variable "region" {
  description = "OCI region the instance lives in"
  type        = string
  default     = "uk-london-1"
}

variable "tenancy_ocid" {
  description = "Tenancy OCID. Also the compartment OCID - this account uses the root compartment"
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment holding the instance. Same as tenancy_ocid on this account"
  type        = string
}

variable "instance_ocid" {
  description = "OCID of the EXISTING k8s-node instance. Used for the import block"
  type        = string
}

variable "vcn_ocid" {
  description = "OCID of the existing VCN"
  type        = string
}

variable "subnet_ocid" {
  description = "OCID of the existing subnet"
  type        = string
}

variable "security_list_ocid" {
  description = "OCID of the existing security list attached to the subnet"
  type        = string
}

variable "availability_domain" {
  description = "AD the instance runs in"
  type        = string
  default     = "vOEW:UK-LONDON-1-AD-1"
}

variable "instance_display_name" {
  description = "Display name of the existing instance, must match exactly"
  type        = string
  default     = "k8s node"
}

variable "instance_ocpus" {
  description = "OCPUs allocated to the A1.Flex instance"
  type        = number
  default     = 1
}

variable "instance_memory_gbs" {
  description = "Memory in GB allocated to the A1.Flex instance"
  type        = number
  default     = 6
}

variable "boot_image_ocid" {
  description = <<-EOT
    OCID of the image the instance was created from. Required by the
    provider schema, but ignored via lifecycle.ignore_changes since this
    config adopts an existing instance rather than creating one.
    Fetch with:
      oci compute instance get --instance-id <instance-ocid> \
        --query 'data."source-details"'
  EOT
  type        = string
  default     = "TODO_IMAGE_OCID"
}

variable "vcn_cidr" {
  description = "CIDR block of the existing VCN. Verify with: oci network vcn get --vcn-id <ocid>"
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_cidr" {
  description = "CIDR block of the existing subnet. Verify with: oci network subnet get --subnet-id <ocid>"
  type        = string
  default     = "10.0.0.0/24"
}

variable "vcn_display_name" {
  description = "Display name of the existing VCN, must match exactly"
  type        = string
  default     = "vcn-k8s"
}

variable "subnet_display_name" {
  description = "Display name of the existing subnet, must match exactly"
  type        = string
  default     = "subnet-k8s"
}

variable "security_list_display_name" {
  description = "Display name of the existing security list, must match exactly"
  type        = string
  default     = "Default Security List for vcn-k8s"
}
