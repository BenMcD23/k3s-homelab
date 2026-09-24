# k3s HA cluster

Three-node k3s cluster with embedded etcd, meshed over Tailscale.
Infrastructure as code: Terraform for the Oracle Cloud node, Ansible for
host configuration, ArgoCD for workloads.

**Current state: the cluster is up.** The `base` role prepares hosts, the
`k3s_server` role stands up the three-server cluster, and the `argocd`
role bootstraps ArgoCD onto it — all three have been run against the real
nodes. Workloads (GPU scheduling, and anything under `clusters/prod/`) are
next.

## Nodes

| Alias      | Hostname      | User        | Arch    | Notes |
|------------|---------------|-------------|---------|-------|
| `home`     | `home-server` | `ben`       | amd64   | Lenovo M70q, i5-10400T, 16GB. Reliable home LAN. Founding etcd member. |
| `squadron` | `317server`   | `server317` | amd64   | i7-4790K, GTX 1070, 16GB. Remote site on WiFi. Best CPU and the only GPU, but the connection is unreliable and it could drop off. |
| `oracle`   | `k8s-node`    | `ubuntu`    | aarch64 | OCI A1.Flex, 1 OCPU / 6GB. **Already provisioned — never recreate**, Ampere capacity is scarce. |

All three mesh over Tailscale (`tail02e471.ts.net`). The tailnet is the
only network all three nodes share — k3s binds to Tailscale IPs, not LAN
or public addresses.

## Layout

```
infra/terraform/oracle/   Adopts the existing OCI instance/VCN/subnet/security list
infra/ansible/            Inventory + roles
  roles/base/               Users, SSH, swap, sysctls, chrony, Tailscale
  roles/k3s_server/         k3s servers with embedded etcd, bound to the tailnet
  roles/tailscale_operator/ Tailscale operator - gives services their own tailnet names
  roles/argocd/             ArgoCD bootstrap, published on the tailnet
docs/decisions/           ADRs
clusters/prod/            What ArgoCD deploys - the app-of-apps root points here
```

## Prerequisites

```bash
# On your workstation (WSL is fine - it routes to the tailnet via Windows)
sudo apt install ansible age
# sops is not in Ubuntu's repos - install the .deb from upstream:
curl -fsSL -o /tmp/sops.deb https://github.com/getsops/sops/releases/download/v3.13.3/sops_3.13.3_amd64.deb
sudo apt install -y /tmp/sops.deb
# terraform: https://developer.hashicorp.com/terraform/install

make deps          # Ansible collections
```

OCI API auth comes from `~/.oci/config` (DEFAULT profile). Set it up with
`oci setup config`, or use Cloud Shell for read-only queries.

## Secrets

SOPS + age. Full detail in
[ADR 0002](docs/decisions/0002-secrets-management.md).

```bash
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt     # once, keep the private half safe
# put the age1... public key into .sops.yaml

cp infra/ansible/inventory/group_vars/all/secrets.sops.yaml.example \
   infra/ansible/inventory/group_vars/all/secrets.sops.yaml

# Four keys to fill in: the Tailscale auth key, the k3s cluster token, and
# the Tailscale OAuth client id/secret (see "ArgoCD" below for that one).
# Generate the token once - every server must share the same value:
openssl rand -hex 32

sops --encrypt --in-place infra/ansible/inventory/group_vars/all/secrets.sops.yaml
```

The encrypted file is safe to commit. The private key never is, and never
leaves your machine.

## Terraform

The Oracle node **already exists**. This config describes it so it can be
managed, not created. First run adopts it into state via `import` blocks:

```bash
cd infra/terraform/oracle
cp terraform.tfvars.example terraform.tfvars    # values are pre-filled
terraform init
terraform plan      # expect: 4 to import, 0 to add, 0 to change, 0 to destroy
terraform apply
```

If plan shows anything other than a clean import, a variable doesn't match
reality — **fix the variable**, never let Terraform reconcile the live
instance. `prevent_destroy = true` is set on the instance, VCN, subnet and
security list as a backstop.

Two values in `terraform.tfvars.example` are guesses and will show as
drift until corrected — the VCN/subnet display names and CIDRs, and the
boot image OCID. Fetch the real ones with:

```bash
oci network vcn get --vcn-id <vcn-ocid> --query 'data.{name:"display-name",cidr:"cidr-blocks"}'
oci network subnet get --subnet-id <subnet-ocid> --query 'data.{name:"display-name",cidr:"cidr-block"}'
oci compute instance get --instance-id <instance-ocid> --query 'data."source-details"'
```

### State

