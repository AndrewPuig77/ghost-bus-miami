output "public_ip" {
  value = oci_core_instance.app.public_ip
}

output "ssh" {
  value = "ssh -i ~/.ssh/ghostbus ubuntu@${oci_core_instance.app.public_ip}"
}
