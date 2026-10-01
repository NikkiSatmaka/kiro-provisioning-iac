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
    GLOBALLY-UNIQUE S3 bucket name for OpenTofu state. S3 bucket names are shared
    across all AWS accounts, so include something unique (account id, org name).
    Example: "acme-kiro-tofu-state-123456789012".
  EOT
  type        = string

  validation {
    condition     = length(var.state_bucket_name) >= 3 && length(var.state_bucket_name) <= 63
    error_message = "state_bucket_name must be 3-63 characters (S3 bucket naming rules)."
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
    Project   = "kiro-subscriptions"
    ManagedBy = "opentofu"
    Purpose   = "tofu-remote-state"
  }
}
