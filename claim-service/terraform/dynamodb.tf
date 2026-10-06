# =============================================================================
# DynamoDB — single-table model for the Credential Claim Service
# =============================================================================
#
# One on-demand table backs the whole service. Three item types share the table,
# distinguished by the `PK` prefix, so a single `TransactWriteItems` can enforce
# both uniqueness constraints (one-per-credential and one-per-email) atomically.
# This is the race-proof correctness core (Requirements 2.x, 8.x) — the schema
# here only has to carry the keys those conditional writes depend on.
#
# Capacity is PAY_PER_REQUEST (on-demand): no provisioned throughput to size or
# pay for, free-tier friendly at workshop scale (Requirement 9.2).
#
# -----------------------------------------------------------------------------
# Item shapes (all keyed by the single partition key `PK`, a String):
# -----------------------------------------------------------------------------
#
# Credential item — one per IdC user, seeded up front by seed_claim_pool.py:
#
#   PK               = "CRED#<username>"
#   username         = <string>
#   otp              = <string>
#   sign_in_url      = <string>
#   region           = <AWS_REGION, default "us-east-1">
#   status           = "available" | "claimed"
#   claimed_by_email = <normalized_email>   (absent until claimed)
#   claimed_at       = <iso8601>            (absent until claimed)
#
#   The claim transaction conditionally Updates this item with
#   `ConditionExpression: status = "available"` so a credential is handed out
#   at most once (Requirement 2.1 / 8.1).
#
# Email-lock item — written at claim time to enforce one-per-email:
#
#   PK          = "EMAIL#<normalized_email>"
#   username    = <the credential they got>
#   claimed_at  = <iso8601>
#
#   The claim transaction conditionally Puts this item with
#   `ConditionExpression: attribute_not_exists(PK)` so an email claims at most
#   once (Requirement 2.2 / 8.2). A conflict here drives the idempotent re-claim.
#
# Rate item — per-source-IP attempt counter for the abuse gate:
#
#   PK    = "RATE#<source_ip>"
#   count = <number>          (atomic ADD on each POST)
#   ttl   = <epoch seconds>   (DynamoDB TTL auto-expires the counter)
#
#   The `ttl` attribute below drives TimeToLive expiry so these counters clean
#   themselves up without a separate store (Requirement 12.2).
#
# Only `PK` is a key attribute, so it is the only attribute declared below —
# DynamoDB is schemaless for everything else, and `ttl`/`status`/etc. are plain
# item attributes written by the handler and scripts, not part of the table
# schema.
# =============================================================================

# -----------------------------------------------------------------------------
# The one namespaced base name every claim resource derives from. Threaded from
# var.workshop_id so two workshops never share a table, Lambda, Function URL,
# role, or policy (design: "One claim service per workshop", R7.3/R9.3).
# -----------------------------------------------------------------------------
locals {
  name = "credential-claim-${var.workshop_id}"
}

resource "aws_dynamodb_table" "claim" {
  name         = local.name
  billing_mode = "PAY_PER_REQUEST"

  # Single partition key; no sort key. Item type is encoded in the PK prefix
  # (CRED# / EMAIL# / RATE#), which is what lets one transaction span item types.
  hash_key = "PK"

  attribute {
    name = "PK"
    type = "S"
  }

  # Auto-expire RATE#<source_ip> counters once their `ttl` epoch passes, keeping
  # the per-IP gate self-cleaning. CRED# and EMAIL# items carry no `ttl`, so TTL
  # never touches them.
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Service   = "credential-claim-service"
    ManagedBy = "opentofu"
  }
}

# -----------------------------------------------------------------------------
# Table identity re-exported for the least-privilege IAM role (lambda.tf, task
# 9.1). Keeping the name and ARN in one local gives the role policy a single
# place to scope its five DynamoDB actions to exactly this table.
# -----------------------------------------------------------------------------
locals {
  claim_table_name = aws_dynamodb_table.claim.name
  claim_table_arn  = aws_dynamodb_table.claim.arn
}