**Local state, for now.** `terraform.tfstate` sits on one machine and is
gitignored. That means: no locking, no history, and losing the workstation
means re-importing everything from scratch. That is recoverable: the
import blocks are kept in `imports.tf` so the path back is written down.
Fine for one operator. A remote backend (OCI Object Storage) is the
upgrade when that stops being true.

### Security list

The live security list allows **all TCP from 0.0.0.0/0**. That is
reproduced as-is in `network.tf` rather than silently corrected — this
config adopts reality. What actually restricts inbound traffic is the
host's `/etc/iptables/rules.v4`, which rejects everything except port 22.
Tightening the security list is a deliberate separate change.

## Ansible

```bash
make lint        # ansible-lint
make validate    # terraform validate + ansible syntax check
make base        # host prep only
make cluster     # k3s bring-up only
make argocd      # Tailscale operator + ArgoCD bootstrap only
make apply       # everything: base role, the cluster, then ArgoCD
```

`site.yml` is five plays: the `base` role across all nodes, then the
first k3s server, then the rest joining it one at a time, then the
Tailscale operator and ArgoCD on the first server. The split is what
enforces bring-up order — see below.

The `base` role is idempotent and safe to re-run. It covers: SSH key +
passwordless sudo, SSH hardening, unattended-upgrades, swap off
(persistently), k8s sysctls and kernel modules, chrony (which replaces
systemd-timesyncd, removed by apt on install), and Tailscale install +
enrolment.

### A note on `--check`

`ansible-playbook site.yml --check` on a host that has not been configured
yet will report failures on tasks that depend on earlier ones. Check mode
simulates the package install, so a later "is the service running" task
looks for something that is not there. That is expected on a first run and
not a sign anything is wrong. Once a host has had the role applied for
real, `--check` should come back clean.

Target one host:

```bash
cd infra/ansible
ansible-playbook site.yml --limit squadron
ansible-playbook site.yml --limit oracle --tags tailscale
```

### SSH hardening

`base_harden_ssh: true` (default) disables root login and password auth.
Confirm key auth works before running this against a machine you cannot
easily get to in person, squadron especially. Otherwise run with
`-e base_harden_ssh=false` and turn it on once you are sure.

## Cluster bring-up

```bash
make cluster        # or: ansible-playbook site.yml --tags k3s
```

Three servers, all running embedded etcd, quorum 2 of 3 ([ADR
0001](docs/decisions/0001-etcd-topology.md)). Order is enforced by the
play structure rather than by remembering to do it right: home is in the
`k3s_first_server` inventory group and bootstraps with `cluster-init`,
then `k3s_additional_servers` (squadron, oracle) join it `serial: 1`, one
at a time.

The token is pre-shared from SOPS rather than scraped off home after the
fact, so all three nodes can be configured in one pass and a rebuilt node
rejoins without a new secret.

Everything binds to the tailnet. `node-ip`, `advertise-address` and the
API server's certificate SANs come from each host's `ansible_host`, which
is its Tailscale IP, and flannel is pinned to `tailscale0`. Before
installing anything the role asserts that address is actually present on
the machine — a stale inventory IP otherwise produces a cluster that comes
up and then cannot talk to itself.

`--cluster-init` is not set from a flag anyone can pass. It comes from
inventory group membership, so there is one source of truth for which node
bootstraps and no way to hand it to a second node by accident.

### Node names and labels

Nodes register as `home`, `squadron` and `oracle` — the inventory aliases,
not the machine hostnames (`home-server`, `317server`, `k8s-node`). That
is `k3s_server_node_name`, set so the cluster matches what ADRs 0003 and
0004 already say. Changing it after a node has registered leaves the old
Node object behind.

Each node carries `role=<node_role>` from the inventory, per [ADR
0004](docs/decisions/0004-workload-placement.md). k3s only applies
`node-label` at first registration, so the role also reconciles it on
every run with `kubectl label --overwrite`. Changing `node_role` in the
inventory and re-running is enough to move a node's placement.

### kubeconfig

The first server's kubeconfig is fetched to
`~/.kube/k3s-homelab.yaml`, repointed from `127.0.0.1` to home's Tailscale
IP, and its cluster/user/context renamed off `default` so it can be merged
with other kubeconfigs:

```bash
export KUBECONFIG=~/.kube/k3s-homelab.yaml
kubectl get nodes -o wide
```

It is cluster-admin. Treat it like a private key — it is written `0600`
and is outside the repo. Set `k3s_server_fetch_kubeconfig: false` to skip
this.

### Version pinning

