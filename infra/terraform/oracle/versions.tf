terraform {
  required_version = ">= 1.6.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 9.2.0"
    }
  }
}

provider "oci" {
  region = var.region
  # Auth comes from ~/.oci/config (DEFAULT profile) or standard OCI_*
  # environment variables. No credentials in this repo.
}
