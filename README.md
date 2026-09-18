# k3s HA cluster

Three-node k3s cluster with embedded etcd, meshed over Tailscale.
Infrastructure as code: Terraform for the Oracle Cloud node, Ansible for
host configuration, ArgoCD (later) for workloads.

**Current state: scaffolding.** No k3s is installed by anything in this
repo yet. The Ansible `base` role prepares hosts; cluster bring-up is the
next piece of work.

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
infra/ansible/            Inventory + base role (users, SSH, swap, sysctls, chrony, Tailscale)
docs/decisions/           ADRs
clusters/prod/            Placeholder for ArgoCD app-of-apps
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
# fill in the Tailscale auth key, then:
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
make apply       # run the base role against all three nodes
```

The `base` role is idempotent and safe to re-run. It covers: SSH key +
passwordless sudo, SSH hardening, unattended-upgrades, swap off
(persistently), k8s sysctls and kernel modules, chrony (replacing
systemd-timesyncd), and Tailscale install + enrolment.

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

`harden_ssh: true` (default) disables root login and password auth.
Confirm key auth works before running this against a machine you cannot
easily get to in person, squadron especially. Otherwise run with
`-e harden_ssh=false` and turn it on once you are sure.

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
ansible-playbook site.yml --limit home -e ansible_host=192.168.1.x
```

Set the machine's hostname to match the inventory (`home-server`,
`317server`, `k8s-node`) — MagicDNS names derive from it.

**3. Run the base role.**

```bash
ansible-playbook site.yml --limit <alias>
```

**4. Rejoin the cluster.** For a replaced node, remove the old etcd member
before the new one joins, or etcd will count a member that's never coming
back toward quorum:

```bash
kubectl delete node <name>            # from a surviving node
k3s server --server https://<home-tailnet-ip>:6443 --token <token>
```

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

## Decisions

- [0001 — Embedded etcd, 3 servers, quorum 2](docs/decisions/0001-etcd-topology.md)
- [0002 — Secrets: SOPS + age for infra secrets; in-cluster secrets undecided](docs/decisions/0002-secrets-management.md)
- [0003 — GPU scheduling on squadron](docs/decisions/0003-gpu-scheduling.md)
- [0004 — Workload placement](docs/decisions/0004-workload-placement.md)
