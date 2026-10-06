"""Property 1: every group maps to exactly one account assignment.

Feature: multi-workshop-provisioning, Property 1: every group maps to exactly
one account assignment
Validates: Requirements 2.2, 2.3

Property 1: *For any* valid ``workshop_accounts`` map, the flatten emits exactly
one account assignment per declared group — so a child account that holds G
groups yields exactly G assignments (R2.3), each assignment binds its group to
that account via a ``target_id`` equal to the account's own 12-digit id (R2.2),
and no group is left without an assignment and no account gets an assignment it
does not own.

The property drives the pure Python mirror of ``locals.tf`` (``workshop_flatten``):
each example builds a Hypothesis-generated ``workshop_accounts`` map over valid
12-digit account ids and non-empty group names, derives the assignments, and
asserts the per-account cardinality and the ``target_id`` identity hold. A
regression that emitted a shared assignment, dropped a group, or pointed an
assignment at the wrong account's id fails here.

Harness note: ``workshop_flatten`` lives under ``tests/`` and is importable via
the shared conftest ``sys.path`` shim (``tests/`` is on the path), mirroring how
the sibling renderer property tests import their helpers.
"""

from __future__ import annotations

import workshop_flatten as wf
from hypothesis import given, settings
from hypothesis import strategies as st

# Account ids are 12-digit AWS account numbers (the workshop_accounts validation
# enforces ``^[0-9]{12}$``). Full 12-digit strings keep values in the real input
# space; drawing them unique per map guarantees each account is distinguishable,
# so an assignment pointing at the wrong account's id is unambiguously caught.
_account_ids = st.text(alphabet="0123456789", min_size=12, max_size=12)

# Group names are non-empty strings (the validation enforces non-empty after
# trimspace). Exclude ':' because the flatten key is "<account_id>:<group>" and
# a ':' in a group name would be ambiguous — the HCL group names in practice are
# slugs, and the key stability property (R3.7) relies on an unambiguous split.
_group_names = st.text(
    alphabet=st.characters(
        min_codepoint=0x21,
        max_codepoint=0x7E,
        blacklist_characters=":",
    ),
    min_size=1,
    max_size=24,
).filter(lambda s: s.strip() != "")

# A group config holds a user_count in the inclusive range 0..500 (the
# validation bound). Property 1 is about group->account cardinality, not user
# counts, but using the real range keeps the generated maps valid end-to-end.
_group_cfg = st.builds(lambda n: {"user_count": n}, st.integers(min_value=0, max_value=500))


@st.composite
def _workshop_accounts(draw):
    """A valid ``workshop_accounts`` map: unique 12-digit accounts, each with
    one or more uniquely-named groups.

    Builds between 1 and 4 accounts (all distinct ids) and, under each, a
    non-empty map of 1..5 uniquely-named groups, so every account has a known,
    positive group count G to check the assignment cardinality against.
    """
    account_ids = draw(
        st.lists(_account_ids, min_size=1, max_size=4, unique=True)
    )
    accounts = {}
    for acct in account_ids:
        group_names = draw(
            st.lists(_group_names, min_size=1, max_size=5, unique=True)
        )
        accounts[acct] = {
            "groups": {gname: draw(_group_cfg) for gname in group_names}
        }
    return accounts


@settings(max_examples=200, deadline=None)
@given(accounts=_workshop_accounts())
def test_every_group_maps_to_exactly_one_account_assignment(accounts):
    """Each group yields exactly one assignment targeting its owning account.

    Feature: multi-workshop-provisioning, Property 1: every group maps to
    exactly one account assignment
    Validates: Requirements 2.2, 2.3
    """
    assignments = wf.assignments(accounts)

    # Total assignments equals the total number of declared groups: no group is
    # dropped and none is duplicated.
    total_groups = sum(len(cfg["groups"]) for cfg in accounts.values())
    assert len(assignments) == total_groups

    # Per-account cardinality: an account holding G groups yields exactly G
    # assignments whose target_id is that account's own 12-digit id (R2.3).
    for account_id, cfg in accounts.items():
        owned = [
            a for a in assignments.values() if a.target_id == account_id
        ]
        assert len(owned) == len(cfg["groups"]), (
            f"account {account_id} has {len(cfg['groups'])} groups "
            f"but {len(owned)} assignments target it"
        )

    # Per-assignment identity: every assignment's target_id is a declared
    # 12-digit account id, and it is exactly the account under which its group's
    # key is nested (R2.2). The group_key is "<account_id>:<group>", so the
    # target_id must equal the key's account prefix.
    for gk, a in assignments.items():
        assert a.group_key == gk
        assert a.target_id in accounts, (
            f"assignment target_id {a.target_id!r} is not a declared account"
        )
        owning_account = gk.split(":", 1)[0]
        assert a.target_id == owning_account, (
            f"group {gk!r}: target_id {a.target_id!r} != owning account "
            f"{owning_account!r}"
        )

    # Every declared group is covered by exactly one assignment, keyed by that
    # group's for_each key — the one-to-one mapping the property names.
    expected_keys = {
        wf.group_key(acct, gname)
        for acct, cfg in accounts.items()
        for gname in cfg["groups"]
    }
    assert set(assignments.keys()) == expected_keys
