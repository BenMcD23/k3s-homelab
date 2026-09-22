# k3s cluster infrastructure

TF_DIR := infra/terraform/oracle
ANSIBLE_DIR := infra/ansible

.PHONY: help deps fmt lint validate plan apply base cluster argocd etcd-health

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

deps: ## Install Ansible collections
	cd $(ANSIBLE_DIR) && ansible-galaxy collection install -r requirements.yml

fmt: ## Format terraform files
	cd $(TF_DIR) && terraform fmt -recursive

lint: ## Lint ansible
	cd $(ANSIBLE_DIR) && ansible-lint

validate: ## Validate terraform config and ansible syntax
	cd $(TF_DIR) && terraform fmt -check -recursive
	cd $(TF_DIR) && terraform init -backend=false && terraform validate
	cd $(ANSIBLE_DIR) && ansible-playbook site.yml --syntax-check

plan: ## Terraform plan - adopts existing OCI infra on first run
	cd $(TF_DIR) && terraform plan

apply: ## Run the whole playbook - base role, k3s bring-up, then Argo CD
	cd $(ANSIBLE_DIR) && ansible-playbook site.yml

base: ## Host prep only, no k3s
	cd $(ANSIBLE_DIR) && ansible-playbook site.yml --tags base

cluster: ## k3s bring-up only - the base role must have run first
	cd $(ANSIBLE_DIR) && ansible-playbook site.yml --tags k3s

argocd: ## Argo CD bootstrap only - the cluster must be up first
	cd $(ANSIBLE_DIR) && ansible-playbook site.yml --tags argocd

etcd-health: ## etcd fsync latency and leader stability on every server
	@scripts/etcd-health.sh
