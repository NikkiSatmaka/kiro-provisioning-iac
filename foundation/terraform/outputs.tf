output "instance_arn" {
  description = "ARN of the IAM Identity Center ORGANIZATION instance, read from the management account's existing instance. Export into the subscription stack as TF_VAR_idc_instance_arn."
  value       = local.instance_arn
}

output "identity_store_id" {
  description = "Identity store ID backing the organization instance (d-xxxxxxxxxx), read from the existing instance. Export into the subscription stack as TF_VAR_identity_store_id."
  value       = local.identity_store_id
}

output "region" {
  description = "Region the org IdC instance is read from (the concrete region the providers resolved to)."
  value       = local.resolved_region
}

# The default AWS access portal sign-in URL is derived directly from the
# identity store id (format: d-xxxxxxxxxx.awsapps.com/start). Same derivation the
# subscription stack uses, so a vanity-subdomain caveat applies there too.
output "sign_in_url" {
  description = "Default AWS access portal sign-in URL derived from the identity store id."
  value       = "https://${local.identity_store_id}.awsapps.com/start"
}

# --- Shared-primitive handoff into governance/ ------------------------------
# The three once-per-management-account resources this stack now owns. Export
# each into the governance stack as the matching TF_VAR_* (NOT remote state).
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
