"""Property 10: isolation diff flags any removal or modification.

Feature: multi-workshop-provisioning, Property 10: isolation diff flags any
removal or modification of another workshop's resources
Validates: Requirements 10.5, 10.6

Property 10: *For any* pair of resource snapshots ``(before, after)`` of another
workshop, ``diff_snapshots`` SHALL report an empty result when the two snapshots
are equal, and SHALL report every removed or modified resource (and only those)
when they differ, so a destroy that touches another workshop is always detected
(R10.5, R10.6). Additions to the bystander workshop are NOT a violation and are
never reported.

The subject is the pure core ``scripts/verify_isolation.diff_snapshots`` created
by task 9.1 — no AWS, no I/O. A snapshot is a dict of category
(``groups`` / ``users`` / ``account_assignments`` / ``claim``) to a map of
``resource_key -> hashable value``.

Two properties are checked over Hypothesis-generated snapshots:

1. **Reflexive / equal:** ``diff_snapshots(s, s) == []`` for any snapshot ``s``.
2. **Mutation:** from a base snapshot, independently derive ``after`` by removing
   a subset of resources, modifying a subset (each to a genuinely different
   value), and adding fresh ones. The expected finding set — one entry per
   removed or modified resource, nothing for additions or unchanged ones — is
   computed independently of the function under test, then matched against
   ``diff_snapshots``'s output.

Harness note: the repo-root ``scripts/`` dir is not on the shared conftest
``sys.path`` shim (which exposes ``tests/`` and ``subscription/scripts/``), so
this module appends it before importing the subject.
"""

from __future__ import annotations

import sys
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

# scripts/ (repo root) holds verify_isolation.py; the shared conftest shim does
# not cover it, so add it here. Additive, mirroring the conftest convention.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from verify_isolation import diff_snapshots

# The snapshot categories build_snapshot emits (verify_isolation.build_snapshot).
_CATEGORIES = ("groups", "users", "account_assignments", "claim")

# Resource keys and values: short, hashable, and comparable. Values are the
# "stable value" diff_snapshots compares with ``!=``; strings and small ints
# cover both identity and change detection without over-generating.
_keys = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789:-", min_size=1, max_size=8
)
_values = st.one_of(
    st.text(max_size=12),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
)


@st.composite
def _snapshots(draw):
    """Generate a snapshot: category -> {resource_key -> hashable value}.

    Every category is present (as build_snapshot always emits all four), each
    an independently-generated dict so keys may collide across categories — the
    diff treats ``category: key`` as the unit, so a key reused in two categories
    is two distinct resources.
    """
    return {
        category: draw(st.dictionaries(_keys, _values, max_size=6))
        for category in _CATEGORIES
    }


@settings(max_examples=200, deadline=None)
@given(snapshot=_snapshots())
def test_equal_snapshots_report_no_findings(snapshot):
    """diff_snapshots(s, s) == [] for any snapshot s (R10.6).

    Feature: multi-workshop-provisioning, Property 10: isolation diff flags any
    removal or modification of another workshop's resources
    Validates: Requirements 10.5, 10.6
    """
    # Reflexive against the same object and against an independent deep copy, so
    # the empty result is about value-equality, not object identity.
    copy = {category: dict(items) for category, items in snapshot.items()}
    assert diff_snapshots(snapshot, snapshot) == []
    assert diff_snapshots(snapshot, copy) == []


@st.composite
def _before_and_mutation(draw):
    """Generate (before, after, expected) where after is a mutation of before.

    ``after`` is derived from ``before`` by independently choosing, per existing
    resource, to keep / remove / modify it, plus adding fresh resources. The
    expected finding set is built here from those choices alone — never by
    calling the function under test — so the assertion is a genuine oracle.
    """
    before = draw(_snapshots())

    after: dict[str, dict] = {category: {} for category in _CATEGORIES}
    expected: set[str] = set()

    for category, items in before.items():
        for key, value in items.items():
            action = draw(st.sampled_from(("keep", "remove", "modify")))
            if action == "keep":
                after[category][key] = value
            elif action == "remove":
                # Dropped from ``after`` -> a removal finding.
                expected.add(f"{category}: {key} was removed")
            else:  # modify
                # Draw a value guaranteed different from the original, so the
                # change is genuine and must be flagged.
                new_value = draw(_values.filter(lambda v, _v=value: v != _v))
                after[category][key] = new_value
                expected.add(f"{category}: {key} was modified")

        # Add fresh resources under keys not present in ``before`` for this
        # category. Additions must NOT be flagged (isolation only cares about
        # removals/modifications).
        additions = draw(st.dictionaries(_keys, _values, max_size=4))
        for key, value in additions.items():
            if key not in items:
                after[category][key] = value

    return before, after, expected


@settings(max_examples=200, deadline=None)
@given(data=_before_and_mutation())
def test_diff_reports_exactly_removed_and_modified(data):
    """Every removed/modified resource is reported; additions are not (R10.5/6).

    Feature: multi-workshop-provisioning, Property 10: isolation diff flags any
    removal or modification of another workshop's resources
    Validates: Requirements 10.5, 10.6
    """
    before, after, expected = data

    findings = diff_snapshots(before, after)

    # 1. The finding set matches the independently-computed oracle exactly: no
    #    removed/modified resource is missed, and nothing extra (no addition,
    #    no unchanged resource) is reported.
    assert set(findings) == expected

    # 2. Each resource is reported at most once (one finding per resource).
    assert len(findings) == len(set(findings))
    assert len(findings) == len(expected)

    # 3. Deterministic, sorted output: calling again yields byte-identical
    #    results, and findings come back in sorted order.
    assert diff_snapshots(before, after) == findings
    assert findings == sorted(findings)

    # 4. No addition is ever reported: every finding names a key that existed in
    #    ``before`` (removals/modifications only, never a brand-new key).
    for category in _CATEGORIES:
        for key in after[category]:
            if key not in before.get(category, {}):
                assert f"{category}: {key} was removed" not in findings
                assert f"{category}: {key} was modified" not in findings