`k3s_server_version` in `roles/k3s_server/defaults/main.yml` pins the
release. Unpinned would mean a routine re-run could upgrade the cluster
underneath you. Bump that one line to upgrade deliberately; the installer
replaces the binary and restarts the service, and the config file is left
alone.

### Things not decided yet

- `k3s_server_disable` is empty, so traefik, servicelb, local-path and
  metrics-server all install. No ADR covers ingress yet. ArgoCD does not
  need one ([ADR 0005](docs/decisions/0005-argocd-bootstrap-and-access.md)
  publishes it over Tailscale instead), so the question is still open and
  still cheap to answer.
- `secrets-encryption` is on. It is free at `cluster-init` and means
  re-encrypting every existing Secret if turned on later.
- etcd snapshots are k3s defaults: every 12h, 5 retained, **on local disk
  only**. A node that dies takes its snapshots with it. Off-node snapshot
  storage is unbuilt.
- oracle is 1 OCPU. It is a full etcd member and may log slow-fsync
  warnings under load. Expected, not a fault.

## Rebuilding a node from scratch

Assumes the machine is wiped and has Ubuntu 24.04 installed, with a user
matching the inventory (`ben` / `server317` / `ubuntu`).

**1. Get an SSH foothold.** Ansible can't create the access it runs over.
At the machine's keyboard:

```bash
sudo apt update && sudo apt install -y openssh-server
sudo systemctl enable --now ssh
ip -4 addr show scope global | grep inet     # note the address
```

From your workstation:

```bash
ssh-copy-id -i ~/.ssh/id_ed25519_cluster.pub <user>@<lan-ip>
```

