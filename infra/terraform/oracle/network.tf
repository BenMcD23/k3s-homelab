# Existing network. These resources DESCRIBE what is already deployed -
# they are adopted into state via the import blocks below, never created.

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

# Mirrors the live rules exactly as of adoption.
#
# NOTE: ingress rule 4 below allows ALL TCP ports from 0.0.0.0/0. That is
# the live configuration, reproduced here deliberately rather than quietly
# "fixed" - this config adopts reality, it does not reshape it. What
# actually restricts inbound traffic on this host is the OS-level iptables
# ruleset in /etc/iptables/rules.v4 (see the ansible base role), which
# rejects everything except port 22 regardless of what this list permits.
# Tightening this rule is a separate, deliberate change - see README.
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

  # All TCP, all ports, from anywhere. See NOTE above.
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
