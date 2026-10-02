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

output "kiro_tier" {
  description = "Configured Kiro tier (applied to groups by scripts/)."
  value       = var.kiro_tier
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
    region            = local.resolved_region
    instance_arn      = local.instance_arn
    identity_store_id = local.identity_store_id
    kiro_tier         = var.kiro_tier
    users = {
      for k, u in aws_identitystore_user.this :
      k => {
        username = u.user_name
        email    = local.users[k].email
        user_id  = u.user_id
      }
    }
    groups = {
      for k, g in aws_identitystore_group.this :
      k => {
        display_name = g.display_name
        group_id     = g.group_id
      }
    }
  }
}
