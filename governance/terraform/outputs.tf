# =============================================================================
# outputs.tf — operator-facing identifiers for the governance stack
#
# These surface the pieces an operator needs to verify the applied plan shape
# and to drive the manual un-freeze path documented in the RUNBOOK: the OU, the
# two SCPs, the budgets execution role, and the per-account budget/action map.
# All attributes are confirmed present in hashicorp/aws v6.67.0:
#   - aws_organizations_organizational_unit: id, arn, name
#   - aws_organizations_policy:               id
#   - aws_iam_role:                           arn
#   - aws_budgets_budget:                     name
#   - aws_budgets_budget_action:              id
# =============================================================================

# --- Workshop OU (Requirement 2.1) ------------------------------------------
output "workshop_ou_id" {
  description = "ID of the workshop organizational unit."
  value       = aws_organizations_organizational_unit.workshop.id
}

output "workshop_ou_arn" {
  description = "ARN of the workshop organizational unit."
  value       = aws_organizations_organizational_unit.workshop.arn
}

output "workshop_ou_name" {
  description = "Name of the workshop organizational unit (workshop-<workshop_id>)."
  value       = aws_organizations_organizational_unit.workshop.name
}

# --- Service Control Policies (Requirements 4.1, 5.1) -----------------------
output "kiro_guardrail_scp_id" {
  description = "ID of the Kiro guardrail SCP attached to the workshop OU."
  value       = aws_organizations_policy.kiro_guardrail.id
}

output "freeze_scp_id" {
  description = "ID of the deny-all freeze SCP (created unattached; AWS Budgets attaches it on breach)."
  value       = aws_organizations_policy.freeze.id
}

# --- Budgets execution role (Requirement 6.1) -------------------------------
output "budgets_execution_role_arn" {
  description = "ARN of the least-privilege role AWS Budgets assumes to attach/detach the freeze SCP."
  value       = aws_iam_role.budgets_execution.arn
}

# --- Per-account budget/action map (Requirement 7.1) ------------------------
# Keyed by account id → { budget_name, action_id }, built with a for-expression
# over var.account_ids so the key set exactly matches the supplied accounts.
output "per_account_budgets" {
  description = "Per-account map of the COST budget name and its AUTOMATIC freeze action id, keyed by account id."
  value = {
    for a in var.account_ids : a => {
      budget_name = aws_budgets_budget.account[a].name
      action_id   = aws_budgets_budget_action.freeze[a].id
    }
  }
}
