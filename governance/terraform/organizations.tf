# ===========================================================================
# Organizations — one workshop OU (accounts are moved in out-of-band)
# ===========================================================================
#
# This stack NEVER creates, invites, closes, or owns an account (Requirement 1).
# It owns ONLY the workshop OU; the SCP attachment and per-account budgets live
# in the sibling files. The accounts in var.account_ids are already created and
# already members of the organization.

# --- The workshop OU --------------------------------------------------------
#
# Exactly one OU per run — a single resource, NEVER for_each — so a run always
# produces one OU named workshop-<workshop_id> under the caller-supplied parent
# (Requirements 2.1-2.4).

resource "aws_organizations_organizational_unit" "workshop" {
  name      = "workshop-${var.workshop_id}"
  parent_id = var.parent_id
}

# --- Account placement is OUT-OF-BAND, not a Terraform resource -------------
#
# The pre-existing accounts in var.account_ids are moved into the workshop OU
# OUTSIDE Terraform, by `mise run governance-place-accounts` (which runs
# `aws organizations move-account` once per id). This stack deliberately owns NO
# account resource.
#
# WHY no Terraform resource places accounts here:
#   * hashicorp/aws v6.67.0 exposes NO standalone "move account into an OU" or
#     OU-membership resource (the long-standing provider gap, issue #8281, is
#     unresolved as of this version). The ONLY resource that carries account->OU
#     placement is the organizations *account* resource — AWS's CREATE-an-account
#     resource. Using it to express placement means an apply with no prior state
#     CREATES brand-new accounts (which is exactly how two phantom accounts were
#     once minted). No combination of import / ignore_changes / prevent_destroy
#     / close_on_deletion removes that create-on-missing-state hazard.
#   * Moving placement out-of-band makes it STRUCTURALLY IMPOSSIBLE for this
#     stack to ever create, invite, close, or own an account.
#
# INVARIANT: this stack never creates, invites, closes, or owns an account. It
# creates only the OU; placement into that OU is the out-of-band move-account
# step. var.account_ids is still required here — the per-account budgets are
# keyed by it, and the move-account task reads it.
