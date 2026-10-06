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

# --- Shared primitives from foundation/ (wired forward as variables) --------
# These three are once-per-management-account singletons owned by foundation/
# and consumed here by id/ARN. No defaults: a missing wire-forward fails closed.

variable "budgets_execution_role_arn" {
  description = "From foundation/: ARN of the shared least-privilege role AWS Budgets assumes to attach/detach the freeze SCP."
  type        = string
}

variable "kiro_guardrail_scp_id" {
  description = "From foundation/: id of the shared Kiro guardrail SCP this stack attaches to the workshop OU."
  type        = string
}

variable "freeze_scp_id" {
  description = "From foundation/: id of the shared deny-all freeze SCP AWS Budgets attaches to a breaching account on breach."
  type        = string
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
    account (or a delegated Org-admin) — the same management-account profile
    every stack in this repo now uses; its SCPs/budgets still TARGET the member
    accounts. Empty string falls back to the default SDK credential chain /
    AWS_PROFILE env var.
  EOT
  type        = string
  default     = ""
}

variable "default_tags" {
  description = "Tags applied to every taggable resource via the aws provider default_tags block."
  type        = map(string)
  default = {
    Project   = "kiro-provisioning-iac"
    ManagedBy = "opentofu"
    Purpose   = "workshop-account-governance"
  }
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
