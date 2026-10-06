# =============================================================================
# outputs.tf — operator-facing identifiers for the governance stack
#
# These surface the per-workshop pieces this stack OWNS: the OU and the
# per-account budget/action map. The shared guardrail/freeze SCP ids and the
# budgets execution role ARN are now INPUTS from foundation/ (wired forward as
# variables), not outputs this stack owns.
# All attributes are confirmed present in hashicorp/aws v6.67.0:
#   - aws_organizations_organizational_unit: id, arn, name
#   - aws_budgets_budget:                     name
#   - aws_budgets_budget_action:              id
# =============================================================================

# --- Workshop OU (Requirement 2.1) ------------------------------------------
output "workshop_ou_id" {
  description = "ID of the workshop organizational unit."
  value       = aws_organizations_organizational_unit.workshop.id
}

# --- Account ids to place (single source of truth for the move task) --------
# Echoes var.account_ids so the out-of-band `governance-place-accounts` task can
# read the authoritative list from `tofu output` instead of a parallel env var,
# keeping terraform.tfvars the one place account ids are declared.
output "account_ids" {
  description = "The pre-existing account ids this workshop places into the OU; read by the governance-place-accounts task."
  value       = var.account_ids
}

output "workshop_ou_arn" {
  description = "ARN of the workshop organizational unit."
  value       = aws_organizations_organizational_unit.workshop.arn
}

output "workshop_ou_name" {
  description = "Name of the workshop organizational unit (workshop-<workshop_id>)."
  value       = aws_organizations_organizational_unit.workshop.name
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
