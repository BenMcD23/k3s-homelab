# 6. Cluster secrets: Sealed Secrets, sealing key backed up with SOPS

## Status
Accepted. Settles the question [ADR 0002](0002-secrets-management.md) left
open.

## Context
The first workload (the SMS API) needs a dozen secrets: API keys, a Google
service-account key, an encryption key. They lived in hand-edited `.env`
files on the server, outside git, which meant a code deploy never carried a
new variable and nobody could see what the server was actually running.

ADR 0002 listed three options: Sealed Secrets, SOPS via KSOPS, and External
Secrets Operator.

## Decision
**Sealed Secrets**, with its private key backed up SOPS-encrypted in this
repo.

- The controller runs in `kube-system`, installed by Argo CD from
  `clusters/prod/sealed-secrets.yaml`.
- Apps commit `SealedSecret` objects next to their manifests. They are
  encrypted to the controller's public key and scoped to one namespace and
  name, so a sealed secret copied into another namespace is useless.
- Argo CD applies them like any other object, with no plugin.

KSOPS was rejected for the reason ADR 0002 gave: a sync-time decryption
plugin in Argo CD is the fiddly part, and it would put the age key inside
the cluster anyway. External Secrets needs a real secret store to point at,
which is more to run than three machines justify.

### The key backup
The weakness ADR 0002 named is that the sealing key lives in the cluster. It
is closed by backing that key up with the tool that already protects
infrastructure secrets:

```bash
kubectl -n kube-system get secret -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml \
  > infra/sealed-secrets/sealing-key.sops.yaml
sops --encrypt --in-place infra/sealed-secrets/sealing-key.sops.yaml
```

To restore on a rebuilt cluster, before the controller starts or followed by
a controller restart:

```bash
sops --decrypt infra/sealed-secrets/sealing-key.sops.yaml | kubectl apply -f -
kubectl -n kube-system rollout restart deploy/sealed-secrets-controller
```

The controller renews its key every 30 days and keeps the old ones, so old
sealed secrets still decrypt. Existing secrets are not re-sealed, and a new
key only matters for secrets sealed after it. **Re-run the backup after a
renewal**, or anything sealed since then is lost with the cluster.
<!-- ponytail: manual backup; a CronJob that diffs the key list would catch a missed renewal -->

### Day to day
```bash
kubectl create secret generic <name> -n <ns> --from-env-file=<file> --dry-run=client -o yaml \
  | kubeseal -o yaml > sealed-secret.yaml
```

To change one value, re-seal the whole thing. `kubeseal --merge-into`
updates a single key in place.

## Consequences
- Secrets are in git, encrypted, next to the code that reads them. No `.env`
  on any server.
- Sealing needs cluster access, because kubeseal fetches the public key from
  the controller. `kubeseal --fetch-cert > cert.pem` lets you seal offline.
- The age key now protects the cluster's secrets too, not just the
  infrastructure's. Its offline backup matters more than it did.
