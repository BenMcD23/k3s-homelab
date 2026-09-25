# clusters/prod

What Argo CD deploys. The `argocd` Ansible role creates one Application —
`prod`, an app-of-apps — pointed at this directory, recursing. Anything
committed here that is a Kubernetes manifest gets applied to the cluster;
Ansible is not involved again ([ADR 0005](../../docs/decisions/0005-argocd-bootstrap-and-access.md)).

Each file is a child Application, so each thing gets its own sync status:

| File | What | Where its manifests live |
|------|------|--------------------------|
| `sealed-secrets.yaml` | Sealed Secrets controller ([ADR 0006](../../docs/decisions/0006-cluster-secrets.md)) | upstream Helm chart |
| `traefik.yaml` | Not an Application: values for k3s's bundled Traefik — pinned to oracle, Let's Encrypt, the public front door on oracle's own IP | k3s HelmChart in `kube-system` |
| `cloudnative-pg.yaml` | CloudNativePG operator ([ADR 0007](../../docs/decisions/0007-sms-api-placement-and-ha.md)) | upstream Helm chart |
| `sms-api.yaml` | SMS API, prod (`main`) and dev (`development`) | `deploy/` in [SMS_Scrapers_API](https://github.com/BenMcD23/SMS_Scrapers_API) |

App manifests live in the app's own repo, so a change to code and its
deployment is one PR. This directory only says which apps exist and where
to find them.

Secrets are `SealedSecret` objects committed next to the app's manifests
([ADR 0006](../../docs/decisions/0006-cluster-secrets.md)).

Placement is not automatic. Every workload picks its node with a
`nodeSelector` on `role=interactive`, `role=batch` or `role=edge`
([ADR 0004](../../docs/decisions/0004-workload-placement.md)), and anything
that might run on oracle needs an arm64 image.

Anything that needs to be reachable gets its own name on the tailnet by
adding an Ingress with `ingressClassName: tailscale` and its own hostname
in `spec.tls[0].hosts`. Add the `tailscale.com/funnel: "true"` annotation to
publish it to the internet, which also needs the `funnel` node attribute for
`tag:k8s` in the tailnet ACL.
