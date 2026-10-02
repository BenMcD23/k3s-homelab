# 8. squadron becomes an agent; oracle2 takes its etcd vote

## Status
Accepted, 2026-10-02. Supersedes the voter list in
[ADR 0001](0001-etcd-topology.md) and the "squadron stays an etcd member"
note in [ADR 0007](0007-sms-api-placement-and-ha.md).

## Context
squadron's WiFi/mobile link does not fail cleanly, it stalls. Each stall made
the other servers time out dialling its etcd peer port, and requests to the
`kubernetes` Service (which balances over every API server) that landed on
squadron hung. On 2026-09-29 that was enough to fail the SMS database over
twice while its primary sat on home, a healthy node.

Taking squadron out of etcd with only home and oracle left would mean two
voters, quorum 2 of 2, and no tolerance for losing either.

## Decision
- A second Oracle A1 VM, **oracle2** (1 OCPU / 6GB, always free), joins as a
  full server in FAULT-DOMAIN-2; oracle is in FAULT-DOMAIN-3. London has a
  single availability domain, so a fault domain is the most separation
  available.
- **squadron is a k3s agent** (`roles/k3s_agent`): it runs workloads, keeps
  `role=batch` and its local-path volumes, but has no etcd vote and no API
  server.
- Voters are home, oracle and oracle2: quorum 2 of 3.

## Consequences
- A squadron outage no longer touches etcd or the API, only what runs on it.
- Both Oracle VMs share a region. A London-wide OCI outage takes two of three
  voters and freezes the API until one returns. Running workloads carry on.
- oracle2 is a normal server, untainted, `role=edge`. Nothing selects it
  specifically; the CNPG operator and Traefik prefer or require `edge`, and
  Traefik stays on oracle because its certificate volume lives there.
- squadron's old server state is kept at
  `/var/lib/rancher/k3s-server-backup-2026-10-02` until it is clearly not
  needed.
