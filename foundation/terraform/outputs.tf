output "instance_arn" {
  description = "ARN of the IAM Identity Center instance this stack read — the ORGANIZATION instance when run in the management account, or the child account's ACCOUNT instance when run under a child-account profile. Export into the subscription stack as TF_VAR_idc_instance_arn."
  value       = local.instance_arn
}

output "identity_store_id" {
  description = "Identity store ID backing the instance (d-xxxxxxxxxx), read from the existing instance (org instance in management, account instance in a child account). Export into the subscription stack as TF_VAR_identity_store_id."
  value       = local.identity_store_id
}

output "region" {
  description = "Region the IdC instance is read from (the concrete region the providers resolved to)."
  value       = local.resolved_region
}

# The default AWS access portal sign-in URL is derived directly from the
# identity store id (format: d-xxxxxxxxxx.awsapps.com/start). Same derivation the
# subscription stack uses, so a vanity-subdomain caveat applies there too.
output "sign_in_url" {
  description = "Default AWS access portal sign-in URL derived from the identity store id."
  value       = "https://${local.identity_store_id}.awsapps.com/start"
}

# NOTE: the shared budgets role + 2 SCP policy objects (and their outputs) moved
# OUT of foundation into the management-only governance-shared/ stack, so
# foundation is account-safe (dual-mode). The three TF_VAR_* governance consumes
# (budgets_execution_role_arn, kiro_guardrail_scp_id, freeze_scp_id) now come
# from governance-shared-apply, not foundation.
