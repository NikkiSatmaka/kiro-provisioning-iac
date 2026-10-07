variable "aws_region" {
  description = <<-EOT
    Region the IAM Identity Center instance this stack adopts lives in / is read
    from. Must match the region where IdC was enabled in the credentialed
    account — the ORGANIZATION instance in the management account, or the
    account instance in a child/member account.

    Leave empty (the default) to inherit AWS_REGION from the environment — mise
    sources it from the git-ignored .env file, so change the region there
    (`cp .env.example .env`) rather than editing committed files. Set a value
    here or via `-var`/tfvars only to pin it explicitly.
  EOT
  type        = string
  default     = ""
}

variable "aws_profile" {
  description = "AWS CLI/SDK profile to use. Use a management-account profile to adopt the organization instance, or a child/member account's profile to adopt that account's own IdC account instance. Empty string falls back to the default SDK credential chain / AWS_PROFILE env var."
  type        = string
  default     = ""
}

variable "default_tags" {
  description = "Tags applied to every taggable resource created by this stack via the aws provider default_tags."
  type        = map(string)
  default = {
    Project   = "kiro-provisioning-iac"
    ManagedBy = "opentofu"
    Purpose   = "kiro-login-only"
    # Shared infra, not attributable per workshop; keeps the cost-allocation tag
    # key present on every line item so there are no untagged items.
    workshop_id = "shared"
  }
}

# NOTE: kiro_allowed_actions moved to governance-shared/ along with the shared
# Kiro guardrail SCP. Foundation no longer creates any SCP, so it no longer
# needs that variable.
