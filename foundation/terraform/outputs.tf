output "instance_arn" {
  description = "ARN of the IAM Identity Center account instance. Export into the subscription stack as TF_VAR_idc_instance_arn."
  value       = local.instance_arn
}

output "identity_store_id" {
  description = "Identity store ID backing the account instance (d-xxxxxxxxxx). Export into the subscription stack as TF_VAR_identity_store_id."
  value       = local.identity_store_id
}

output "region" {
  description = "Region the IdC instance was created in (the concrete region the providers resolved to)."
  value       = local.resolved_region
}

# The default AWS access portal sign-in URL is derived directly from the
# identity store id (format: d-xxxxxxxxxx.awsapps.com/start). Same derivation the
# subscription stack uses, so a vanity-subdomain caveat applies there too.
output "sign_in_url" {
  description = "Default AWS access portal sign-in URL derived from the identity store id."
  value       = "https://${local.identity_store_id}.awsapps.com/start"
}
