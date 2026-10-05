locals {
  # Region the provider actually resolved to (from var.aws_region or the
  # AWS_REGION env fallback). Outputs/manifest report this concrete value.
  resolved_region = data.aws_region.current.region

  pad = var.sequence_padding

  # Sequence numbers, e.g. start=1 count=3 => [1, 2, 3]
  user_seq  = [for i in range(var.user_count) : i + var.sequence_start]
  group_seq = [for i in range(var.group_count) : i + var.sequence_start]

  # Zero-padded string form, e.g. 1 => "01"
  user_seq_str  = [for n in local.user_seq : format("%0${local.pad}d", n)]
  group_seq_str = [for n in local.group_seq : format("%0${local.pad}d", n)]

  # Final names keyed by the padded sequence so for_each is stable.
  # { "01" => "kiro-user-01", "02" => "kiro-user-02", ... }
  # Users are keyed on a zero-padded sequence and named by username. Email is
  # OPTIONAL and supplemental: looked up from var.user_emails by the same key,
  # null when the user has no entry. A null email renders no emails block on the
  # IdC user (see identity_center.tf) — IAM Identity Center requires none.
  users = {
    for s in local.user_seq_str :
    s => {
      username     = "${var.user_prefix}${s}"
      email        = lookup(var.user_emails, s, null)
      display_name = replace(replace(var.display_name_template, "{seq}", s), "{name}", "${var.user_prefix}${s}")
      given_name   = "Kiro"
      family_name  = "User ${s}"
    }
  }

  groups = {
    for s in local.group_seq_str :
    s => {
      name = "${var.group_prefix}${s}"
    }
  }

  # ---- Account resolution -------------------------------------------------
  # The IdC key for the single account instance this stack provisions.
  idc_key = "default"

  # The account_id for this IdC, or "" when the map has no entry (keeps the
  # pipeline running with an empty cell rather than failing render).
  account_id = lookup(var.idc_account_map, local.idc_key, "")

  # Per-user account_id. Today every user belongs to the single IdC, so each
  # resolves to local.account_id. Keyed per user so a future multi-IdC layout
  # can vary it by user without changing downstream consumers.
  user_account_id = { for k, _ in local.users : k => local.account_id }

  # ---- Membership mapping -------------------------------------------------
  # Produces a map of membership keys => { user_key, group_key } so the
  # aws_identitystore_group_membership for_each is stable.

  group_keys = keys(local.groups)
  user_keys  = keys(local.users)

  memberships_all_in_first = (
    length(local.group_keys) == 0 ? {} : {
      for uk in local.user_keys :
      "${uk}->${local.group_keys[0]}" => {
        user_key  = uk
        group_key = local.group_keys[0]
      }
    }
  )

  memberships_round_robin = (
    length(local.group_keys) == 0 ? {} : {
      for idx, uk in local.user_keys :
      "${uk}->${local.group_keys[idx % length(local.group_keys)]}" => {
        user_key  = uk
        group_key = local.group_keys[idx % length(local.group_keys)]
      }
    }
  )

  memberships = (
    var.membership_strategy == "all_in_first" ? local.memberships_all_in_first :
    var.membership_strategy == "round_robin" ? local.memberships_round_robin :
    {}
  )
}
