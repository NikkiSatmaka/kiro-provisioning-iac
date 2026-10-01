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

variable "instance_name" {
  description = "Name for the IAM Identity Center account instance (shown in the console)."
  type        = string
  default     = "kiro-login"
}

# ---------------------------------------------------------------------------
# Naming: prefix + zero-padded sequence
# ---------------------------------------------------------------------------

variable "user_prefix" {
  description = "Prefix for IdC usernames. Final name = <user_prefix><NN> where NN is a zero-padded sequence."
  type        = string
  default     = "kiro-user-"
}

variable "group_prefix" {
  description = "Prefix for IdC group names. Final name = <group_prefix><NN>."
  type        = string
  default     = "kiro-team-"
}

variable "sequence_padding" {
  description = "How many digits to zero-pad the sequence to. 2 => 01, 02, ... ; 3 => 001, 002, ..."
  type        = number
  default     = 2

  validation {
    condition     = var.sequence_padding >= 1 && var.sequence_padding <= 6
    error_message = "sequence_padding must be between 1 and 6."
  }
}

variable "sequence_start" {
  description = "First sequence number (inclusive). Usually 1."
  type        = number
  default     = 1
}

# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------

variable "user_count" {
  description = "How many IdC users to create."
  type        = number
  default     = 1

  validation {
    condition     = var.user_count >= 0 && var.user_count <= 500
    error_message = "user_count must be between 0 and 500."
  }
}

variable "group_count" {
  description = "How many IdC groups to create."
  type        = number
  default     = 1

  validation {
    condition     = var.group_count >= 0 && var.group_count <= 100
    error_message = "group_count must be between 0 and 100."
  }
}

# ---------------------------------------------------------------------------
# User attributes
# ---------------------------------------------------------------------------

variable "email_domain" {
  description = <<-EOT
    Domain used to synthesize each user's email, e.g. "example.com" produces
    kiro-user-01@example.com. IdC requires an email per user. If you intend to
    use the console "send email" password flow these must be REAL, reachable
    inboxes; for the one-time-password (OTP) flow they can be placeholders.
  EOT
  type        = string
  default     = "example.invalid"
}

variable "display_name_template" {
  description = "Template for a user's display name. {seq} is replaced by the padded sequence, {name} by the full username."
  type        = string
  default     = "Kiro User {seq}"
}

# ---------------------------------------------------------------------------
# Membership strategy: how users map into groups
# ---------------------------------------------------------------------------

variable "membership_strategy" {
  description = <<-EOT
    How to assign users to groups:
      "all_in_first" - every user joins the first group (group_count can be 1).
      "round_robin"  - users are spread evenly across all groups.
      "none"         - create users and groups but no memberships.
    Kiro subscriptions are assigned per GROUP, so every user that needs Kiro
    must belong to at least one subscribed group. "all_in_first" is the simplest
    setup for a single-tier team.
  EOT
  type        = string
  default     = "all_in_first"

  validation {
    condition     = contains(["all_in_first", "round_robin", "none"], var.membership_strategy)
    error_message = "membership_strategy must be one of: all_in_first, round_robin, none."
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
