# 9. Private app repositories

## Status
Accepted. Answers the question [ADR 0005](0005-argocd-bootstrap-and-access.md)
left open.

## Context
Every app so far lives in a public repository, so Argo CD reads them
anonymously and their images on ghcr.io are public. The Polymarket collector
lives in Trading-Research, which is private. That needs two things the public
apps never did:

- **Argo CD has to authenticate** to read the manifests.
- **The kubelet has to authenticate** to pull the image, because a package
  published from a private repository is private.

## Decision
Both are SealedSecrets ([ADR 0006](0006-cluster-secrets.md)), each scoped
as tightly as GitHub allows.

- **The repository credential** lives here, in
  `clusters/prod/<repo>-repo.sealed.yaml`, in the `argocd` namespace with the
  label `argocd.argoproj.io/secret-type: repository`. It holds a
  **fine-grained** token for that one repository with read-only *Contents*,
  so a leak exposes one repo's code and can't change anything. It belongs here
  rather than in the app repo, because Argo CD has to read it before it can
  read the app repo at all.
- **The image pull secret** lives in the app repo next to its manifests, like
  any other app secret, as a `kubernetes.io/dockerconfigjson` secret named
  `ghcr-pull` in the app's namespace. It holds a **classic** token with only
  `read:packages`, because fine-grained tokens can't read ghcr.io packages.
  That scope covers every package on the account, which is the weaker of the
  two, and the reason it is sealed to one namespace.

Argo CD's `retry` covers the first sync racing the credential: until the
controller has decrypted it, the repository reads as not found, and the next
attempt succeeds.

## Consequences
- A private app costs two `kubeseal` commands once, and nothing per deploy.
- Both tokens expire. GitHub mails a reminder before it happens. Re-seal and
  commit, or the app stops syncing (repo token) or stops starting new pods
  (pull token). Running pods keep running.
- Making the repository public would remove both, at the cost of publishing
  the code. That is the app's call, not the cluster's.
