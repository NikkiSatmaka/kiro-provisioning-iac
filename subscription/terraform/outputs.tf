output "instance_arn" {
  description = "ARN of the IAM Identity Center account instance."
  value       = local.instance_arn
}

output "identity_store_id" {
  description = "Identity store ID backing the account instance. Scripts need this."
  value       = local.identity_store_id
}

output "region" {
  description = "Region the instance lives in (also the Kiro sign-in region code)."
  value       = local.resolved_region
}

output "account_id" {
  description = "Child AWS account ID associated with the provisioned IdC (from idc_account_map)."
  value       = local.account_id
}

output "kiro_tier" {
  description = "Configured Kiro tier (applied to groups by scripts/)."
  value       = var.kiro_tier
}

# The default AWS access portal sign-in URL is derived directly from the
# identity store id (format: d-xxxxxxxxxx.awsapps.com/start). Scripts read this
# so users never have to paste the URL by hand. NOTE: if you later configure a
# custom vanity subdomain in the IdC console (your_subdomain.awsapps.com/start),
# this default URL still works but no longer matches the vanity one — pass the
# custom URL explicitly to the renderer in that case.
output "sign_in_url" {
  description = "Default AWS access portal sign-in URL derived from the identity store id."
  value       = "https://${local.identity_store_id}.awsapps.com/start"
}

output "users" {
  description = "Created users: padded-sequence => { username, email, user_id }. email is null for anonymous users."
  value = {
    for k, u in aws_identitystore_user.this :
    k => {
      username = u.user_name
      email    = local.users[k].email
      user_id  = u.user_id
    }
  }
}

output "groups" {
  description = "Created groups: padded-sequence => { display_name, group_id }."
  value = {
    for k, g in aws_identitystore_group.this :
    k => {
      display_name = g.display_name
      group_id     = g.group_id
    }
  }
}

output "memberships" {
  description = "Resolved user->group memberships."
  value = {
    for k, m in local.memberships :
    k => {
      username = local.users[m.user_key].username
      group    = local.groups[m.group_key].name
    }
  }
}

# Convenience: a single JSON blob the scripts can consume via
#   tofu output -json provisioning_manifest > ../output/manifest.json
output "provisioning_manifest" {
  description = "Everything scripts/ needs in one object. No secrets."
  value = {
    region            = local.resolved_region # deployment / IdC region (unchanged meaning)
    kiro_region       = var.kiro_region        # Kiro sign-in region (sign-in only)
    account_id        = local.account_id       # document-level child AWS account ID
    instance_arn      = local.instance_arn
    identity_store_id = local.identity_store_id
    kiro_tier         = var.kiro_tier
    sign_in_url       = "https://${local.identity_store_id}.awsapps.com/start"
    users = {
      for k, u in aws_identitystore_user.this :
      k => {
        username   = u.user_name
        email      = local.users[k].email
        user_id    = u.user_id
        account_id = local.user_account_id[k]
      }
    }
    groups = {
      for k, g in aws_identitystore_group.this :
      k => {
        display_name = g.display_name
        group_id     = g.group_id
      }
    }
    # Resolved user->group memberships, same shape as the standalone
    # `memberships` output. The credentials renderer reads this to fill each
    # user's Group(s) column; without it every user renders as "—".
    memberships = {
      for k, m in local.memberships :
      k => {
        username = local.users[m.user_key].username
        group    = local.groups[m.group_key].name
      }
    }
  }
}
