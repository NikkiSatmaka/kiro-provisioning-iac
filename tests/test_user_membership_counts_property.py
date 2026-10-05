"""Property 2: user and membership counts equal the declared user_count.

Feature: multi-workshop-provisioning, Property 2: user and membership counts
equal the declared user_count
Validates: Requirements 3.6

Property 2: *For any* valid ``workshop_accounts`` map, the flatten produces, for
a group declared with ``user_count = N``, exactly N users nested under that
group and exactly N memberships placing each of those users into that same
group — so the per-group user/membership cardinality is N, no participant is
dropped or duplicated, and the whole-map totals (sum of users, sum of
memberships) both equal the sum of every group's declared ``user_count``.

The property drives the pure Python mirror of ``locals.tf``
(``workshop_flatten.users`` / ``workshop_flatten.memberships``): each example
builds a Hypothesis-generated ``workshop_accounts`` map over valid 12-digit
account ids and non-empty group names with per-group ``user_count`` in the
validated ``0..500`` range, derives the users and memberships, and asserts the
per-group count equals N, every membership points at its user's own group, and
the map-wide totals add up. A regression that miscounted a group, placed a user
in the wrong group, or emitted a membership without a matching user fails here.

Harness note: ``workshop_flatten`` lives under ``tests/`` and is importable via
the shared conftest ``sys.path`` shim, mirroring the sibling property tests
(``test_group_account_assignment_property.py``). ``users``/``memberships`` take
a ``workshop_id``; it only shapes the derived ``username`` string and does not
affect counts, so a single fixed valid slug is used throughout.
"""

from __future__ import annotations

import workshop_flatten as wf
from hypothesis import given, settings
from hypothesis import strategies as st

# Account ids are 12-digit AWS account numbers (the ``workshop_accounts``
# validation enforces ``^[0-9]{12}$``). Drawing them unique per map keeps every
# account distinguishable so a user attributed to the wrong account's group is
# caught.
_account_ids = st.text(alphabet="0123456789", min_size=12, max_size=12)

# Group names are non-empty strings (the validation enforces non-empty after
# trimspace). Exclude ':' because the flatten key is "<account_id>:<group>:<NN>"
# and a ':' in a group name would make the key split ambiguous — the HCL group
# names in practice are slugs.
_group_names = st.text(
    alphabet=st.characters(
        min_codepoint=0x21,
        max_codepoint=0x7E,
        blacklist_characters=":",
    ),
    min_size=1,
    max_size=24,
).filter(lambda s: s.strip() != "")

# ``user_count`` is bounded 0..500 by the variable validation. Keep the upper
# bound small enough that generated maps stay cheap to flatten across 200
# examples while still covering 0 (a group with no participants) and multi-digit
# counts (which exercise the zero-pad width). The property holds for all N in
# the validated range; 0..40 is a representative, fast slice.
_user_count = st.integers(min_value=0, max_value=40)

# ``workshop_id`` only shapes the derived ``username``; counts are independent of
# it. Use a single fixed valid slug (1-63 lowercase alphanumeric + hyphens).
_WORKSHOP_ID = "ws-demo"


@st.composite
def _workshop_accounts(draw):
    """A valid ``workshop_accounts`` map: unique 12-digit accounts, each with
    one or more uniquely-named groups carrying a declared ``user_count``.

    Builds 1..4 accounts (distinct ids), each with 1..5 uniquely-named groups,
    so every (account, group) pair has a known declared ``user_count`` N to
    check the produced user/membership counts against.
    """
    account_ids = draw(st.lists(_account_ids, min_size=1, max_size=4, unique=True))
    accounts = {}
    for acct in account_ids:
        group_names = draw(st.lists(_group_names, min_size=1, max_size=5, unique=True))
        accounts[acct] = {
            "groups": {gname: {"user_count": draw(_user_count)} for gname in group_names}
        }
    return accounts


@settings(max_examples=200, deadline=None)
@given(accounts=_workshop_accounts())
def test_user_and_membership_counts_equal_declared_user_count(accounts):
    """A group declared with ``user_count = N`` yields exactly N users and N
    memberships placing those users in that group; totals add up.

    Feature: multi-workshop-provisioning, Property 2: user and membership counts
    equal the declared user_count
    Validates: Requirements 3.6
    """
    users = wf.users(accounts, _WORKSHOP_ID)
    memberships = wf.memberships(accounts, _WORKSHOP_ID)

    # Per-group cardinality: a group declared with user_count N produces exactly
    # N users under that group and exactly N memberships placing those users in
    # the group — no participant dropped or duplicated.
    for account_id, cfg in accounts.items():
        for gname, g in cfg["groups"].items():
            n = g["user_count"]
            gk = wf.group_key(account_id, gname)

            users_in_group = [u for u in users.values() if u["group_key"] == gk]
            assert len(users_in_group) == n, (
                f"group {gk!r} declared user_count {n} but produced "
                f"{len(users_in_group)} users"
            )

            memberships_in_group = [
                m for m in memberships.values() if m["group_key"] == gk
            ]
            assert len(memberships_in_group) == n, (
                f"group {gk!r} declared user_count {n} but produced "
                f"{len(memberships_in_group)} memberships"
            )

            # The N memberships place exactly this group's N users — the user_key
            # sets match one-to-one, so a membership cannot point at a user from
            # another group.
            group_user_keys = {
                uk for uk, u in users.items() if u["group_key"] == gk
            }
            membership_user_keys = {
                m["user_key"] for m in memberships_in_group
            }
            assert membership_user_keys == group_user_keys, (
                f"group {gk!r}: memberships place users {membership_user_keys} "
                f"but the group's users are {group_user_keys}"
            )

    # Whole-map totals: the sum of users and the sum of memberships both equal
    # the sum of every declared user_count.
    total_declared = sum(
        g["user_count"]
        for cfg in accounts.values()
        for g in cfg["groups"].values()
    )
    assert len(users) == total_declared
    assert len(memberships) == total_declared

    # Every membership references a user that exists, and places it in that
    # user's own group — the membership is a faithful user->group placement, not
    # a dangling or mismatched reference.
    for uk, m in memberships.items():
        assert m["user_key"] == uk
        assert uk in users, f"membership {uk!r} references a non-existent user"
        assert m["group_key"] == users[uk]["group_key"], (
            f"membership {uk!r} places the user in {m['group_key']!r} but the "
            f"user's group is {users[uk]['group_key']!r}"
        )
