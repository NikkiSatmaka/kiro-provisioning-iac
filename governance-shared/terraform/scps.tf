# scps.tf — the shared Service Control Policy OBJECTS.
#
# Both SCP policy objects are management-account SINGLETONS, defined ONCE here in
# governance-shared/ (they were previously in foundation/, but foundation is now
# dual-mode and account-safe, and Organizations SCPs cannot be created in a
# child account). They are consumed by every workshop's governance/ stack (by
# id, via var.kiro_guardrail_scp_id / var.freeze_scp_id, wired forward as
# TF_VAR_* — see governance-shared/RUNBOOK.md). Per-workshop governance/ cannot
# own them because their names are unsuffixed and would collide across
# workshops. This stack creates the policy OBJECTS only; it attaches neither:
#   - Kiro guardrail: a deny-by-default allowlist. governance/ ATTACHES it to
#     each workshop OU, so every account in that OU is bounded to the
#     Kiro-relevant actions.
#   - Freeze: a deny-all policy, CREATED BUT LEFT UNATTACHED. AWS Budgets
#     attaches it to a single breaching account automatically on budget breach
#     (the per-account budget actions live in governance/).

# --- Kiro guardrail: deny-by-default allowlist (policy object only) ----------
data "aws_iam_policy_document" "kiro_guardrail" {
  # Allowlist semantics for an SCP: a single Allow of the permitted actions.
  # Everything not listed is implicitly denied by the SCP boundary.
  statement {
    sid       = "KiroAllowlist"
    effect    = "Allow"
    actions   = var.kiro_allowed_actions
    resources = ["*"]
  }
}

resource "aws_organizations_policy" "kiro_guardrail" {
  name        = "kiro-guardrail"
  description = "Shared org-standard Kiro-only allowlist attached to each workshop OU."
  type        = "SERVICE_CONTROL_POLICY"
  content     = data.aws_iam_policy_document.kiro_guardrail.json
}

# --- Freeze: deny-all (policy object only; attachment is automatic) ----------
data "aws_iam_policy_document" "freeze" {
  statement {
    sid       = "DenyAll"
    effect    = "Deny"
    actions   = ["*"]
    resources = ["*"]
  }
}

resource "aws_organizations_policy" "freeze" {
  name        = "freeze"
  description = "Deny-all freeze; attached to a single account automatically on budget breach."
  type        = "SERVICE_CONTROL_POLICY"
  content     = data.aws_iam_policy_document.freeze.json
}
