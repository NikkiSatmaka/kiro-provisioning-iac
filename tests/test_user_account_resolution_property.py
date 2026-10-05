"""Property 5: each participant's account_id is its owning account.

Feature: multi-workshop-provisioning, Property 5: each participant's account_id
is its owning account
Validates: Requirements 4.1, 4.3

Property 5: *For any* valid ``workshop_accounts`` map, every Participant's
Account_Id resolves to the 12-digit id of the Child_Account under which that
Participant's Group is nested. Concretely, for every user key ``uk`` the flatten
emits, both ``user_account_id[uk]`` (the user -> group -> owning-account table,
R4.1) and ``users[uk]["account_id"]`` (the per-user ``account_id`` threaded into
the Provisioning_Manifest entry, R4.3) equal the account id under which the
user's group sits — the account prefix of the user key.

The property drives the pure Python mirror of ``locals.tf``
(``workshop_flatten``): each example builds a Hypothesis-generated
``workshop_accounts`` map over unique 12-digit account ids and uniquely-named
groups, derives ``users`` and ``user_account_id``, and asserts both agree with
the owning account independently derivable from the ``"<account_id>:<group>:<NN>"``
key prefix. A regression that resolved a user to a sibling account, dropped the
``account_id`` from the manifest entry, or let the two tables disagree fails here.

Harness note: ``workshop_flatten`` lives under ``tests/`` and is importable via
the shared conftest ``sys.path`` shim (``tests/`` is on the path), mirroring how
the sibling property tests (Property 1) import their helpers.
"""

from __future__ import annotations

import workshop_flatten as wf
from hypothesis import given, settings
from hypothesis import strategies as st

# Account ids are 12-digit AWS account numbers (the workshop_accounts validation
# enforces ``^[0-9]{12}$``). Drawing them unique per map makes every account
# distinguishable, so a user resolved to the wrong account's id is caught.
_account_ids = st.text(alphabet="0123456789", min_size=12, max_size=12)

# Group names are non-empty strings (non-empty after trimspace). Exclude ':'
# because the flatten key is "<account_id>:<group>:<NN>" and a ':' in a group
# name would make the account prefix split ambiguous — the group names in
# practice are slugs, and this test derives the owning account from that split.
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
# validation bound). Keep the upper draw modest so maps stay cheap to flatten
# while still exercising multi-user groups and the 0-user (no participants) edge.
_group_cfg = st.builds(
    lambda n: {"user_count": n}, st.integers(min_value=0, max_value=12)
)

# Workshop ids are slugs (1-63 lowercase alphanumeric + hyphens). The username
# embeds the id, but Property 5 is about account resolution, not the username,
# so a simple fixed-shape slug keeps the generated input valid without noise.
_workshop_ids = st.from_regex(r"\A[a-z0-9](-?[a-z0-9]){0,20}\Z", fullmatch=True)


@st.composite
def _workshop_accounts(draw):
    """A valid ``workshop_accounts`` map: unique 12-digit accounts, each with
    one or more uniquely-named groups.

    Builds between 1 and 4 accounts (all distinct ids) and, under each, a
    non-empty map of 1..5 uniquely-named groups, so the map spans several
    accounts and the resolution of a user to its own account (vs. a sibling)
    is a real distinction to check.
    """
    account_ids = draw(st.lists(_account_ids, min_size=1, max_size=4, unique=True))
    accounts = {}
    for acct in account_ids:
        group_names = draw(st.lists(_group_names, min_size=1, max_size=5, unique=True))
        accounts[acct] = {
            "groups": {gname: draw(_group_cfg) for gname in group_names}
        }
    return accounts


@settings(max_examples=200, deadline=None)
@given(accounts=_workshop_accounts(), workshop_id=_workshop_ids)
def test_each_participant_account_id_is_its_owning_account(accounts, workshop_id):
    """Every user's account_id — in both tables — is its owning account.

    Feature: multi-workshop-provisioning, Property 5: each participant's
    account_id is its owning account
    Validates: Requirements 4.1, 4.3
    """
    users = wf.users(accounts, workshop_id)
    user_account_id = wf.user_account_id(accounts, workshop_id)

    # The two derivations cover exactly the same participants: the manifest
    # per-user record and the user->account resolution table never disagree on
    # which users exist.
    assert set(user_account_id.keys()) == set(users.keys())

    for uk, record in users.items():
        # The owning account is independently derivable from the key prefix:
        # the flatten key is "<account_id>:<group>:<NN>", so splitting off the
        # first segment yields the account under which the group is nested.
        owning_account = uk.split(":", 1)[0]

        # It must be a real declared account — never a value conjured from
        # elsewhere — and it must carry a group matching the key's group name,
        # confirming the user is nested under that exact account/group.
        assert owning_account in accounts, (
            f"user {uk!r}: key prefix {owning_account!r} is not a declared account"
        )
        group_name = uk.split(":", 2)[1]
        assert group_name in accounts[owning_account]["groups"], (
            f"user {uk!r}: group {group_name!r} is not under account "
            f"{owning_account!r}"
        )

        # R4.1: the user->group->owning-account resolution table resolves this
        # participant to that owning account.
        assert user_account_id[uk] == owning_account, (
            f"user {uk!r}: user_account_id {user_account_id[uk]!r} != owning "
            f"account {owning_account!r}"
        )

        # R4.3: the per-user account_id threaded into the manifest entry is the
        # same owning account — the manifest never loses or disagrees with it.
        assert record["account_id"] == owning_account, (
            f"user {uk!r}: manifest account_id {record['account_id']!r} != "
            f"owning account {owning_account!r}"
        )

        # The two tables agree with each other (and so with the group record),
        # so no user is split across two different account ids.
        assert user_account_id[uk] == record["account_id"]
        assert record["group_key"] == wf.group_key(owning_account, group_name)
