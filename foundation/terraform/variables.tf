variable "aws_region" {
  description = <<-EOT
    Region to create the IAM Identity Center account instance in. Must be a
    region Kiro supports for IdC.

    Leave empty (the default) to inherit AWS_REGION from the environment — mise
    sources it from the git-ignored .env file, so change the region there
    (`cp .env.example .env`) rather than editing committed files. Set a value
    here or via `-var`/tfvars only to pin it explicitly.
  EOT
  type        = string
  default     = ""
}

variable "aws_profile" {
  description = "AWS CLI/SDK profile to use. Empty string falls back to the default SDK credential chain / AWS_PROFILE env var."
  type        = string
  default     = ""
}

variable "default_tags" {
  description = "Tags applied to every taggable resource, including the IdC instance (via the AWSCC list-of-objects tag shape)."
  type        = map(string)
  default = {
    Project   = "kiro-subscriptions"
    ManagedBy = "opentofu"
    Purpose   = "kiro-login-only"
    # Shared infra, not attributable per workshop; keeps the cost-allocation tag
    # key present on every line item so there are no untagged items.
    workshop_id = "shared"
  }
}

variable "instance_name" {
  description = <<-EOT
    Optional name applied to the IdC account instance (helps identify it in the
    console). Supply via tfvars or TF_VAR_instance_name to override. Defaults to
    "kiro-login" when not supplied.
  EOT
  type        = string
  default     = "kiro-login"
}
