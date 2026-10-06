variable "aws_region" {
  description = <<-EOT
    Region for the state bucket + lock table. Keep it the SAME as the main
    config's region. Leave empty (default) to inherit AWS_REGION from the
    environment (mise sources it from the git-ignored .env); set a value only to pin.
  EOT
  type        = string
  default     = ""
}

variable "aws_profile" {
  description = "AWS profile. Empty string falls back to the default SDK credential chain / AWS_PROFILE env var."
  type        = string
  default     = ""
}

variable "state_bucket_name" {
  description = <<-EOT
    OPTIONAL override for the S3 state bucket name. Leave empty (default) to let
    the bootstrap derive a deterministic, globally-unique name from the account
    id: "kiro-tofu-state-<ACCOUNT_ID>". Set a value ONLY to override that — S3
    bucket names are shared across all AWS accounts, so an override must stay
    globally unique (3-63 chars). Example: "acme-kiro-tofu-state-123456789012".
  EOT
  type        = string
  default     = ""

  validation {
    # Only constrains the override path; the derived default (account id, 12
    # digits + prefix) is always within S3's 3-63 char limit.
    condition     = var.state_bucket_name == "" || (length(var.state_bucket_name) >= 3 && length(var.state_bucket_name) <= 63)
    error_message = "state_bucket_name override must be 3-63 characters (S3 bucket naming rules)."
  }
}

variable "lock_table_name" {
  description = "DynamoDB table name for state locking. Only needs to be unique within the account/region."
  type        = string
  default     = "kiro-tofu-locks"
}

variable "force_destroy" {
  description = <<-EOT
    If true, `tofu destroy` here will delete the state bucket even if it still
    holds objects (state versions). Keep FALSE normally so you cannot wipe your
    state by accident; set true only when you deliberately tear the backend down.
  EOT
  type        = bool
  default     = false
}

variable "default_tags" {
  description = "Tags applied to the bucket + lock table."
  type        = map(string)
  default = {
    Project   = "kiro-provisioning-iac"
    ManagedBy = "opentofu"
    Purpose   = "tofu-remote-state"
    # Shared infra, not attributable per workshop; keeps the cost-allocation tag
    # key present on every line item so there are no untagged items.
    workshop_id = "shared"
  }
}
