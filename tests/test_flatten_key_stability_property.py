"""Property 3: flatten keys are deterministic and locally stable.

Feature: multi-workshop-provisioning, Property 3: flatten keys are deterministic
and locally stable
Validates: Requirements 3.7

Property 3: *For any* valid ``workshop_accounts`` map, the flatten derives its
keyed maps (users/groups/memberships/group_account) from the account id, group
name, and per-group user index only — never from a global running counter — so
the derivation has two invariants (R3.7):

1. **Determinism.** Flattening the same input twice yields byte-identical keys
   *and* values. A re-run (``tofu plan`` after no change) produces the same keys,
   so OpenTofu sees no churn.

2. **Local stability.** A mutation confined to one account X — adding, removing,
   or changing a group, or changing a group's ``user_count`` under X — leaves the
   keys of every *other* account byte-identical. Because keys embed their owning
   account id, a change under X can never shift the key of a user/group/
   membership that lives under a different account, so OpenTofu does not
   recreate unrelated users/groups/memberships on an unrelated change.

Both invariants are checked against the pure Python mirror of ``locals.tf``
(``workshop_flatten``) over Hypothesis-generated valid ``workshop_accounts``
maps. A regression that keyed by a flat global sequence — where inserting a
group under X renumbers everything after it — fails the local-stability check.

Harness note: ``workshop_flatten`` lives under ``tests/`` and is importable via
the shared conftest ``sys.path`` shim, mirroring the sibling property tests.
"""

from __future__ import annotations

import copy

import workshop_flatten as wf
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# A fixed, valid workshop_id slug — this property is about the derivation keys,
# which do not depend on the slug value, so one representative slug suffices.
_WORKSHOP_ID = "kiro-2025-10-10"

# Account ids are 12-digit AWS account numbers (workshop_accounts enforces
# ``^[0-9]{12}$``). Unique ids per map keep accounts distinguishable so a
# cross-account key leak is unambiguously caught.
_account_ids = st.text(alphabet="0123456789", min_size=12, max_size=12)

# Group names are non-empty; exclude ':' because the flatten key is
# "<account_id>:<group>" and a ':' would make the key ambiguous (same reasoning
# as the sibling Property 1 generator).
_group_names = st.text(
    alphabet=st.characters(
        min_codepoint=0x21,
        max_codepoint=0x7E,
        blacklist_characters=":",
    ),
    min_size=1,
    max_size=24,
).filter(lambda s: s.strip() != "")

# user_count in the inclusive validation range 0..500. Cap at 50 here to keep
# the generated maps cheap to flatten across 200 examples while still exercising
# multi-user groups and the zero-user edge.
_group_cfg = st.builds(
    lambda n: {"user_count": n}, st.integers(min_value=0, max_value=50)
)


@st.composite
def _workshop_accounts(draw, min_accounts=1, max_accounts=4):
    """A valid ``workshop_accounts`` map: unique 12-digit accounts, each with
    one or more uniquely-named groups."""
    account_ids = draw(
        st.lists(
            _account_ids,
            min_size=min_accounts,
            max_size=max_accounts,
            unique=True,
        )
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


def _all_derived(accounts):
    """All four keyed derivations, as a dict of name -> derived map.

    Collecting them together lets the asserts compare keys *and* values for the
    whole flatten in one place.
    """
    return {
        "group_account": wf.group_account(accounts),
        "groups": wf.groups(accounts),
        "users": wf.users(accounts, _WORKSHOP_ID),
        "memberships": wf.memberships(accounts, _WORKSHOP_ID),
    }


@settings(max_examples=200, deadline=None)
@given(accounts=_workshop_accounts())
def test_flatten_is_deterministic(accounts):
    """Flattening the same input twice is byte-identical (keys and values).

    Feature: multi-workshop-provisioning, Property 3: flatten keys are
    deterministic and locally stable
    Validates: Requirements 3.7
    """
    first = _all_derived(accounts)
    # A deep copy of the input guarantees the second flatten shares no mutable
    # state with the first — determinism, not accidental aliasing.
    second = _all_derived(copy.deepcopy(accounts))

    for name in first:
        # Keys identical, in the same set.
        assert first[name].keys() == second[name].keys(), (
            f"{name}: key sets differ between runs"
        )
        # Values identical byte-for-byte.
        assert first[name] == second[name], (
            f"{name}: values differ between runs"
        )


@st.composite
def _accounts_and_mutation(draw):
    """A valid map with >= 2 accounts, plus a mutation confined to one account.

    Returns ``(accounts, target, mutated)`` where ``target`` is the account id
    the mutation touches and ``mutated`` is a fresh map identical to ``accounts``
    except under ``target``. The three mutation kinds — add a group, remove a
    group, change a group's ``user_count`` — exercise the three ways a single
    account's sub-map can change (R3.7).
    """
    accounts = draw(_workshop_accounts(min_accounts=2, max_accounts=4))
    target = draw(st.sampled_from(sorted(accounts.keys())))
    mutated = copy.deepcopy(accounts)
    target_groups = mutated[target]["groups"]

    kind = draw(st.sampled_from(["add", "remove", "change"]))

    if kind == "add":
        # Add a brand-new group under the target (name not already present).
        new_name = draw(
            _group_names.filter(lambda g: g not in target_groups)
        )
        target_groups[new_name] = draw(_group_cfg)
    elif kind == "remove":
        # Removing requires more than one group so the account stays non-empty
        # (the generator guarantees >= 1 group; need >= 2 to remove one).
        assume(len(target_groups) >= 2)
        victim = draw(st.sampled_from(sorted(target_groups.keys())))
        del target_groups[victim]
    else:  # change
        victim = draw(st.sampled_from(sorted(target_groups.keys())))
        old = target_groups[victim]["user_count"]
        # Pick a genuinely different user_count so the mutation is observable.
        new_count = draw(
            st.integers(min_value=0, max_value=50).filter(lambda n: n != old)
        )
        target_groups[victim] = {"user_count": new_count}

    return accounts, target, mutated


@settings(max_examples=200, deadline=None)
@given(data=_accounts_and_mutation())
def test_mutation_in_one_account_leaves_other_accounts_keys_stable(data):
    """A mutation confined to account X leaves every other account's keys
    byte-identical across all four derivations.

    Feature: multi-workshop-provisioning, Property 3: flatten keys are
    deterministic and locally stable
    Validates: Requirements 3.7
    """
    accounts, target, mutated = data

    before = _all_derived(accounts)
    after = _all_derived(mutated)

    other_accounts = [a for a in accounts if a != target]
    # There is at least one other account (the generator draws >= 2).
    assert other_accounts

    def _keys_for(account_id, derived_map):
        # Every key in every derivation is of the form "<account_id>:..." —
        # the owning account is the prefix before the first ':'.
        return {k for k in derived_map if k.split(":", 1)[0] == account_id}

    for name in before:
        for account_id in other_accounts:
            before_keys = _keys_for(account_id, before[name])
            after_keys = _keys_for(account_id, after[name])
            assert before_keys == after_keys, (
                f"{name}: keys for untouched account {account_id} changed "
                f"after mutating {target}"
            )
            # And the values under those keys are byte-identical too — not just
            # the key set but the whole derived record for other accounts.
            for k in before_keys:
                assert before[name][k] == after[name][k], (
                    f"{name}: value at {k!r} (account {account_id}) changed "
                    f"after mutating {target}"
                )
