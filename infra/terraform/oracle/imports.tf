# Adopt the existing infrastructure into state. Run once:
#
#   terraform plan     # must show "4 to import, 0 to add, 0 to change, 0 to destroy"
#   terraform apply
#
# After the first successful apply, these blocks are inert and can be
# deleted. They are kept here as documentation of how state was built.
#
# If plan shows changes rather than a clean import, a variable in
# terraform.tfvars does not match reality - fix the variable, never
# let terraform "correct" the live infrastructure.

import {
  to = oci_core_vcn.k8s
  id = var.vcn_ocid
}

import {
  to = oci_core_subnet.k8s
  id = var.subnet_ocid
}

import {
  to = oci_core_security_list.k8s
  id = var.security_list_ocid
}

import {
  to = oci_core_instance.k8s_node
  id = var.instance_ocid
}
