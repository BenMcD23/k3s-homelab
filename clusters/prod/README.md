# clusters/prod

What Argo CD deploys. The `argocd` Ansible role creates one Application —
`prod`, an app-of-apps — pointed at this directory, recursing. Anything
committed here that is a Kubernetes manifest gets applied to the cluster;
Ansible is not involved again ([ADR 0005](../../docs/decisions/0005-argocd-bootstrap-and-access.md)).

**Still empty.** Argo CD syncs it happily and deploys nothing, which is the
intended state until there is something to put here. In practice the next
thing is a child Application per workload rather than raw manifests, so
each one gets its own sync status in the UI.

One thing to settle first: anything needing a Kubernetes Secret is blocked
on the in-cluster secrets question that
[ADR 0002](../../docs/decisions/0002-secrets-management.md) left open —
Sealed Secrets, SOPS via KSOPS, or External Secrets. Workloads that need no
secrets can land before that is decided.

Placement is not automatic. Every workload picks its node with a
`nodeSelector` on `role=interactive`, `role=batch` or `role=edge`
([ADR 0004](../../docs/decisions/0004-workload-placement.md)), and anything
that might run on oracle needs an arm64 image.
