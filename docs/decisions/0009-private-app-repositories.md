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
- **The repository credential** is a read-only **deploy key**, sealed
  ([ADR 0006](0006-cluster-secrets.md)) in
  `clusters/prod/<repo>-repo.sealed.yaml`, in the `argocd` namespace with the
  label `argocd.argoproj.io/secret-type: repository`, and the Application uses
  the `git@github.com:` URL. A deploy key is scoped to one repository, can't
  write, and doesn't expire, unlike a fine-grained token, and `gh` can create
  one, which it can't do for a token. It belongs here rather than in the app
  repo, because Argo CD has to read it before it can read the app repo at all.
- **The image** is a **public** package, even though the repository is
  private, so there is no pull secret. A pull secret would need a classic
  token with `read:packages`, since fine-grained tokens can't read ghcr.io,
  and that scope covers every package on the account and expires. This is only
  acceptable while the image holds nothing secret. An app whose image does
  would add a sealed `ghcr-pull` secret in its own namespace instead.

Argo CD's `retry` covers the first sync racing the credential: until the
controller has decrypted it, the repository reads as not found, and the next
attempt succeeds.

## Consequences
- A private app costs one deploy key and one `kubeseal` command, once, and
  nothing per deploy. Nothing expires.
- Its image is world-readable. Check it holds no secrets before choosing this.
- Making the repository public would remove the deploy key too, at the cost of
  publishing the code. That is the app's call, not the cluster's.
