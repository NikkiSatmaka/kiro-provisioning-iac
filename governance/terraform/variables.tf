# Full input set for the governance stack. The three provider-wiring inputs
# (aws_region, aws_profile, default_tags) are referenced by providers.tf; the
# rest drive the OU, SCPs, budgets, and freeze automation.

# --- Workshop identity ------------------------------------------------------

variable "workshop_id" {
  description = "Per-workshop slug; names the OU (workshop-<id>) and keys the state."
  type        = string
  validation {
    condition = (
      can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", var.workshop_id))
      && !can(regex("--", var.workshop_id))
    )
    error_message = "workshop_id must be 1-63 lowercase alphanumerics/hyphens, begin/end alphanumeric, no consecutive hyphens."
  }
}

variable "parent_id" {
  description = "Parent OU or org-root id the workshop OU hangs under."
  type        = string
}

variable "account_ids" {
  description = "Pre-existing, in-org 12-digit account ids to place in the workshop OU. The stack never CREATES accounts."
  type        = list(string)
  validation {
    # Fails naming the first offending value(s) (Requirement 1.3).
    condition     = alltrue([for a in var.account_ids : can(regex("^\\d{12}$", a))])
    error_message = "Every account id must be a 12-digit string. Offending values: ${join(", ", [for a in var.account_ids : a if !can(regex("^\\d{12}$", a))])}."
  }
}

# --- Provider wiring (referenced by providers.tf) ---------------------------

variable "aws_region" {
  description = <<-EOT
    Region the governance stack's aws provider targets.

    Leave empty (the default) to inherit AWS_REGION from the environment — mise
    sources it from the git-ignored .env file. Set a value here or via
    `-var`/tfvars only to pin it explicitly.
  EOT
  type        = string
  default     = ""
}

variable "aws_profile" {
  description = <<-EOT
    AWS CLI/SDK profile to use. This stack targets the Organizations MANAGEMENT
    account (or a delegated Org-admin), so this is distinct from the
    member-account profile the other stacks use. Empty string falls back to the
    default SDK credential chain / AWS_PROFILE env var.
  EOT
  type        = string
  default     = ""
}

variable "default_tags" {
  description = "Tags applied to every taggable resource via the aws provider default_tags block."
  type        = map(string)
  default = {
    Project   = "kiro-subscriptions"
    ManagedBy = "opentofu"
    Purpose   = "workshop-account-governance"
  }
}

# --- Kiro guardrail SCP ------------------------------------------------------

variable "kiro_allowed_actions" {
  description = <<-EOT
    Allowlist of IAM actions the Kiro guardrail SCP permits (deny-by-default).
    The default is a CONSERVATIVE STARTER permitting Kiro + IAM Identity Center
    sign-in plus read-only basics; it is a TUNABLE starting point — widen or
    narrow it per workshop (see README).
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

# --- Budgets and freeze automation ------------------------------------------

variable "freeze_threshold_percent" {
  description = "Percent of the budget limit at which the AUTOMATIC freeze SCP action fires (and the required notify-only notification is sent)."
  type        = number
  default     = 100
}

variable "notification_emails" {
  description = "REQUIRED budget-notification recipients (notify-only). No default; empty list fails validation."
  type        = list(string)
  validation {
    condition     = length(var.notification_emails) > 0
    error_message = "notification_emails must contain at least one address; a breach must never be silent."
  }
}

variable "notify_threshold_percent" {
  description = "Optional softer notify-only threshold (%). When null, no extra notify-only threshold is created."
  type        = number
  default     = null
}

variable "budget_limit_amount" {
  description = "Per-account COST budget limit amount."
  type        = number
}

variable "budget_limit_unit" {
  description = "Currency unit for the per-account budget limit."
  type        = string
  default     = "USD"
}
