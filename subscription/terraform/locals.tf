locals {
  # ---- Foundation IdC interface -------------------------------------------
  # Resolved from operator-supplied inputs (see var.idc_instance_arn and
  # var.identity_store_id). This module consumes the long-lived, org-level
  # Foundation IdC instance; it neither creates nor destroys it.
  identity_store_id = var.identity_store_id
  instance_arn      = var.idc_instance_arn

  # Region the provider actually resolved to (from var.aws_region or the
  # AWS_REGION env fallback). Outputs/manifest report this concrete value.
  resolved_region = data.aws_region.current.region

  # ---- Flatten workshop_accounts ------------------------------------------
  # The operator supplies an explicit nested map:
  #   { <account_id> => { groups = { <group> => { user_count = N } } } }
  # Pillar 2 flattens it into the keyed maps the existing for_each resources
  # (aws_identitystore_user/group/group_membership) consume, plus the
  # group->account and user->account resolution tables that drive the per-group
  # account assignments and the per-user account_id flow.
  #
  # Keys are built from account id + group name + per-group index only — never a
  # global running counter — so they are deterministic and locally stable: a
  # change confined to one account leaves every other account's keys
  # byte-identical and OpenTofu does not churn unrelated resources (R3.7).

  # Group -> owning account. Key a group as "<account_id>:<group_name>" so the
  # same group name under two accounts stays distinct and stable (R3.7).
  group_account = merge([
    for acct, cfg in var.workshop_accounts : {
      for gname, _ in cfg.groups : "${acct}:${gname}" => acct
    }
  ]...)

  # Groups: group_key => { name }. (name is the human group name shown in IdC.)
  # Same "<account_id>:<group_name>" keying as group_account so two accounts can
  # reuse a group name without a collision.
  groups = merge([
    for acct, cfg in var.workshop_accounts : {
      for gname, _ in cfg.groups : "${acct}:${gname}" => { name = gname }
    }
  ]...)

  # Flatten users to a list first (so the per-group index is available), then
  # key. width = max(2, len(str(user_count))) keeps NN zero-padded to at least
  # two digits and wider only when a group exceeds 99 users.
  _user_rows = flatten([
    for acct, cfg in var.workshop_accounts : [
      for gname, g in cfg.groups : [
        for i in range(g.user_count) : {
          account_id = acct
          group      = gname
          group_key  = "${acct}:${gname}"
          index      = i + 1
          width      = max(2, length(tostring(g.user_count)))
        }
      ]
    ]
  ])

  # Users: "<account_id>:<group>:<NN>" => the record the resources consume.
  # username  = "<workshop_id>-<acct_last4>-<group>-<NN>" (last 4 of the account
  #             id keeps the name short while unique when a group name recurs
  #             under two accounts).
  # email     = null (anonymous OTP flow; the emails block renders nothing).
  # The user resource reads only username/display_name/given_name/family_name/
  # email; the extra group_key/account_id keys are carried for the membership
  # and manifest derivations and ignored by the user resource.
  users = {
    for r in local._user_rows :
    "${r.account_id}:${r.group}:${format("%0${r.width}d", r.index)}" => {
      username     = "${var.workshop_id}-${substr(r.account_id, 8, 4)}-${r.group}-${format("%0${r.width}d", r.index)}"
      email        = null
      display_name = "${r.group} participant ${format("%0${r.width}d", r.index)}"
      given_name   = "Kiro"
      family_name  = "${r.group} ${format("%0${r.width}d", r.index)}"
      group_key    = r.group_key
      account_id   = r.account_id
    }
  }

  # One membership per user, placing that user in its own group.
  memberships = {
    for uk, u in local.users :
    uk => { user_key = uk, group_key = u.group_key }
  }

  # Per-user account_id, resolved through user -> group -> owning account (R4.1).
  user_account_id = { for uk, u in local.users : uk => u.account_id }

  # Document-level account_id: the single account when the workshop has exactly
  # one, else "" (the per-user column is authoritative for multi-account).
  account_id = length(keys(var.workshop_accounts)) == 1 ? keys(var.workshop_accounts)[0] : ""
}