**2. Get it on the tailnet.** The inventory addresses hosts by MagicDNS
name, so the node has to be on the tailnet before Ansible can reach it by
its alias. Either install Tailscale by hand at the keyboard:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh
```

...or run the role once over the LAN address and let it do the enrolment:

```bash
ansible-playbook site.yml --limit home --tags base -e ansible_host=192.168.1.x
```

`--tags base` matters here. Without it the k3s play would run too, and
k3s would bind itself to the LAN address you passed in rather than the
node's Tailscale IP.

Set the machine's hostname to match the inventory (`home-server`,
`317server`, `k8s-node`) — MagicDNS names derive from it.

**3. Run the base role.**

```bash
ansible-playbook site.yml --limit <alias> --tags base
```

**4. Rejoin the cluster.** Remove the old etcd member first, or etcd
counts a member that is never coming back toward quorum:

```bash
kubectl delete node <alias>                                  # from a surviving node
ansible-playbook site.yml --limit <alias> --tags k3s         # rejoins with the same token
```

The token is the one already in SOPS, so a rebuilt node rejoins with no
new secret to distribute. If the node being rebuilt is **home**, it does
not re-run `--cluster-init` — the cluster already exists, and the play
treats it as a rejoin like any other. Moving which node bootstraps means
editing `k3s_first_server` in the inventory, and that is only ever
correct for a cluster being built from nothing.

### Oracle is the exception

`k8s-node` cannot be rebuilt this way. The instance must never be
destroyed — Ampere A1 capacity in `uk-london-1` is frequently unavailable,
and a destroyed instance may be unrecreatable for weeks. Recovery for that
node means reinstalling the OS in place, not reprovisioning. This is why
`prevent_destroy` is set and why `terraform apply` should never show
changes against it.

Note also that the Oracle Minimal image ships without `curl`, `chrony` or
`unattended-upgrades` — `roles/base/tasks/packages.yml` installs them
before anything assumes they exist.

## ArgoCD

```bash
make argocd         # or: ansible-playbook site.yml --tags tailscale_operator,argocd
```

Ansible installs two things and nothing else: the Tailscale operator, and
ArgoCD. ArgoCD installs everything after it ([ADR
0005](docs/decisions/0005-argocd-bootstrap-and-access.md)) — the role
creates exactly one Application, an app-of-apps root pointing at
`clusters/prod/`, and from then on adding a workload is a commit rather
than a playbook run.

Like `--cluster-init`, both run on whichever node is in `k3s_first_server`
rather than from a flag, so cluster-wide manifests are applied from one
place. Upstream manifests are pinned by version *and* sha256 in each
role's `defaults/main.yml`; upgrading means bumping both and re-running:

```bash
curl -sL <manifest-url> | sha256sum
```

ArgoCD deviates from upstream in only two patches: a `role=interactive`
nodeSelector on every workload, so it lands on home rather than wherever
the scheduler has room ([ADR
0004](docs/decisions/0004-workload-placement.md)), and `server.insecure`,
because TLS is terminated by the Tailscale proxy in front of it. Staying
close to upstream is what keeps upgrades to one line.

### Before the first run

The operator needs two things set up in the Tailscale admin console.
Ansible cannot do either, and without them it runs, never authenticates,
and the only symptom is a URL that never resolves.

**1. Own the tags** it uses, in the [ACL
policy](https://login.tailscale.com/admin/acls):

```json
"tagOwners": {
  "tag:k8s-operator": [],
  "tag:k8s":          ["tag:k8s-operator"]
}
```

**2. Create an OAuth client** at [Settings →
OAuth](https://login.tailscale.com/admin/settings/oauth) with the
**`auth_keys` write** scope and the **`tag:k8s-operator`** tag. The secret
is shown once. Both halves go in SOPS:

```yaml
tailscale_oauth_client_id: ...
tailscale_oauth_client_secret: tskey-client-...
```

For `funnel` only, you also need the funnel node attribute in the ACL
policy.

### Getting in

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

Username `admin`. Change it in the UI and delete that Secret afterwards —
it is not rotated and not needed once you have.

### External access

ArgoCD gets **its own device on the tailnet**, not a path on a node:

```
https://argocd.tail02e471.ts.net
```

The Tailscale operator watches for Ingresses with `ingressClassName:
tailscale` and registers each one as a tailnet device with its own name
and its own Let's Encrypt certificate. Nothing is bound on any node — no
ingress controller, no NodePort, no DNS record, no forwarded port, no
certificate to renew.

That URL works from any device logged into your tailnet: laptop on someone
else's WiFi, phone on mobile data, anywhere. It is *not* limited to the
home LAN, which is usually what "external access" is actually after.

`argocd_expose` picks how far it goes:

| Value | Reachable from |
|-------|----------------|
| `cluster` | nowhere; `kubectl port-forward` only |
| `tailnet` (default) | any device on the tailnet |
| `funnel` | the open internet |

It is reversible — setting it back and re-running deletes the Ingress,
which is what tells the operator to tear the device down and release the
name.

**On `funnel`:** it works, and it is one annotation. It is not the default
on purpose. ArgoCD's admin account can schedule a pod in any namespace, so
it is cluster-admin by another name, and `funnel` puts its login page
somewhere scanners find within hours — with no SSO, no MFA and no rate
limiting in front of it. The honest version is that `tailnet` already
covers "I want to reach it when I'm out"; `funnel` only adds access from a
device that isn't yours. If you do want it, wire up OIDC on the admin
account first. The reasoning is in ADR 0005.

### A nicer URL

The name is `<device>.<tailnet>.ts.net`. The operator gives you the device
half — `argocd`, from `argocd_hostname`. The tailnet half is
`tail02e471.ts.net` until you [rename the
tailnet](https://login.tailscale.com/admin/dns), which is worth doing: it
is a one-line change here, because `ansible_host` is a raw Tailscale IP
and the kubeconfig points at an IP, so nothing depends on the name
resolving.

```yaml
# infra/ansible/inventory/hosts.yml
tailnet: your-name-here.ts.net
```

Then `make cluster` (to get the new name into the API server's TLS SANs)
and `make argocd`. Tailnet names are globally unique across all of
Tailscale, and Tailscale limits how often you can change one.

Any workload deployed later gets the same treatment by adding an Ingress
with `ingressClassName: tailscale` and its own name in `spec.tls[0].hosts`
— no further decisions, and the proxy pod inherits the `role=interactive`
placement from the operator's default ProxyClass.

### The ArgoCD CLI

The UI is plain HTTPS and needs nothing special. The `argocd` CLI talks
gRPC, which needs `--grpc-web` through this proxy:

```bash
argocd login argocd.tail02e471.ts.net --grpc-web
```

## Decisions

- [0001 — Embedded etcd, 3 servers, quorum 2](docs/decisions/0001-etcd-topology.md)
- [0002 — Secrets: SOPS + age for infra secrets](docs/decisions/0002-secrets-management.md)
- [0003 — GPU scheduling on squadron](docs/decisions/0003-gpu-scheduling.md)
- [0004 — Workload placement](docs/decisions/0004-workload-placement.md)
- [0005 — ArgoCD bootstrapped by Ansible, published by the Tailscale operator](docs/decisions/0005-argocd-bootstrap-and-access.md)
- [0006 — Cluster secrets: Sealed Secrets, key backed up with SOPS](docs/decisions/0006-cluster-secrets.md)
- [0007 — SMS API on squadron, failing over to home](docs/decisions/0007-sms-api-placement-and-ha.md)
