# ===========================================================================
# IAM Identity Center — users, groups, and memberships
# ===========================================================================
#
# This module consumes the long-lived, org-level Foundation IdC instance as an
# interface; it neither creates nor destroys that instance. The instance ARN and
# identity store ID are operator-supplied inputs (see var.idc_instance_arn and
# var.identity_store_id); the foundation locals resolve from those variables.

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

  # Email is optional and supplemental (var.user_emails). The block renders only
  # for users that have an address; users without one stay anonymous. IAM
  # Identity Center's CreateUser does not require an email.
  dynamic "emails" {
    for_each = each.value.email == null ? [] : [each.value.email]
    content {
      value   = emails.value
      primary = true
    }
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
# ---------------------------------------------------------------------------
# Account access — one shared permission set, one assignment per group
# ---------------------------------------------------------------------------
# A single permission set is reused across every group; each group's account
# scope comes from its own account assignment, not from a distinct permission
# set (R2.1). The permission set binds to the Foundation IdC instance supplied
# via var.idc_instance_arn.

resource "aws_ssoadmin_permission_set" "this" {
  name         = "kiro-${var.workshop_id}"
  instance_arn = var.idc_instance_arn
  description  = "Account access for Kiro workshop ${var.workshop_id} groups."
  tags         = var.default_tags
}

# One assignment per group, binding the group to its owning account (R2.2, R2.3).
# local.groups and local.group_account are keyed "<account_id>:<group_name>" so
# the same group name under two accounts stays distinct (R3.7). Every participant
# of a group inherits the account access through the group assignment (R2.4).
resource "aws_ssoadmin_account_assignment" "this" {
  for_each = local.groups

  instance_arn       = var.idc_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.this.arn

  principal_type = "GROUP"
  principal_id   = aws_identitystore_group.this[each.key].group_id

  target_type = "AWS_ACCOUNT"
  target_id   = local.group_account[each.key]
}
