# 1. Embedded etcd, 3 servers, quorum 2

## Status
Accepted

## Context
The cluster has three machines:

- **home** — on the home LAN, reliable.
- **squadron** — at a remote site on WiFi. The connection is unreliable and
  the node could drop off the network. It has been fine recently, but the
  cluster should not assume it stays up.
- **oracle** — an Oracle Cloud VM. Always on, but only 1 OCPU.

k3s can run HA in two ways: embedded etcd, or an external database.
An external database means running and backing up a database outside the
cluster it supports, which is another thing to maintain. Embedded etcd
needs nothing extra and k3s manages it.

## Decision
Run all three machines as k3s servers with embedded etcd.

Quorum is 2 of 3. home and oracle are the two stable nodes, so between
them they hold quorum on their own. If squadron drops off, the cluster
keeps working, and squadron catches up when it comes back.

If home or oracle goes down while squadron is also offline, quorum is lost
and the API server stops accepting writes until two nodes are back. A
5-node cluster would survive two failures at once, but there are only
three machines.

## The --cluster-init flag
The first k3s server has to start with `--cluster-init`. Without it, k3s
uses sqlite instead of etcd. The cluster still starts and looks healthy,
but a second server cannot join later. There is no supported way to switch
from sqlite to etcd afterwards, so the fix is to rebuild the cluster.

Start order:

1. home, as the first server (most reliable machine):
   `k3s server --cluster-init`
2. oracle and squadron join it:
   `k3s server --server https://<home-tailnet-ip>:6443 --token <token>`

All three advertise their Tailscale IP rather than a LAN or public
address. The tailnet is the only network all three machines share (see
[ADR 0004](0004-workload-placement.md)).

## Consequences
- Losing home or oracle while squadron is also offline stops the API
  server until two nodes are back.
- If squadron is offline for a long time, rejoining means catching up the
  etcd log over a slow link. That is fine for the work it runs.
- No separate database to run, patch, or back up.
