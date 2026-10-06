"""Property 4: flattened maps match the shapes the for_each resources consume.

Feature: multi-workshop-provisioning, Property 4: flattened maps match the
shapes the for_each resources consume
Validates: Requirements 3.4, 3.5

Property 4: *For any* valid ``workshop_accounts`` map, the flatten emits the
exact value shapes the existing ``aws_identitystore_user`` /
``aws_identitystore_group`` / ``aws_identitystore_group_membership`` ``for_each``
resources consume (R3.4) — so the resources keep working unchanged (R3.5):

- every ``local.users[k]`` carries exactly the baseline fields the user resource
  reads (``username``, ``email``, ``display_name``, ``given_name``,
  ``family_name``) plus the ``group_key`` and ``account_id`` the membership and
  manifest derivation read — no field missing, none extra;
- every ``local.groups[gk]`` is exactly ``{ name }`` — the sole attribute the
  group resource reads;
- every ``local.memberships[k]`` is exactly ``{ user_key, group_key }`` whose
  ``user_key`` points at an existing ``users`` entry and whose ``group_key``
  points at an existing ``groups`` entry, so no membership dangles.

The property drives the pure Python mirror of ``locals.tf``
(``workshop_flatten``): each example builds a Hypothesis-generated
``workshop_accounts`` map and a valid ``workshop_id``, derives the three maps,
and asserts their key sets and value shapes. A regression that dropped a baseline
field, added a stray attribute to ``groups``, or emitted a membership referencing
a non-existent user or group fails here.

Harness note: ``workshop_flatten`` lives under ``tests/`` and is importable via
the shared conftest ``sys.path`` shim (``tests/`` is on the path), mirroring the
sibling property tests (e.g. ``test_group_account_assignment_property.py``).
"""

from __future__ import annotations

import workshop_flatten as wf
from hypothesis import given, settings
from hypothesis import strategies as st

# The exact baseline field set each ``local.users[k]`` record carries: the five
# attributes the ``aws_identitystore_user`` resource reads
# (username/email/display_name/given_name/family_name) plus the group_key and
# account_id the membership and manifest derivation read. The shape check below
# asserts equality against this set, so both a dropped field and a stray extra
# field are caught.
_USER_FIELDS = frozenset(
    {
        "username",
        "email",
        "display_name",
        "given_name",
        "family_name",
        "group_key",
        "account_id",
    }
)

# Account ids are 12-digit AWS account numbers (``^[0-9]{12}$``). Drawing them
# unique per map keeps each account distinguishable, mirroring the sibling test.
_account_ids = st.text(alphabet="0123456789", min_size=12, max_size=12)

# Group names are non-empty strings. Exclude ':' because the flatten key is
# "<account_id>:<group>[:<NN>]" and a ':' would make the key ambiguous — the HCL
# group names are slugs in practice.
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
# validation bound). Keep the upper bound modest here so examples stay small and
# fast while still exercising groups with zero users (which emit no users /
# memberships) and groups with several.
_group_cfg = st.builds(
    lambda n: {"user_count": n}, st.integers(min_value=0, max_value=8)
)

# A valid ``workshop_id`` slug: 1-63 lowercase alphanumeric + hyphens, begin/end
# alphanumeric, no consecutive hyphens. The username derivation embeds it, but
# Property 4 only checks shapes, so any valid slug keeps the input realistic.
_workshop_ids = st.from_regex(
    r"\A[a-z0-9](-?[a-z0-9])*\Z", fullmatch=True
).filter(lambda s: 1 <= len(s) <= 63)


@st.composite
def _workshop_accounts(draw):
    """A valid ``workshop_accounts`` map: unique 12-digit accounts, each with
    one or more uniquely-named groups.

    Builds between 1 and 4 accounts (all distinct ids) and, under each, a
    non-empty map of 1..5 uniquely-named groups, mirroring the sibling test's
    generator so the two properties exercise the same input space.
    """
    account_ids = draw(st.lists(_account_ids, min_size=1, max_size=4, unique=True))
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
@given(accounts=_workshop_accounts(), workshop_id=_workshop_ids)
def test_flattened_maps_match_for_each_value_shapes(accounts, workshop_id):
    """The flattened users/groups/memberships maps carry exactly the shapes the
    ``for_each`` resources consume.

    Feature: multi-workshop-provisioning, Property 4: flattened maps match the
    shapes the for_each resources consume
    Validates: Requirements 3.4, 3.5
    """
    users = wf.users(accounts, workshop_id)
    groups = wf.groups(accounts)
    memberships = wf.memberships(accounts, workshop_id)

    # groups: every entry is exactly { name }, and that name is a declared group
    # name under the account the key's prefix identifies. The group resource
    # reads only `name`, so any extra attribute would break the shape contract.
    for gk, g in groups.items():
        assert set(g.keys()) == {"name"}, (
            f"groups[{gk!r}] has fields {sorted(g.keys())}, expected only 'name'"
        )
        account_id, gname = gk.split(":", 1)
        assert account_id in accounts, (
            f"groups[{gk!r}] prefix {account_id!r} is not a declared account"
        )
        assert gname in accounts[account_id]["groups"], (
            f"groups[{gk!r}] name {gname!r} is not a declared group"
        )
        assert g["name"] == gname

    # users: every entry carries exactly the baseline field set — no field
    # missing, none extra — and its group_key / account_id reference declared
    # entries (group_key is a key in `groups`; account_id is a declared account).
    for uk, u in users.items():
        assert set(u.keys()) == set(_USER_FIELDS), (
            f"users[{uk!r}] has fields {sorted(u.keys())}, "
            f"expected {sorted(_USER_FIELDS)}"
        )
        assert u["group_key"] in groups, (
            f"users[{uk!r}].group_key {u['group_key']!r} is not an existing "
            f"groups entry"
        )
        assert u["account_id"] in accounts, (
            f"users[{uk!r}].account_id {u['account_id']!r} is not a declared "
            f"account"
        )
        # The user's group_key and account_id agree: the key's account prefix is
        # the user's account, keeping the user->group->account chain consistent.
        assert u["group_key"].split(":", 1)[0] == u["account_id"]

    # memberships: every entry is exactly { user_key, group_key }, keyed by the
    # user's own key, with user_key referencing an existing users entry and
    # group_key referencing an existing groups entry — no dangling membership.
    for mk, m in memberships.items():
        assert set(m.keys()) == {"user_key", "group_key"}, (
            f"memberships[{mk!r}] has fields {sorted(m.keys())}, "
            f"expected 'user_key' and 'group_key'"
        )
        assert m["user_key"] == mk, (
            f"memberships[{mk!r}] user_key {m['user_key']!r} != its own key"
        )
        assert m["user_key"] in users, (
            f"memberships[{mk!r}].user_key {m['user_key']!r} is not an existing "
            f"users entry"
        )
        assert m["group_key"] in groups, (
            f"memberships[{mk!r}].group_key {m['group_key']!r} is not an "
            f"existing groups entry"
        )
        # The membership places the user in that user's own group (R3.6 shape):
        # its group_key equals the referenced user's group_key.
        assert m["group_key"] == users[m["user_key"]]["group_key"]

    # Cross-map consistency: one membership per user, keyed identically, so the
    # membership resource's for_each covers exactly the users the user resource
    # creates — the invariant the shared for_each key contract depends on.
    assert set(memberships.keys()) == set(users.keys())
