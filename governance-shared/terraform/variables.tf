# Input set for the governance-shared stack. The three provider-wiring inputs
# (aws_region, aws_profile, default_tags) are referenced by providers.tf; the
# kiro_allowed_actions input drives the shared Kiro guardrail SCP.

# --- Provider wiring (referenced by providers.tf) ---------------------------

variable "aws_region" {
  description = <<-EOT
    Region the governance-shared stack's aws provider targets. This stack is
    management-account only; the region matters for the provider/STS calls, not
    for the (global) Organizations SCPs.

    Leave empty (the default) to inherit AWS_REGION from the environment — mise
    sources it from the git-ignored .env file. Set a value here or via
    `-var`/tfvars only to pin it explicitly.
  EOT
  type        = string
  default     = ""
}

variable "aws_profile" {
  description = "AWS CLI/SDK profile to use (MUST be a management-account or delegated Org-admin profile — this stack creates Organizations SCPs). Empty string falls back to the default SDK credential chain / AWS_PROFILE env var."
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

# --- Kiro guardrail SCP ------------------------------------------------------

variable "kiro_allowed_actions" {
  description = <<-EOT
    Allowlist of IAM actions the shared Kiro guardrail SCP permits
    (deny-by-default). The default is a CONSERVATIVE STARTER permitting Kiro +
    IAM Identity Center sign-in plus read-only basics; it is a single
    org-standard allowlist tuned ONCE here in governance-shared and shared by
    every workshop (widen or narrow it here, not per workshop — see README).
  EOT
  type        = list(string)
  default = [
    "sso:*",
    "sso-directory:*",
    "identitystore:*",
    "signin:*",
    "sts:GetCallerIdentity",
    "codewhisperer:*",
    "q:*",
  ]
}
