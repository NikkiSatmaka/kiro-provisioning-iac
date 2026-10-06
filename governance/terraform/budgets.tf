# =============================================================================
# budgets.tf — execution role, per-account budgets, and SCP freeze actions
#
# Task 5.1 (this file, below): the budgets EXECUTION ROLE only — a
# least-privilege IAM role AWS Budgets assumes to attach/detach the freeze SCP,
# with an aws:SourceAccount confused-deputy guard on the trust policy.
#
# Tasks 5.2 (per-account budgets) and 5.3 (per-account AUTOMATIC SCP freeze
# actions) APPEND to this file below the execution-role section. Keep the
# execution-role resources above that boundary; add later resources beneath it.
# =============================================================================

# --- Budgets execution role (least privilege + confused-deputy guard) --------
# AWS Budgets assumes this role to attach the freeze SCP to a breaching account.
# The trust policy only permits budgets.amazonaws.com when the request's
# aws:SourceAccount equals THIS management account (Requirement 6.1, 6.2) — the
# confused-deputy guard that stops another account's Budgets service from
# borrowing this role.
data "aws_iam_policy_document" "budgets_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id] # Requirement 6.2
    }
  }
}

# Permissions scoped to the Organizations attach/detach of the freeze SCP plus
# the minimal reads the service needs to resolve the policy and its targets.
# No org-wide admin (Requirement 6.3, 6.4).
data "aws_iam_policy_document" "budgets_permissions" {
  statement {
    sid    = "AttachDetachFreezeSCP"
    effect = "Allow"
    actions = [
      "organizations:AttachPolicy",
      "organizations:DetachPolicy",
      # Minimal reads Budgets needs to resolve the policy/targets:
      "organizations:ListPolicies",
      "organizations:DescribePolicy",
      "organizations:ListTargetsForPolicy",
    ]
    resources = ["*"] # scoped by the action set above; no org-wide admin (Requirement 6.4)
  }
}

resource "aws_iam_role" "budgets_execution" {
  name               = "governance-budgets-exec-${var.workshop_id}"
  assume_role_policy = data.aws_iam_policy_document.budgets_trust.json
}

resource "aws_iam_role_policy" "budgets_execution" {
  name   = "attach-detach-freeze"
  role   = aws_iam_role.budgets_execution.id
  policy = data.aws_iam_policy_document.budgets_permissions.json
}
# --- Per-account COST budgets (task 5.2) -------------------------------------
# One COST budget per supplied account, keyed by account id. Each budget is
# scoped to just that linked account via a cost_filter and carries the required
# notify-only recipients at the freeze threshold, plus an optional softer
# notify-only threshold when var.notify_threshold_percent is set.
#
# cost_filter / notification are block (set) forms in hashicorp/aws v6.67.0 —
# confirmed against the installed provider schema (the deprecated cost_filters
# map is NOT used).
resource "aws_budgets_budget" "account" {
  for_each = toset(var.account_ids)

  name         = "governance-${var.workshop_id}-${each.key}"
  budget_type  = "COST"
  limit_amount = var.budget_limit_amount
  limit_unit   = var.budget_limit_unit
  time_unit    = "MONTHLY"

  # Scope this budget to just this linked account (Requirement 7.1).
  cost_filter {
    name   = "LinkedAccount"
    values = [each.key]
  }

  # Required notify-only recipients at the freeze threshold (Requirement 8.3).
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.freeze_threshold_percent
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.notification_emails
  }

  # Optional softer notify-only threshold (Requirements 8.4, 8.5). When
  # var.notify_threshold_percent is null, no extra notification is created.
  dynamic "notification" {
    for_each = var.notify_threshold_percent != null ? [var.notify_threshold_percent] : []
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = var.notification_emails
    }
  }
}

# --- Per-account AUTOMATIC SCP freeze actions (task 5.3) ---------------------
# One AUTOMATIC budget action per supplied account, keyed by account id. On
# breach of the freeze threshold AWS Budgets assumes the execution role (5.1)
# and attaches the deny-all freeze SCP (scps.tf) to the SINGLE breaching
# account — never the OU — so one account's overrun never freezes the whole
# workshop (Requirement 7.4).
#
# Schema confirmed against the installed hashicorp/aws v6.67.0 provider:
#   - action_type is a required top-level attribute; the SCP enum value is
#     "APPLY_SCP_POLICY" (AWS Budgets ActionType: APPLY_IAM_POLICY |
#     APPLY_SCP_POLICY | RUN_SSM_DOCUMENTS).
#   - notification_type is ALSO required at the top level (ACTUAL | FORECASTED);
#     the design block omitted it — added here as "ACTUAL".
#   - definition is a required single block containing scp_action_definition
#     with policy_id (string) and target_ids (set(string)).
#   - subscriber is a set block (min 1, max 11); every notification email is
#     rendered via a dynamic "subscriber" block, not just the first.
resource "aws_budgets_budget_action" "freeze" {
  for_each = toset(var.account_ids)

  budget_name        = aws_budgets_budget.account[each.key].name
  action_type        = "APPLY_SCP_POLICY"                 # Requirements 7.2, 7.3
  notification_type  = "ACTUAL"                           # required by the provider schema
  approval_model     = "AUTOMATIC"                        # Requirement 7.2 (no human in the loop)
  execution_role_arn = aws_iam_role.budgets_execution.arn # Requirement 7.5

  # Fire at the freeze threshold, matching the budget's freeze-threshold
  # notification so the attach happens exactly when the breach notifies.
  action_threshold {
    action_threshold_type  = "PERCENTAGE"
    action_threshold_value = var.freeze_threshold_percent
  }

  # Attach the freeze SCP to THIS account only (Requirement 7.4) using the
  # least-privilege execution role (Requirement 7.5).
  definition {
    scp_action_definition {
      policy_id  = aws_organizations_policy.freeze.id
      target_ids = [each.key] # the breaching account, NEVER the OU
    }
  }

  # Subscribe every notification email (Requirement 7 notification path). The
  # subscriber block is a set; render one entry per address rather than only the
  # first element.
  dynamic "subscriber" {
    for_each = toset(var.notification_emails)
    content {
      subscription_type = "EMAIL"
      address           = subscriber.value
    }
  }
}
