# =============================================================================
# Input variables for the Credential Claim Service stack
# =============================================================================
#
# These inputs parameterize the single table, the Lambda, and its abuse gate.
# `workshop_id` is the namespace: every claim resource name derives from
# `local.name = credential-claim-<workshop_id>` (dynamodb.tf / lambda.tf), so
# the table name is no longer a direct input. `workshop_code`, `allowed_origin`,
# `retry_bound`, and `per_ip_cap` are wired into the Lambda's TABLE_NAME /
# WORKSHOP_CODE / ALLOWED_ORIGIN / RETRY_BOUND / PER_IP_CAP environment
# variables in lambda.tf (design: "Lambda packaging and configuration"). The
# handler reads each with a sensible fallback, so only `workshop_id` and
# `workshop_code` are strictly required at apply time.
#
# `workshop_id` (the namespace) and `workshop_code` (the handler access-gate
# secret) are deliberately distinct values: `workshop_id` is never used for
# access-gate validation, and `workshop_code` is never used in a resource name
# or state key (design: "workshop_id vs workshop_code coexist", R9.3/R9.4).
# =============================================================================

variable "aws_region" {
  description = <<-EOT
    Deployment region for the table, Lambda, and Function URL. Leave empty
    (default) to inherit AWS_REGION from the environment (mise sources it from
    the git-ignored .env; it defaults to us-east-1 there). Set a value only to
    pin. The region is never hardcoded in the provider — it comes from the env.
  EOT
  type        = string
  default     = ""
}

variable "aws_profile" {
  description = "AWS CLI/SDK profile (MUST be a management-account profile). Empty falls back to the AWS_PROFILE env / default chain."
  type        = string
  default     = ""
}

variable "default_tags" {
  description = "Tags applied to every taggable resource via the aws provider default_tags block."
  type        = map(string)
  default = {
    Project   = "kiro-provisioning-iac"
    Service   = "claim-service"
    ManagedBy = "opentofu"
  }
}

variable "workshop_id" {
  description = <<-EOT
    Slug that namespaces this workshop's claim resources and state key, e.g.
    kiro-2025-10-10. Threaded from WORKSHOP_ID via TF_VAR_workshop_id. Every
    claim resource name derives from it through
    local.name = "credential-claim-$${workshop_id}". Distinct from
    workshop_code (the claim access-gate secret) — the namespace is never the
    access gate.
  EOT
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", var.workshop_id)) && !can(regex("--", var.workshop_id))
    error_message = "workshop_id must be a slug: 1-63 lowercase alphanumeric characters and hyphens, starting and ending alphanumeric, with no consecutive hyphens."
  }
}

variable "workshop_code" {
  description = <<-EOT
    Shared gate secret participants must submit with a claim (Requirement 12.1).
    Required — there is deliberately no default, so an operator must supply the
    code for the specific workshop. Marked sensitive so it is not shown in CLI
    output or logs.
  EOT
  type        = string
  sensitive   = true
}

variable "allowed_origin" {
  description = <<-EOT
    Origin allowed by the Function URL's CORS policy and echoed to the claim
    page (Requirement 12.3). The Function URL's own origin is only known after
    apply, so this defaults to empty: an empty value means "do not pin a
    specific cross-origin" and the browser form submission remains same-origin
    (the page and endpoint share the one Function URL origin). Set it to the
    computed function_url origin on a second apply if a hard CORS pin is wanted.
  EOT
  type        = string
  default     = ""
}

variable "retry_bound" {
  description = "Max pick-and-claim retries after a lost credential race before reporting exhaustion (Requirements 2.4, 5.1). Matches the handler's RETRY_BOUND fallback."
  type        = number
  default     = 5
}

variable "per_ip_cap" {
  description = "Max POST attempts allowed from a single source IP before the per-IP cap trips 429 (Requirement 12.2). Matches the handler's PER_IP_CAP fallback."
  type        = number
  default     = 20
}
