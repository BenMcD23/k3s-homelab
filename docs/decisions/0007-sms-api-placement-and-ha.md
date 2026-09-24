# 7. SMS API: runs on squadron, fails over to home

## Status
Accepted. An exception to [ADR 0004](0004-workload-placement.md) for one
workload.

## Context
ADR 0004 puts anything a person uses on home, because squadron's WiFi is the
link most likely to go away. For the SMS API that is the wrong trade:

- Squadron has the best CPU, and the scrapers drive Chromium.
- Squadron's link is not randomly bad. It is predictably bad: Wednesday and
  Friday evenings, when the building is full and the WiFi is throttled.
- The database must survive a node going down.

## Decision
**Database: CloudNativePG, two instances.** One is on home and one on
squadron (required anti-affinity), with streaming replication. If the
primary's node drops, the operator promotes the replica in about a minute.
oracle holds no instance.

**The primary lives on squadron, except 17:00–23:00 Europe/London on
Wednesday and Friday, when it lives on home.** A CronJob in the app repo
(`deploy/overlays/prod/switchover.yaml`) checks every 10 minutes and does a
CNPG switchover when the primary is on the wrong node. It is a reconciler,
not a timer. That means it also fails back to squadron after an outage, but
only once squadron's replica has been Ready for 30 minutes, so a flapping
link doesn't bounce the primary.

**The API follows the primary.** It has preferred pod affinity to the
instance labelled `cnpg.io/instanceRole=primary`, and the CronJob restarts it
when the two end up on different nodes. It runs as one replica with a
zero-downtime rolling update. The in-process scheduler only runs in the pod
holding a Postgres advisory lock (`app/core/leader.py`), so the brief overlap
never runs a job twice.

**The CNPG operator prefers oracle.** It is the thing that performs
failover, so it must not share fate with either database node. It is the one
platform component that is not pinned to home.

A latency-probe that moves pods when the API is slow was considered and
rejected. Kubernetes has no such mechanism, so it would be a controller to
write, and the slowness is predictable enough to schedule around.

## Consequences
- **Failover loses recent writes.** Replication is async, so the last second
  or so of writes on a primary that dies are lost. Synchronous replication
  would stop that, but every write would then wait on squadron's WiFi.
- **Every switchover costs a few seconds of downtime**, twice each busy
  evening, and kills any scrape running at that moment.
- **The Tailscale proxy is still a single point of failure.** Proxies use the
  `homelab` ProxyClass, which pins them to home. If home dies, the database
  fails over fine but the Funnel endpoint is gone until home is back. The
  upgrade is an HA ProxyGroup with a replica per node.
- **A partitioned squadron can briefly run a second API.** If squadron loses
  the tailnet but keeps internet, the old pod can't be killed. Its scheduler
  stops within about 15 seconds, because its lock connection to the old
  primary dies (the primary also shuts itself down). A job that was already
  mid-run finishes.
- The image is amd64-only, so neither the API nor the database can land on
  oracle.
