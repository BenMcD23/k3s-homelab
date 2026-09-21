# Existing network. These resources describe what is already deployed and
# are adopted into state by the import blocks in imports.tf, never created.

resource "oci_core_vcn" "k8s" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = [var.vcn_cidr]
  display_name   = var.vcn_display_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "oci_core_subnet" "k8s" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.k8s.id
  cidr_block     = var.subnet_cidr
  display_name   = var.subnet_display_name

  security_list_ids = [oci_core_security_list.k8s.id]

  lifecycle {
    prevent_destroy = true
  }
}

# Mirrors the live rules as of adoption.
#
# Note the fourth ingress rule allows all TCP ports from 0.0.0.0/0. That is
# the live configuration, copied here rather than changed, since this config
# adopts existing infrastructure. Inbound traffic is actually restricted by
# the host's iptables ruleset in /etc/iptables/rules.v4 (see the ansible base
# role), which rejects everything except port 22. Tightening this rule is a
# separate change, see README.
resource "oci_core_security_list" "k8s" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.k8s.id
  display_name   = var.security_list_display_name

  egress_security_rules {
    destination      = "0.0.0.0/0"
    destination_type = "CIDR_BLOCK"
    protocol         = "all"
    stateless        = false
  }

  # SSH
  ingress_security_rules {
    source      = "0.0.0.0/0"
    source_type = "CIDR_BLOCK"
    protocol    = "6"
    stateless   = false

    tcp_options {
      min = 22
      max = 22
    }
  }

  # ICMP fragmentation-needed (path MTU discovery) - OCI default rule
  ingress_security_rules {
    source      = "0.0.0.0/0"
    source_type = "CIDR_BLOCK"
    protocol    = "1"
    stateless   = false

    icmp_options {
      type = 3
      code = 4
    }
  }

  # ICMP destination-unreachable within the VCN - OCI default rule
  ingress_security_rules {
    source      = var.vcn_cidr
    source_type = "CIDR_BLOCK"
    protocol    = "1"
    stateless   = false

    icmp_options {
      type = 3
    }
  }

  # All TCP, all ports, from anywhere. See the note above.
  ingress_security_rules {
    source      = "0.0.0.0/0"
    source_type = "CIDR_BLOCK"
    protocol    = "6"
    stateless   = false
  }

  # TCP 5000
  ingress_security_rules {
    source      = "0.0.0.0/0"
    source_type = "CIDR_BLOCK"
    protocol    = "6"
    stateless   = false

    tcp_options {
      min = 5000
      max = 5000
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}
