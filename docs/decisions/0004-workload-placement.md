# 4. Where workloads run

## Status
Accepted. The SMS API is an exception, see
[ADR 0007](0007-sms-api-placement-and-ha.md).

## Context
The three machines are good at different things:

- **home** — reliable network, modest CPU (i5-10400T), amd64.
- **squadron** — best CPU and the only GPU, amd64. On remote WiFi that is
  unreliable, so it could drop off the network.
- **oracle** — always on, weakest CPU (1 OCPU), arm64.

Left to itself the scheduler spreads pods by available capacity. That
would put user-facing services on squadron, which is the one machine whose
network might go away.

## Decision
- **squadron** runs batch and retryable work. Encoding jobs, scheduled
  scrapers, anything where running late is not a problem. It also takes
  GPU work once [ADR 0003](0003-gpu-scheduling.md) is built.
- **home** runs anything a person uses directly: the cadet portal, the
  scraper API, dashboards. These are pinned there rather than left to the
  scheduler.
- **oracle** runs small always-on services that benefit from being
  reachable without depending on a home broadband connection. It is
  **arm64**, so anything running there needs a multi-arch or native arm64
  image. An amd64-only image does not fail with a clear error, it just
  crash-loops.

## How it is enforced
Each node gets a label, set once:

| Node | Label |
|------|-------|
| home | `role=interactive` |
| squadron | `role=batch` |
| oracle | `role=edge` |

Workloads select the node they belong on with `nodeSelector`.

Images that might run on oracle are built with
`docker buildx build --platform linux/amd64,linux/arm64`. Enforcing that
in CI is future work.

## Consequences
- Nothing balances across nodes automatically. Placement is written down
  per workload. That is the point: automatic placement is how a
  user-facing service ends up on squadron the week its WiFi plays up.
- Multi-arch builds add time to CI for anything targeting oracle.
