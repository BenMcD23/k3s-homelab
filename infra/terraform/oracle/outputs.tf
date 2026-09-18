output "instance_id" {
  description = "OCID of the adopted instance"
  value       = oci_core_instance.k8s_node.id
}

output "instance_public_ip" {
  description = "Public IP of the instance. Note: k3s uses the Tailscale IP, not this"
  value       = oci_core_instance.k8s_node.public_ip
}

output "instance_private_ip" {
  description = "VCN-private IP of the instance"
  value       = oci_core_instance.k8s_node.private_ip
}

output "subnet_id" {
  description = "OCID of the adopted subnet"
  value       = oci_core_subnet.k8s.id
}
