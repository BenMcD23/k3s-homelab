# The Oracle Cloud A1.Flex instance. Ampere capacity is scarce in this
# region, so a destroyed instance may not be recreatable, hence
# prevent_destroy below.

resource "oci_core_instance" "k8s_node" {
  compartment_id      = var.compartment_ocid
  availability_domain = var.availability_domain
  display_name        = var.instance_display_name
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_gbs
  }

  source_details {
    source_type = "image"
    source_id   = var.boot_image_ocid
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.k8s.id
    assign_public_ip = true
  }

  lifecycle {
    prevent_destroy = true

    # The instance already exists and is configured by Ansible. These
    # attributes are set on the live instance and are not managed here:
    #   source_details - the boot image OCID, unknown until fetched, and
    #                    changing it would force replacement
    #   metadata       - holds the cloud-init SSH keys, managed by Ansible
    ignore_changes = [
      source_details,
      metadata,
    ]
  }
}
