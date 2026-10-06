# ===========================================================================
# Organizations — one workshop OU + placement of pre-existing accounts
# ===========================================================================
#
# This stack NEVER creates or invites accounts (Requirement 1). The accounts in
# var.account_ids are already created and already members of the organization;
# the stack only places them under this workshop's OU.

# --- The workshop OU --------------------------------------------------------
#
# Exactly one OU per run — a single resource, NEVER for_each — so a run always
# produces one OU named workshop-<workshop_id> under the caller-supplied parent
# (Requirements 2.1-2.4).

resource "aws_organizations_organizational_unit" "workshop" {
  name      = "workshop-${var.workshop_id}"
  parent_id = var.parent_id
}

# --- Account placement ------------------------------------------------------
#
# PLACEMENT MECHANISM (confirmed against the installed provider, hashicorp/aws
# v6.67.0): adopt each pre-existing account via `aws_organizations_account`,
# IMPORTED (never created), with parent_id pointed at the workshop OU so the
# only change the provider ever makes is the MOVE into the OU.
#
# Why this resource, and why it is safe here:
#   * hashicorp/aws v6.67.0 still exposes NO standalone "move account into OU"
#     or OU-membership resource (the long-standing provider gap, issue #8281,
#     is unresolved as of this version). `aws_organizations_account` is the only
#     resource carrying a `parent_id`, so it is the placement primitive.
#   * Per the v6.67.0 resource docs, DELETING this resource by default only
#     REMOVES the account from the organization — it does NOT close the account.
#     Closing requires the opt-in `close_on_deletion = true`, which we never
#     set. So even a destroy cannot close a pre-existing account.
#   * We add `prevent_destroy = true` as a second, explicit guard: a destroy of
#     this stack errors out rather than touching these accounts at all
#     (Requirements 1.1, 3.1-3.3). The OU/SCP teardown path is documented in the
#     RUNBOOK; accounts must be moved out manually first.
#   * `ignore_changes` on name/email/role_name: these are set only to satisfy
#     the required/importable schema. The real values live in AWS and (for
#     role_name) are unreadable after import, so without ignore_changes the plan
#     would perpetually show spurious diffs. Ignoring them keeps the plan to the
#     single meaningful attribute — parent_id — i.e. the placement itself.
#
# IMPORT IS REQUIRED (these are NOT applies that create accounts). Each account
# is adopted into state before plan/apply, one per supplied id:
#   tofu import 'aws_organizations_account.placed["111111111111"]' 111111111111
# After import the only planned change is the move into the workshop OU. If an
# account is already in the OU, the plan is a no-op for it.
#
# RUNBOOK (task 10) — RECORD THIS:
#   Chosen mechanism : aws_organizations_account adopted via `tofu import`,
#                      parent_id = workshop OU, close_on_deletion unset (false),
#                      prevent_destroy = true, ignore_changes on name/email/role.
#   moveAccount fallback (if an operator prefers not to adopt into state, or the
#   import is impractical): place accounts out-of-band and let the stack own
#   only the OU + SCP attachment —
#     aws organizations move-account \
#       --account-id <id> \
#       --source-parent-id <current root/parent id> \
#       --destination-parent-id <workshop OU id>
#   (or the console "Move AWS account" action), once per account.
#
# Placement is keyed SOLELY by var.account_ids, so no account outside that set
# is ever moved (Requirement 3.3).

resource "aws_organizations_account" "placed" {
  for_each = toset(var.account_ids)

  # Existing account — these satisfy the schema and are reconciled from AWS on
  # import; the real values are ignored below so they never drive a diff.
  name      = each.key
  email     = "placeholder+${each.key}@example.invalid"
  parent_id = aws_organizations_organizational_unit.workshop.id

  # Default (false) means a destroy only removes the account from the org, never
  # closes it. Stated explicitly so the intent is unmistakable.
  close_on_deletion = false

  lifecycle {
    # Never let a destroy of this stack touch a pre-existing account.
    prevent_destroy = true

    # Only the placement (parent_id) is meaningful here; the rest are set to
    # satisfy the schema and reconciled on import. role_name in particular is
    # unreadable after creation, so ignoring it avoids a permanent phantom diff.
    ignore_changes = [name, email, role_name]
  }
}
