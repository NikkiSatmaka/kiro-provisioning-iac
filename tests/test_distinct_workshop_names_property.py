"""Property 6: distinct workshop_ids yield fully distinct names and state keys.

Feature: multi-workshop-provisioning, Property 6: distinct workshop_ids yield
fully distinct claim names and state keys
Validates: Requirements 7.3, 7.5, 9.3

Property 6: *For any* two DISTINCT valid ``workshop_id`` slugs ``wid_a`` and
``wid_b`` (``wid_a != wid_b``), the full set of claim-service resource names
derived from each — the DynamoDB table name, the Lambda function name, the IAM
role name, and the inline table-access policy name — together with that
workshop's two Terraform state keys (subscription and claim-service) share NO
value between the two workshops. Because every one of those strings embeds the
exact ``workshop_id`` (``credential-claim-<id>`` and
``workshops/<id>/<stack>/terraform.tfstate``), two different ids can never
collide on a table, Lambda, Function URL, role, policy, or state key — the
isolation guarantee of "one claim service per workshop" (R7.3, R7.5, R9.3).

The property is checked against the pure Python mirror of the HCL
``local.name`` derivation and the mise state-key scheme (``workshop_names``) over
Hypothesis-generated pairs of distinct valid slugs. A regression that namespaced
by anything coarser than the full ``workshop_id`` — or dropped the id from any
single derived name or state key — would let two workshops share that value and
fail this test.

Harness note: ``workshop_names`` lives under ``tests/`` and is importable via the
shared conftest ``sys.path`` shim, mirroring the sibling property tests.
"""

from __future__ import annotations

import workshop_names as wn
from hypothesis import given, settings
from hypothesis import strategies as st

# Valid workshop_id slugs: 1-63 lowercase alphanumeric + hyphens, begin/end
# alphanumeric, no consecutive hyphens. The regex ``[a-z0-9](-?[a-z0-9])*``
# enforces the no-leading/trailing/double-hyphen grammar; the length filter caps
# at 63. Mirrors the slug strategy the sibling renderer property tests use.
_workshop_ids = st.from_regex(
    r"\A[a-z0-9](-?[a-z0-9])*\Z", fullmatch=True
).filter(lambda s: 1 <= len(s) <= 63)


@settings(max_examples=200)
@given(wid_a=_workshop_ids, wid_b=_workshop_ids)
def test_distinct_workshop_ids_share_no_derived_value(
    wid_a: str, wid_b: str
) -> None:
    """Two distinct slugs share no derived name or state key."""
    # Property 6 is only meaningful for a DISTINCT pair; skip the diagonal.
    if wid_a == wid_b:
        return

    values_a = set(wn.derived_values(wid_a))
    values_b = set(wn.derived_values(wid_b))

    # The full set for A and the full set for B are disjoint: no table, Lambda,
    # role, policy, or state key is shared between the two workshops (R7.3/9.3).
    overlap = values_a & values_b
    assert overlap == set(), (
        f"workshop_ids {wid_a!r} and {wid_b!r} share derived value(s): "
        f"{sorted(overlap)}"
    )


@settings(max_examples=200)
@given(wid_a=_workshop_ids, wid_b=_workshop_ids)
def test_each_derived_slot_differs_between_distinct_ids(
    wid_a: str, wid_b: str
) -> None:
    """Each derived slot (table/lambda/role/policy + both keys) differs.

    Stronger than set-disjointness: it pins that the *same slot* never matches
    across two distinct ids, so no single resource category can collide even if
    some other slot happened to differ.
    """
    if wid_a == wid_b:
        return

    assert wn.table_name(wid_a) != wn.table_name(wid_b)
    assert wn.lambda_name(wid_a) != wn.lambda_name(wid_b)
    assert wn.role_name(wid_a) != wn.role_name(wid_b)
    assert wn.policy_name(wid_a) != wn.policy_name(wid_b)
    for stack in wn.STACKS:
        assert wn.state_key(wid_a, stack) != wn.state_key(wid_b, stack)


def test_derived_values_shape_for_a_sample_id() -> None:
    """A concrete sample pins the exact derived strings (R7.5/9.3)."""
    wid = "kiro-2025-10-10"
    assert wn.table_name(wid) == "credential-claim-kiro-2025-10-10"
    assert wn.lambda_name(wid) == "credential-claim-kiro-2025-10-10"
    assert wn.role_name(wid) == "credential-claim-kiro-2025-10-10-lambda"
    assert (
        wn.policy_name(wid) == "credential-claim-kiro-2025-10-10-table-access"
    )
    assert (
        wn.state_key(wid, "subscription")
        == "workshops/kiro-2025-10-10/subscription/terraform.tfstate"
    )
    assert (
        wn.state_key(wid, "claim-service")
        == "workshops/kiro-2025-10-10/claim-service/terraform.tfstate"
    )
    # The two state keys differ only in the stack segment.
    assert wn.state_key(wid, "subscription") != wn.state_key(
        wid, "claim-service"
    )
