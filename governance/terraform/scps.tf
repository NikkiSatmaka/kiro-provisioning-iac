# scps.tf — Service Control Policies for the workshop OU.
#
# Two SCPs, with deliberately asymmetric attachment:
#   - Kiro guardrail: a deny-by-default allowlist, ATTACHED to the workshop OU
#     so every account in the OU is bounded to the Kiro-relevant actions.
#   - Freeze: a deny-all policy, CREATED BUT LEFT UNATTACHED. AWS Budgets
#     attaches it to a single breaching account automatically on budget breach
#     (see budgets.tf); this stack declares NO attachment resource for it.

# --- Kiro guardrail: deny-by-default allowlist, attached to the OU ----------
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
  name        = "kiro-guardrail-${var.workshop_id}"
  description = "Kiro-only allowlist for workshop ${var.workshop_id}."
  type        = "SERVICE_CONTROL_POLICY"
  content     = data.aws_iam_policy_document.kiro_guardrail.json
}

resource "aws_organizations_policy_attachment" "kiro_guardrail" {
  policy_id = aws_organizations_policy.kiro_guardrail.id
  target_id = aws_organizations_organizational_unit.workshop.id
}

# --- Freeze: deny-all, CREATED BUT NOT ATTACHED (no attachment resource) ----
data "aws_iam_policy_document" "freeze" {
  statement {
    sid       = "DenyAll"
    effect    = "Deny"
    actions   = ["*"]
    resources = ["*"]
  }
}

resource "aws_organizations_policy" "freeze" {
  name        = "freeze-${var.workshop_id}"
  description = "Deny-all freeze; attached to a single account automatically on budget breach."
  type        = "SERVICE_CONTROL_POLICY"
  content     = data.aws_iam_policy_document.freeze.json
}

# INTENTIONALLY no aws_organizations_policy_attachment for the freeze policy.
# The freeze SCP must exist but stay UNATTACHED at apply time (Requirement 5.3);
# AWS Budgets attaches it to the single breaching account on budget breach.
