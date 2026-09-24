# 2. Secrets: SOPS + age

## Status
Accepted for infrastructure secrets. In-cluster secrets: see
[ADR 0006](0006-cluster-secrets.md) (Sealed Secrets).

## Context
The repo needs somewhere to keep a Tailscale auth key. Plaintext in git is
not an option even in a private repo, because git history keeps it
forever and this repo may end up public.

There are two kinds of secret here and they do not have the same answer:

1. **Infrastructure secrets** — used by Ansible and Terraform before k3s
   exists. The Tailscale auth key is the only one so far. These are plain
   files, not Kubernetes objects, and there is no cluster running to
   decrypt them.
2. **Cluster secrets** — ArgoCD repo tokens, image pull credentials,
   application config. These are Kubernetes Secrets used by a running
   cluster through GitOps.

This file decides the first kind only.

## Decision
[SOPS](https://github.com/getsops/sops) for encryption, with
[age](https://github.com/FiloSottile/age) holding the keys.

GPG was rejected because its key management is harder for no benefit here.
Cloud KMS was rejected because it adds a cloud dependency to a homelab
cluster.

### Generating the key
Done once, by hand. Never by Ansible or CI.

```bash
age-keygen -o ~/.config/sops/age/keys.txt
# prints: Public key: age1...
```

The **private key** stays at `~/.config/sops/age/keys.txt` on the
operator's machine. It is never committed and never copied onto a node.
Back it up offline. If it is lost, every secret in the repo has to be
rotated and re-encrypted from scratch.

The **public key** is not secret. It goes in `.sops.yaml` at the repo root
and can be committed.

### .sops.yaml
This decides which files get encrypted and for whom:

```yaml
creation_rules:
  - path_regex: infra/ansible/.*\.sops\.ya?ml$
    age: age1TODO_REPLACE_WITH_REAL_PUBLIC_KEY
```

Any file under `infra/ansible/` ending in `.sops.yaml` or `.sops.yml` is
encrypted on write and decrypted on read, as long as SOPS can find the
private key.

`ansible-vault` was considered and rejected. It means managing another
password, and SOPS works with Ansible through the `community.sops` vars
plugin without one.

### Day to day
```bash
sops infra/ansible/inventory/group_vars/all/secrets.sops.yaml
git add infra/ansible/inventory/group_vars/all/secrets.sops.yaml
```

Only the encrypted version is ever written to disk in the repo.

## Cluster secrets
Decided in [ADR 0006](0006-cluster-secrets.md): Sealed Secrets, with the
sealing key backed up by SOPS. The options as they stood:

**Sealed Secrets.** A controller in the cluster holds a private key.
`kubeseal` encrypts against its public key, the encrypted object is
committed, and the controller decrypts it inside the cluster. It fits
GitOps well, since ArgoCD just applies the object with no plugin needed.

The catch is that the key lives inside the cluster. If the cluster is
rebuilt and that key was not backed up, every sealed secret in git becomes
unreadable. Choosing this means backing up the sealing key is not
optional.

**SOPS and age, reused from above.** One tool for the whole repo, and the
key is offline so it survives losing the cluster. The cost is that ArgoCD
needs a plugin such as KSOPS to decrypt at sync time, which is more
fiddly than it sounds.

**External Secrets Operator** pointed at a real secret store. The most
capable option and the most to run for three machines.

The offline key is the appealing part of reusing SOPS, but the ArgoCD
integration cost is real. Better to decide this with the ArgoCD work in
front of us.

## Consequences
- One private key, held by one person, protects every infrastructure
  secret in the repo. Fine for a single operator. A team would need a key
  each and a list of recipients.
- Anyone or anything else that needs to decrypt has to be given the key
  separately. Not an issue while there is one operator.
- The cluster secrets question is settled in ADR 0006.
