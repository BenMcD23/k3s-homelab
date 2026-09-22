# 5. Argo CD: bootstrapped by Ansible, published by the Tailscale operator

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
firewall is the only thing holding that back, and changes to it are a
separate piece of work. There is no DNS name for this cluster, no
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
wherever there is room), and `server.insecure` so TLS is terminated in
front of it rather than twice.

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

### The UI is published by the Tailscale Kubernetes operator
Not by an ingress controller, and not by `tailscale serve` on the node.

The operator watches for Ingresses with `ingressClassName: tailscale` and
gives each one **its own device on the tailnet** — its own name, its own
Let's Encrypt certificate, its own entry in the device list. Argo CD gets
`https://argocd.<tailnet>.ts.net`.

`argocd_expose` has three settings:

- **`cluster`** — no Ingress. `kubectl port-forward` only.
- **`tailnet`** (default) — reachable from any device logged into the
  tailnet, and from nowhere else.
- **`funnel`** — the `tailscale.com/funnel` annotation on the same
  Ingress. Reachable from the open internet.

Nothing is bound on a node. No ingress controller is in the path, there is
no DNS record to own, no certificate to renew, no port forwarded on a home
router, and — for `funnel` — no dependency on having a public IP, which is
the only reason publishing from home is possible at all.

### Why the operator rather than `tailscale serve`
`tailscale serve` runs on a *node*, so the URL is always that node's
name — `home-server.<tailnet>.ts.net` — and reaching the service behind it
needs a NodePort, which binds every interface on every node including LAN
ones. Both of those get worse with every service added: the second one
needs a path or a port on the same hostname.

With the operator each service is addressed by its own name, the way it
would be with real DNS, and nothing is published on a node at all. The
NodePort and its LAN exposure disappear entirely. It also generalises:
every workload deployed through Argo CD later gets the same treatment by
adding an Ingress, with no further decisions.

The cost is a second bootstrap component and one more secret. Taken
deliberately, and taken now rather than later — nothing exists yet, so
this is the cheapest it will ever be. Migrating a cluster with services on
it would mean changing every URL.

### The operator is bootstrap, not a workload
It is installed by Ansible, in its own `tailscale_operator` role, before
Argo CD — even though "Ansible installs Argo CD and nothing else" is the
rule above.

The reason is not convenience. The operator is what publishes Argo CD's
own UI, and a front door cannot depend on the thing it is the front door
to. If Argo CD deployed the operator and a sync broke, the UI needed to
see *why* it broke would be the thing that went down with it. Bootstrap
components are the ones you need working in order to debug everything
else.

Its images are pinned to the release being installed. Upstream ships both
the operator and the proxies as `:stable`, which would let an ordinary pod
restart upgrade the operator underneath a running cluster — the same
reason `k3s_server_version` exists.

The proxy pods it creates are pinned to `role=interactive` through a
ProxyClass set as the operator's default. A proxy pod is where traffic for
a published service actually lands, which makes it user-facing whatever is
behind it — left to the scheduler one could land on squadron, and ADR 0004
exists precisely to stop that.

### The operator's OAuth client is an infrastructure secret
The operator needs a Tailscale OAuth client to mint auth keys. It comes
from SOPS via Ansible, in the same class as the Tailscale auth key and the
k3s token: a bootstrap secret needed *before* GitOps can publish anything,
handled by the mechanism ADR 0002 already decided for exactly that class.

This is deliberately **not** a precedent for application secrets. Those
are still open — Sealed Secrets, SOPS via KSOPS, or External Secrets — and
still to be decided when the first workload needs one.

One trap worth recording: upstream's manifest ships a placeholder
`operator-oauth` Secret whose two keys are explicitly null. Applied
server-side, that does not leave real credentials alone, it blanks them on
every run. The role drops the placeholder from the kustomize build and
writes the real Secret separately, before the operator starts.

### `tailnet` is the default, and should stay the default
`funnel` is deliberately not the default. It is a real option and it is
one annotation away, but it puts a password prompt for a cluster-admin
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
- Two prerequisites in the Tailscale admin console that Ansible cannot do:
  `tagOwners` for `tag:k8s-operator` and `tag:k8s` in the ACL policy, and
  an OAuth client with the `auth_keys` write scope. `funnel` additionally
  needs the funnel node attribute. Without them the operator runs, never
  authenticates, and the only symptom is an Ingress that never gets an
  address — so the role reads its logs and says so.
- Argo CD and the proxy pod both live on home. If home's broadband is
  down, the UI is gone and syncs stop until it is back. The cluster and
  everything already deployed keep running — Argo CD is not in the request
  path of anything.
- Renaming the tailnet changes the URL. It is one line in the inventory
  (`tailnet:`), because `ansible_host` is a raw Tailscale IP and the
  kubeconfig points at an IP, so nothing else depends on the name
  resolving.
- Traffic between the Tailscale proxy pod and argocd-server is plaintext
  inside the cluster, because `server.insecure` is what stops Argo CD
  terminating TLS a second time behind a proxy that already did. This is
  the standard Argo CD ingress setup.
- The `argocd` CLI talks gRPC and needs `--grpc-web` through this proxy.
  The web UI does not care.
- traefik stays enabled. Nothing here needs it, so the ingress question
  the README flags is still open and still cheap to answer later.
- Upgrades are a version bump and a checksum refresh, for both roles.
  Deviating from upstream in only a few patches is what keeps that true.
