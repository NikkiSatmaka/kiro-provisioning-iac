# =============================================================================
# Input variables for the Credential Claim Service stack
# =============================================================================
#
# These five inputs parameterize the single table, the Lambda, and its abuse
# gate. Names line up with what the rest of the stack and the handler expect:
# `table_name` feeds dynamodb.tf (`var.table_name`), and `workshop_code`,
# `allowed_origin`, `retry_bound`, and `per_ip_cap` are wired into the Lambda's
# TABLE_NAME / WORKSHOP_CODE / ALLOWED_ORIGIN / RETRY_BOUND / PER_IP_CAP
# environment variables in lambda.tf (design: "Lambda packaging and
# configuration"). The handler reads each with a sensible fallback, so only
# `workshop_code` is strictly required at apply time.
# =============================================================================

variable "table_name" {
  description = "Name of the single DynamoDB table backing the service (CRED#/EMAIL#/RATE# items share it)."
  type        = string
  default     = "credential-claim-service"
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
