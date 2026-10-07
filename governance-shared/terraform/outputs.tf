# =============================================================================
# outputs.tf — the shared-primitive handoff into per-workshop governance/
#
# The three once-per-management-account resources this stack owns. Export each
# into the governance stack as the matching TF_VAR_* (NOT remote state) — the
# governance-shared-apply mise task prints the three export lines. These were
# previously emitted by foundation/ (same descriptions); they now come from the
# local resources in this stack.
# =============================================================================

output "budgets_execution_role_arn" {
  description = "ARN of the shared least-privilege role AWS Budgets assumes to attach/detach the freeze SCP. Export into the governance stack as TF_VAR_budgets_execution_role_arn."
  value       = aws_iam_role.budgets_execution.arn
}

output "kiro_guardrail_scp_id" {
  description = "ID of the shared Kiro guardrail SCP the governance stack attaches to each workshop OU. Export into the governance stack as TF_VAR_kiro_guardrail_scp_id."
  value       = aws_organizations_policy.kiro_guardrail.id
}

output "freeze_scp_id" {
  description = "ID of the shared deny-all freeze SCP AWS Budgets attaches to a breaching account on breach. Export into the governance stack as TF_VAR_freeze_scp_id."
  value       = aws_organizations_policy.freeze.id
}
