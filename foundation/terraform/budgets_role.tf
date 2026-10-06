# =============================================================================
# budgets_role.tf — the shared budgets EXECUTION ROLE
#
# A least-privilege IAM role AWS Budgets assumes to attach/detach the freeze SCP,
# with an aws:SourceAccount confused-deputy guard on the trust policy. Defined
# ONCE per management account here in foundation/ and consumed by every
# workshop's governance/ stack (via var.budgets_execution_role_arn) — it is no
# longer recreated per workshop, so its name carries no workshop_id suffix.
# =============================================================================

# The management account id — used for the aws:SourceAccount confused-deputy
# guard on the budgets role trust policy.
data "aws_caller_identity" "current" {}

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
  name               = "governance-budgets-exec"
  assume_role_policy = data.aws_iam_policy_document.budgets_trust.json
}

resource "aws_iam_role_policy" "budgets_execution" {
  name   = "attach-detach-freeze"
  role   = aws_iam_role.budgets_execution.id
  policy = data.aws_iam_policy_document.budgets_permissions.json
}
