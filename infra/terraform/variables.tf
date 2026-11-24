# Oracle API credentials (Profile -> My profile -> API keys -> Add API key).
variable "tenancy_ocid" {
  type = string
}

variable "user_ocid" {
  type = string
}

variable "fingerprint" {
  type = string
}

variable "private_key_path" {
  description = "Path to the API signing key (.pem) downloaded from the Oracle console"
  type        = string
}

variable "region" {
  description = "Your home region, e.g. us-ashburn-1. Always Free resources exist only there."
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment for all resources. Leave empty to use the tenancy's root compartment."
  type        = string
  default     = ""
}

variable "ssh_public_key_path" {
  description = "Public key allowed to SSH into the server"
  type        = string
  default     = "~/.ssh/ghostbus.pub"
}

variable "ssh_allowed_cidr" {
  description = "Who may reach SSH. GitHub Actions deploys over SSH from changing IPs, so this is open by default; key-only login is enforced on the server."
  type        = string
  default     = "0.0.0.0/0"
}

# Ampere A1 (ARM). Oracle reportedly cut the Always Free allowance to 2 OCPUs / 12 GB in 2026;
# check Governance -> Limits in your console before raising these.
variable "availability_domain" {
  description = "Index of the availability domain (0, 1 or 2). Try another if apply fails with \"Out of host capacity\"."
  type        = number
  default     = 0
}

variable "ocpus" {
  type    = number
  default = 2
}

variable "memory_gbs" {
  type    = number
  default = 12
}

variable "boot_volume_gbs" {
  description = "Disk size. Always Free includes 200 GB of block storage in total."
  type        = number
  default     = 100
}

variable "budget_alert_email" {
  description = "Email for the cost alert. Leave empty to skip creating the budget."
  type        = string
  default     = ""
}
