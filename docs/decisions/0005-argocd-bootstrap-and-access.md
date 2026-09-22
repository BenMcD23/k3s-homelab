# 5. Argo CD: bootstrapped by Ansible, published over Tailscale

## Status
Accepted

## Context
The README has said from the start that Ansible configures hosts and Argo
CD runs workloads. That leaves one thing undecided: who installs Argo CD.

It cannot install itself. Something outside the cluster has to put the
first copy there, and after that Argo CD is the only thing that should be
applying manifests — two tools writing the same objects is how drift
starts.

The second question is how anyone reaches the UI. Argo CD's admin account
can create a workload in any namespace, which makes it cluster-admin by
another route. "Externally available" therefore is not a convenience
setting; it decides who gets a shot at that account.

The machines constrain the options. home and squadron sit behind
residential NAT with no inbound ports and no static address. oracle has a
public IP, but its host firewall rejects everything except 22 and the
console security list in front of it allows all TCP from 0.0.0.0/0 — the
firewall is the only thing holding that back, and ADR-worthy changes to it
are a separate piece of work. There is no DNS name for this cluster, no
cert-manager and no ADR covering ingress.

What all three machines do share is the tailnet. Every node already runs
tailscaled, and so does the operator's workstation.

## Decision

### Ansible installs it, once, from the first server
A new `argocd` role, bound to the `k3s_first_server` inventory group for
the same reason `--cluster-init` is (ADR 0001): cluster-wide manifests
should be applied from exactly one place, decided by inventory rather than
by a flag someone can pass twice.

The role downloads the pinned upstream `install.yaml`, checks it against a
recorded sha256, and applies it through kustomize with two patches: a
`role=interactive` nodeSelector on every Deployment and StatefulSet (ADR
0004 — Argo CD is used by a person, so it belongs on home rather than
wherever there is room), and a NodePort on `argocd-server` when the UI is
being published.

Server-side apply, not because it is tidier but because the
`applicationsets` CRD is 1.4MB and a client-side apply would try to store
that in a 256KB annotation.

### Everything after Argo CD is a commit, not a playbook run
The role creates exactly one Application: an app-of-apps root pointing at
`clusters/prod/` in this repo. Adding a workload means committing a
manifest there. Ansible never touches the cluster again.

The repo is public, so Argo CD reads it anonymously. A private repo would
need a credential in the cluster, which is the question ADR 0002 left
open.

### The UI is published over Tailscale, not over an ingress
`argocd_expose` has three settings:

- **`cluster`** — nothing is published. `kubectl port-forward` only.
- **`tailnet`** (default) — `tailscale serve` puts the UI on
  `https://home-server.tail02e471.ts.net`, reachable from any device
  logged into the tailnet and from nowhere else.
- **`funnel`** — `tailscale funnel`, the same handler with Tailscale's
  public relays in front of it. Reachable from the open internet.

Tailscale terminates a real Let's Encrypt certificate for the MagicDNS
name and proxies to the NodePort on `127.0.0.1`. That means no ingress
controller in the path, no DNS record to own, no certificate to renew, no
port forwarded on a home router, and — for `funnel` — no dependency on
having a public IP at all, which is the only reason publishing from home
is possible without one.

### `tailnet` is the default, and should stay the default
`funnel` is deliberately not the default. It is a real option and it is
one variable away, but it puts a password prompt for a cluster-admin
account on the public internet, where it is found by scanners within
hours. Argo CD is a well-known target with a history of authentication and
path-traversal CVEs, and this cluster has no SSO, no MFA, no WAF and no
rate limiting in front of it.

Against that: with `tailnet`, the UI is already reachable from a phone, a
laptop on someone else's WiFi, or anywhere else — the tailnet is not the
home LAN, and being on it is not the same as being at home. The thing
`funnel` actually adds is access from a device that is *not* yours, which
is a narrow benefit for the cost.

If `funnel` is ever turned on, it should come with OIDC on the admin
account first, not on its own.

## Consequences
- Argo CD lives on home. If home's broadband is down, the UI is gone and
  syncs stop until it is back. The cluster and everything already deployed
  keep running — Argo CD is not in the request path of anything.
- HTTPS certificates have to be enabled for the tailnet in the Tailscale
  admin console, and `funnel` additionally needs the funnel node attribute
  in the ACL policy. Neither can be set from Ansible.
- The `argocd-server` NodePorts bind every interface on every node, not
  just home's tailscale0. On oracle the host firewall rejects them; on home
  and squadron they are reachable from those LANs, still behind an Argo CD
  login. Narrowing that needs a cluster-wide kube-proxy setting and is not
  worth it here.
- traefik stays enabled. Argo CD does not bring its own ingress and nothing
  in this decision needs one, so the ingress question the README flags is
  still open and still cheap to answer later.
- Upgrades are one line: bump `argocd_version`, refresh the checksum,
  re-run. Deviating from upstream in only two patches is what keeps that
  true.
