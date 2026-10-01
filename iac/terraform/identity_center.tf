# ===========================================================================
# IAM Identity Center — ACCOUNT instance in this (child) account
# ===========================================================================
#
# aws_ssoadmin_instance creates an *account* instance of Identity Center in the
# account/region the provider targets. This is distinct from the organization
# instance that may already exist in the management account.
#
# PRECONDITION (cannot be enforced from here): the org management account must
# have permitted member-account instance creation. If it has not, apply fails
# with an authorization error on this resource. See RUNBOOK.md step 0.
#
# One account instance per account (across all regions). Importing an existing
# instance:
#   tofu import awscc_sso_instance.this <instance_arn>

resource "awscc_sso_instance" "this" {
  # name is optional; helps identify the instance in the console.
  name = var.instance_name

  # AWSCC uses a list-of-objects tag shape (no provider default_tags support).
  tags = [for k, v in var.default_tags : { key = k, value = v }]
}

locals {
  identity_store_id = awscc_sso_instance.this.identity_store_id
  instance_arn      = awscc_sso_instance.this.instance_arn
}

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
# These users exist for Kiro login only. We deliberately create NO permission
# sets and NO account assignments, so they have zero AWS account access.
#
# NOTE: aws_identitystore_user cannot set a password and does not send an
# invitation email — AWS exposes neither via API. Password setup is a console
# step handled after apply (see scripts/ and RUNBOOK.md).

resource "aws_identitystore_user" "this" {
  for_each = local.users

  identity_store_id = local.identity_store_id

  user_name    = each.value.username
  display_name = each.value.display_name

  name {
    given_name  = each.value.given_name
    family_name = each.value.family_name
  }

  emails {
    value   = each.value.email
    primary = true
  }
}

# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------
# Kiro subscriptions are assigned per group (done later via console/script).

resource "aws_identitystore_group" "this" {
  for_each = local.groups

  identity_store_id = local.identity_store_id
  display_name      = each.value.name
  description       = "Kiro subscription group ${each.value.name}"
}

# ---------------------------------------------------------------------------
# Group memberships (strategy-driven; see locals.tf)
# ---------------------------------------------------------------------------

resource "aws_identitystore_group_membership" "this" {
  for_each = local.memberships

  identity_store_id = local.identity_store_id
  group_id          = aws_identitystore_group.this[each.value.group_key].group_id
  member_id         = aws_identitystore_user.this[each.value.user_key].user_id
}
