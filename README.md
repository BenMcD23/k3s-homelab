# k3s HA cluster

Three-node k3s cluster with embedded etcd, meshed over Tailscale.
Infrastructure as code: Terraform for the Oracle Cloud node, Ansible for
host configuration, ArgoCD for workloads.

**Current state: bring-up is written, not yet run.** The `base` role
prepares hosts, the `k3s_server` role stands up the three-server cluster,
and the `argocd` role bootstraps ArgoCD onto it. Neither the cluster nor
anything on it exists yet — running `make apply` against the real nodes is
the next step. Workloads (GPU scheduling, and anything under
`clusters/prod/`) come after.

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
  roles/argocd/             ArgoCD bootstrap, published over Tailscale
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

# Two keys to fill in: the Tailscale auth key, and the k3s cluster token.
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
make argocd      # ArgoCD bootstrap only
make apply       # everything: base role, the cluster, then ArgoCD
```

`site.yml` is four plays: the `base` role across all nodes, then the
first k3s server, then the rest joining it one at a time, then ArgoCD on
the first server. The split is what enforces bring-up order — see below.

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
make argocd         # or: ansible-playbook site.yml --tags argocd
```

Ansible installs ArgoCD and nothing else. ArgoCD installs everything after
it ([ADR 0005](docs/decisions/0005-argocd-bootstrap-and-access.md)) — the
role creates exactly one Application, an app-of-apps root pointing at
`clusters/prod/`, and from then on adding a workload is a commit rather
than a playbook run.

Like `--cluster-init`, this runs on whichever node is in `k3s_first_server`
rather than from a flag, so the cluster-wide manifests are applied from one
place. The upstream `install.yaml` is pinned by version *and* sha256 in
`roles/argocd/defaults/main.yml`; upgrading means bumping both and
re-running:

```bash
curl -sL https://raw.githubusercontent.com/argoproj/argo-cd/vX.Y.Z/manifests/install.yaml | sha256sum
```

Only two things deviate from upstream: a `role=interactive` nodeSelector on
every ArgoCD workload, so the UI lands on home rather than wherever the
scheduler has room ([ADR
0004](docs/decisions/0004-workload-placement.md)), and a NodePort on
`argocd-server` when the UI is published. Staying close to upstream is what
keeps upgrades to one line.

### Getting in

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo
```

Username `admin`. Change it in the UI and delete that Secret afterwards —
it is not rotated and not needed once you have.

### External access

The UI is published by **Tailscale**, not by an ingress. `tailscale serve`
on home terminates a real Let's Encrypt certificate for the node's MagicDNS
name and proxies to ArgoCD:

```
https://home-server.tail02e471.ts.net
```

That is reachable from any device logged into the tailnet — your laptop on
someone else's WiFi, your phone, anywhere. It is *not* limited to the home
LAN, which is usually what "external access" is actually after. Nothing is
forwarded on the router, there is no DNS record to own and no certificate
to renew.

`argocd_expose` picks how far it goes:

| Value | Reachable from |
|-------|----------------|
| `cluster` | nowhere; `kubectl port-forward` only |
| `tailnet` (default) | any device on the tailnet |
| `funnel` | the open internet |

It is reversible — setting it back and re-running withdraws the handler
rather than leaving it up.

**On `funnel`:** it works, and it is one variable. It is not the default on
purpose. ArgoCD's admin account can schedule a pod in any namespace, so it
is cluster-admin by another name, and `funnel` puts its login page
somewhere scanners find within hours — with no SSO, no MFA and no rate
limiting in front of it. The honest version is that `tailnet` already
covers "I want to reach it when I'm out"; `funnel` only adds access from a
device that isn't yours. If you do want it, wire up OIDC on the admin
account first. The reasoning is in ADR 0005.

Two things have to be turned on in the [Tailscale admin
console](https://login.tailscale.com/admin/dns) and cannot be done from
Ansible:

- **HTTPS certificates** for the tailnet — required for `tailnet` and
  `funnel` both.
- **The `funnel` node attribute** in the ACL policy — required for
  `funnel` only.

Without them the `tailscale serve` task fails with Tailscale's own message
saying which one is missing.

One caveat worth knowing: the `argocd-server` NodePorts (30080/30443) bind
every interface on every node, not just home's `tailscale0`. On oracle the
host firewall rejects them. On home and squadron they are reachable from
those LANs, still behind an ArgoCD login. Narrowing that needs a
cluster-wide kube-proxy setting, which is not worth it here.

## Decisions

- [0001 — Embedded etcd, 3 servers, quorum 2](docs/decisions/0001-etcd-topology.md)
- [0002 — Secrets: SOPS + age for infra secrets; in-cluster secrets undecided](docs/decisions/0002-secrets-management.md)
- [0003 — GPU scheduling on squadron](docs/decisions/0003-gpu-scheduling.md)
- [0004 — Workload placement](docs/decisions/0004-workload-placement.md)
- [0005 — ArgoCD bootstrapped by Ansible, published over Tailscale](docs/decisions/0005-argocd-bootstrap-and-access.md)
