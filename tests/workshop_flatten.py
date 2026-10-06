"""Pure Python mirror of the ``subscription/terraform/locals.tf`` flatten.

Feature: multi-workshop-provisioning

The design (Pillar 2) flattens the operator-supplied ``workshop_accounts``
nested map — ``{ <account_id> => { groups = { <group> => { user_count = N } } } }``
— into the keyed maps the existing ``for_each`` resources consume, plus the
group-to-account and user-to-account resolution tables that drive the per-group
account assignments and the per-user ``account_id`` flow.

This module is a *pure* Python re-implementation of that HCL derivation. It
takes the exact same input shape (``workshop_accounts``) and produces the same
derived maps the HCL ``locals`` block does, so the property tests can exercise
the derivation logic deterministically, offline, over many Hypothesis-generated
inputs — no ``tofu`` process, no AWS, no cloud.

Keep this a faithful mirror of ``locals.tf``: when the HCL flatten changes, this
mirror changes with it. The sibling property tests (Properties 1-5) all read
from here rather than each re-deriving the flatten, so the mirror is defined
once and shared.

Mapped directly from the design's ``locals.tf``:

    group_account   = { "<account_id>:<group>"      => "<account_id>" }
    groups          = { "<account_id>:<group>"      => { "name": "<group>" } }
    users           = { "<account_id>:<group>:<NN>" => { username, email,
                                                         display_name, given_name,
                                                         family_name, group_key,
                                                         account_id } }
    memberships     = { "<user_key>"                => { user_key, group_key } }
    user_account_id = { "<user_key>"                => "<account_id>" }
    assignments     = one per groups entry:
                        { group_key, principal (group_key), target_id (account) }
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Input type (mirrors the ``workshop_accounts`` tfvars shape)
# ---------------------------------------------------------------------------

# ``workshop_accounts`` is a map keyed by 12-digit account id. Each value holds
# a ``groups`` map keyed by group name, and each group holds a ``user_count``.
# In Python we accept the equivalent nested dict:
#   { "111111111111": {"groups": {"team-a": {"user_count": 3}}}, ... }
WorkshopAccounts = dict


@dataclass(frozen=True)
class Assignment:
    """One ``aws_ssoadmin_account_assignment`` the HCL emits per group.

    ``group_key`` is the ``for_each`` key (``"<account_id>:<group>"``); the HCL
    sets ``principal_id`` from the group at that key and ``target_id`` from
    ``local.group_account[each.key]`` — the owning account's 12-digit id.
    """

    group_key: str
    target_id: str


def group_key(account_id: str, group: str) -> str:
    """The stable ``for_each`` key for a group: ``"<account_id>:<group>"``.

    Mirrors the HCL key expression ``"${acct}:${gname}"``. Keying by account id
    plus group name (not bare name) is what lets the same group name recur under
    two accounts without a collision and keeps keys stable per account (R3.7).
    """
    return f"{account_id}:{group}"


def group_account(accounts: WorkshopAccounts) -> dict[str, str]:
    """``local.group_account``: group_key => owning account id.

    Mirrors::

        group_account = merge([
          for acct, cfg in var.workshop_accounts : {
            for gname, _ in cfg.groups : "${acct}:${gname}" => acct
          }
        ]...)
    """
    out: dict[str, str] = {}
    for account_id, cfg in accounts.items():
        for gname in cfg.get("groups", {}):
            out[group_key(account_id, gname)] = account_id
    return out


def groups(accounts: WorkshopAccounts) -> dict[str, dict[str, str]]:
    """``local.groups``: group_key => ``{ "name": <group> }``.

    Mirrors the ``merge([for ...]...)`` idiom producing
    ``{ "<account_id>:<group>" => { name = <group> } }``.
    """
    out: dict[str, dict[str, str]] = {}
    for account_id, cfg in accounts.items():
        for gname in cfg.get("groups", {}):
            out[group_key(account_id, gname)] = {"name": gname}
    return out


def assignments(accounts: WorkshopAccounts) -> dict[str, Assignment]:
    """The account assignments: one per ``local.groups`` entry.

    The HCL resource is ``for_each = local.groups`` with
    ``target_id = local.group_account[each.key]``, so there is exactly one
    assignment per group, keyed by the same ``group_key``, whose ``target_id``
    is the owning account's 12-digit id (R2.2, R2.3).
    """
    ga = group_account(accounts)
    return {
        gk: Assignment(group_key=gk, target_id=ga[gk])
        for gk in groups(accounts)
    }


# ---------------------------------------------------------------------------
# User / membership derivation (shared with Properties 2-5)
# ---------------------------------------------------------------------------


def _width(user_count: int) -> int:
    """Zero-pad width for a group's per-user index: ``max(2, len(str(N)))``.

    Mirrors the HCL ``max(2, length(tostring(g.user_count)))``.
    """
    return max(2, len(str(user_count)))


def user_key(account_id: str, group: str, index: int, width: int) -> str:
    """A user's stable key: ``"<account_id>:<group>:<NN>"`` (1-based, padded).

    Mirrors ``"${r.account_id}:${r.group}:${format("%0${r.width}d", r.index)}"``.
    """
    return f"{account_id}:{group}:{index:0{width}d}"


def users(accounts: WorkshopAccounts, workshop_id: str) -> dict[str, dict]:
    """``local.users``: user_key => the user record the resources consume.

    Mirrors the HCL ``local._user_rows`` flatten + ``local.users`` map:
    a group with ``user_count = N`` yields N users indexed 1..N, each carrying
    ``username``/``email``/``display_name``/``given_name``/``family_name`` plus
    the ``group_key`` and ``account_id`` the manifest/membership derivation read.
    """
    out: dict[str, dict] = {}
    for account_id, cfg in accounts.items():
        for gname, g in cfg.get("groups", {}).items():
            count = g["user_count"]
            width = _width(count)
            gk = group_key(account_id, gname)
            for i in range(count):
                index = i + 1
                nn = f"{index:0{width}d}"
                uk = user_key(account_id, gname, index, width)
                out[uk] = {
                    "username": f"{workshop_id}-{account_id[8:12]}-{gname}-{nn}",
                    "email": None,
                    "display_name": f"{gname} participant {nn}",
                    "given_name": "Kiro",
                    "family_name": f"{gname} {nn}",
                    "group_key": gk,
                    "account_id": account_id,
                }
    return out


def memberships(accounts: WorkshopAccounts, workshop_id: str) -> dict[str, dict]:
    """``local.memberships``: user_key => ``{ user_key, group_key }``.

    Mirrors ``{ for uk, u in local.users : uk => { user_key = uk,
    group_key = u.group_key } }`` — one membership per user, placing that user
    in its own group.
    """
    return {
        uk: {"user_key": uk, "group_key": u["group_key"]}
        for uk, u in users(accounts, workshop_id).items()
    }


def user_account_id(accounts: WorkshopAccounts, workshop_id: str) -> dict[str, str]:
    """``local.user_account_id``: user_key => owning account id.

    Mirrors ``{ for uk, u in local.users : uk => u.account_id }`` — each user's
    account resolved through user -> group -> owning account (R4.1).
    """
    return {uk: u["account_id"] for uk, u in users(accounts, workshop_id).items()}
