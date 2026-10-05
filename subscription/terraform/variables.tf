# ---------------------------------------------------------------------------
# Provider / environment
# ---------------------------------------------------------------------------

variable "aws_region" {
  description = <<-EOT
    Region to create the IAM Identity Center account instance in. Must be a
    region Kiro supports for IdC.

    Leave empty (the default) to inherit AWS_REGION from the environment —
    mise sources it from the git-ignored .env file, so change the region there
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
  description = "Tags applied to every taggable resource."
  type        = map(string)
  default = {
    Project   = "kiro-subscriptions"
    ManagedBy = "opentofu"
    Purpose   = "kiro-login-only"
  }
}

# ---------------------------------------------------------------------------
# Foundation IdC (consumed, never created)
# ---------------------------------------------------------------------------

variable "idc_instance_arn" {
  description = <<-EOT
    ARN of the long-lived Foundation IdC instance to consume
    (arn:aws:sso:::instance/ssoins-xxxxxxxxxxxx). Supplied via tfvars or
    TF_VAR_idc_instance_arn. This module NEVER creates or destroys the instance.
  EOT
  type        = string

  validation {
    condition     = length(trimspace(var.idc_instance_arn)) > 0
    error_message = "idc_instance_arn is required (the Foundation IdC instance ARN). Set it in tfvars or via TF_VAR_idc_instance_arn."
  }
}

variable "identity_store_id" {
  description = <<-EOT
    Identity store ID backing the Foundation IdC instance (d-xxxxxxxxxx).
    Supplied via tfvars or TF_VAR_identity_store_id. Users, groups, and
    memberships are created against this identity store.
  EOT
  type        = string

  validation {
    condition     = length(trimspace(var.identity_store_id)) > 0
    error_message = "identity_store_id is required (the Foundation IdC identity store ID). Set it in tfvars or via TF_VAR_identity_store_id."
  }
}

# ---------------------------------------------------------------------------
# Workshop namespace + topology
# ---------------------------------------------------------------------------

variable "workshop_id" {
  description = <<-EOT
    Slug that namespaces this workshop's state key and resource names, e.g.
    kiro-2025-10-10. Threaded from WORKSHOP_ID via TF_VAR_workshop_id. Distinct
    from workshop_code (the claim access-gate secret).
  EOT
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", var.workshop_id)) && !can(regex("--", var.workshop_id))
    error_message = "workshop_id must be a slug: 1-63 lowercase alphanumeric characters and hyphens, starting and ending alphanumeric, with no consecutive hyphens."
  }
}

variable "workshop_accounts" {
  description = <<-EOT
    Explicit nested map describing this workshop's child accounts, the groups in
    each account, and the user count of each group. Keyed by 12-digit account id.
    Replaces the removed count/prefix/strategy generators.
  EOT
  type = map(object({
    groups = map(object({
      user_count = number
    }))
  }))

  validation {
    condition     = alltrue([for acct in keys(var.workshop_accounts) : can(regex("^[0-9]{12}$", acct))])
    error_message = "Every workshop_accounts key must be a 12-digit AWS account id."
  }

  validation {
    condition = alltrue(flatten([
      for acct, cfg in var.workshop_accounts : [
        for gname, g in cfg.groups : length(trimspace(gname)) > 0
      ]
    ]))
    error_message = "Every group name in workshop_accounts must be non-empty."
  }

  validation {
    condition = alltrue(flatten([
      for acct, cfg in var.workshop_accounts : [
        for gname, g in cfg.groups : g.user_count >= 0 && g.user_count <= 500
      ]
    ]))
    error_message = "Every group's user_count must be between 0 and 500 inclusive."
  }
}

# ---------------------------------------------------------------------------
# Kiro subscription tier (consumed by scripts, surfaced here for one source of truth)
# ---------------------------------------------------------------------------

variable "kiro_tier" {
  description = "Kiro subscription tier to assign to each group. One of PRO, PRO_PLUS, PRO_MAX, POWER. NOTE: tier assignment itself is a console/API step performed by scripts/, not by OpenTofu."
  type        = string
  default     = "PRO"

  validation {
    condition     = contains(["PRO", "PRO_PLUS", "PRO_MAX", "POWER"], var.kiro_tier)
    error_message = "kiro_tier must be one of: PRO, PRO_PLUS, PRO_MAX, POWER."
  }
}

# ---------------------------------------------------------------------------
# IdC region (sign-in instruction only)
# ---------------------------------------------------------------------------

variable "kiro_region" {
  description = <<-EOT
    Region a participant enters when signing in to Kiro. Kiro supports only
    us-east-1 today. Inherited from KIRO_REGION in the environment via
    TF_VAR_kiro_region (the provisioning task exports it). This value is used
    ONLY for the Kiro sign-in instruction in credentials.md; it never changes
    where AWS resources are created (that is AWS_REGION / IDC_REGION).
  EOT
  type        = string
  default     = "us-east-1"
}
