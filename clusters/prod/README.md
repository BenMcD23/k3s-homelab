# clusters/prod

What Argo CD deploys. The `argocd` Ansible role creates one Application —
`prod`, an app-of-apps — pointed at this directory, recursing. Anything
committed here that is a Kubernetes manifest gets applied to the cluster;
Ansible is not involved again ([ADR 0005](../../docs/decisions/0005-argocd-bootstrap-and-access.md)).

Each file is a child Application, so each thing gets its own sync status:

| File | What | Where its manifests live |
|------|------|--------------------------|
| `sealed-secrets.yaml` | Sealed Secrets controller ([ADR 0006](../../docs/decisions/0006-cluster-secrets.md)) | upstream Helm chart |
| `traefik.yaml` | Not an Application: values for k3s's bundled Traefik — one replica on each oracle node behind the OCI load balancer, the public front door | k3s HelmChart in `kube-system` |
| `cloudnative-pg.yaml` | CloudNativePG operator ([ADR 0007](../../docs/decisions/0007-sms-api-placement-and-ha.md)) | upstream Helm chart |
| `sms-api.yaml` | SMS API, prod (`main`) and dev (`development`) | `deploy/` in [SMS_Scrapers_API](https://github.com/BenMcD23/SMS_Scrapers_API) |
| `chatbot.yaml` | Docs assistant (RAG), cluster-internal, called by the SMS API | `deploy/` in [RAFAC-Chatbot](https://github.com/BenMcD23/RAFAC-Chatbot) |
| `cert-manager.yaml` | cert-manager and the `letsencrypt` ClusterIssuer (HTTP-01 via Traefik) | upstream Helm chart |
| `polymarket-collector.yaml` | Polymarket order-book collector, research only, on an oracle node | `deploy/polymarket/` in Trading-Research (**private**) |
| `previews.yaml` | Preview stacks: a branch of the API, SMS site and cadet portal on seeded data, started by a `preview` label ([ADR 0010](../../docs/decisions/0010-preview-stacks.md)) | `previews/` in this repo |
| `trading-research-repo.sealed.yaml` | Not an Application: Argo CD's read-only deploy key for Trading-Research ([ADR 0009](../../docs/decisions/0009-private-app-repositories.md)) | sealed here, by the command below |

App manifests live in the app's own repo, so a change to code and its
deployment is one PR. This directory only says which apps exist and where
to find them.

Secrets are `SealedSecret` objects committed next to the app's manifests
([ADR 0006](../../docs/decisions/0006-cluster-secrets.md)).

A **private** app repository also needs a sealed read credential here, in the
`argocd` namespace ([ADR 0009](../../docs/decisions/0009-private-app-repositories.md)).
For Trading-Research, a read-only deploy key (the Application uses the
`git@github.com:` URL to match):

```bash
ssh-keygen -t ed25519 -N '' -C argocd-k3s-homelab -f key
gh repo deploy-key add key.pub --repo BenMcD23/Trading-Research --title "Argo CD (k3s-homelab), read-only"
kubectl create secret generic trading-research-repo -n argocd \
    --from-literal=type=git \
    --from-literal=url=git@github.com:BenMcD23/Trading-Research.git \
    --from-file=sshPrivateKey=key --dry-run=client -o yaml \
  | kubectl label --local -f - argocd.argoproj.io/secret-type=repository -o yaml \
  | kubeseal -o yaml > clusters/prod/trading-research-repo.sealed.yaml
shred -u key key.pub
```

Placement is not automatic. Every workload picks its node with a
`nodeSelector` on `role=interactive`, `role=batch` or `role=edge`
([ADR 0004](../../docs/decisions/0004-workload-placement.md)), and anything
that might run on oracle needs an arm64 image.

Anything that needs to be reachable gets its own name on the tailnet by
adding an Ingress with `ingressClassName: tailscale` and its own hostname
in `spec.tls[0].hosts`. Add the `tailscale.com/funnel: "true"` annotation to
publish it to the internet, which also needs the `funnel` node attribute for
`tag:k8s` in the tailnet ACL.
