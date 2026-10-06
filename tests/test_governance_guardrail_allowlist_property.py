"""Property 1: guardrail renders exactly the supplied allowlist.

Feature: workshop-account-governance, Property 1: Guardrail renders exactly the
supplied allowlist
Validates: Requirements 4.3, 4.4

Property 1: *For any* non-empty ``var.kiro_allowed_actions`` list, the rendered
Kiro guardrail SCP (``aws_organizations_policy.kiro_guardrail.content``) is a
single ``Allow`` statement whose action set equals EXACTLY the supplied
allowlist — nothing added, nothing dropped — scoped to ``Resource = "*"``, with
no ``Deny`` and no second statement. So the guardrail grants precisely the
configured actions and nothing outside them.

Why a rendered plan, not a text scan. The guardrail is built by
``data.aws_iam_policy_document.kiro_guardrail`` feeding the policy ``content``;
the only faithful way to assert the *rendered* document over varied inputs is to
plan the stack and read ``tofu show -json``. A regression that appended a
default action, deduplicated/reordered in a lossy way, split into multiple
statements, or flipped the effect fails here.

Offline harness. The guardrail document renders fully at plan time (``content``
is a known value), and the harness (``governance_guardrail_plan``) swaps in a
credential-free provider backed by a mock STS and drops the live-only account
placement — so the plan needs no AWS credentials or network, mirroring the
sibling Property 2/3 suites. No ``tofu apply`` ever runs. The tofu-backed test
skips cleanly when no ``tofu`` binary is on PATH.
"""

from __future__ import annotations

import governance_guardrail_plan as gov
import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.skipif(
    not gov.tofu_available(),
    reason="tofu binary not on PATH; plan-backed Property 1 render unavailable",
)

# IAM action tokens like "service:Operation" or "service:*". A conservative
# alphabet keeps the rendered JSON unambiguous; the property is about set
# equality of the rendered actions, not the exact token text.
_service = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
    min_size=1,
    max_size=12,
).filter(lambda s: s.strip() != "")
_operation = st.one_of(
    st.just("*"),
    st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        min_size=1,
        max_size=16,
    ),
)
_action = st.builds(lambda s, o: f"{s}:{o}", _service, _operation)

# A non-empty allowlist of DISTINCT actions (the stack passes the list straight
# through; uniqueness keeps a dropped/duplicated entry unambiguous in failure
# output).
_allowlists = st.lists(_action, min_size=1, max_size=8, unique=True)


def _assert_single_allow_equals(document: dict, expected_actions: list[str]) -> None:
    """Assert the SCP is one Allow over exactly ``expected_actions`` on ``*``."""
    statements = document.get("Statement")
    # A single-statement document may render Statement as a dict, not a list.
    if isinstance(statements, dict):
        statements = [statements]
    assert isinstance(statements, list) and len(statements) == 1, (
        f"guardrail must have exactly one statement; got {statements!r}"
    )

    stmt = statements[0]
    assert stmt.get("Effect") == "Allow", (
        f"guardrail statement must be an Allow; got Effect={stmt.get('Effect')!r}"
    )

    actions = stmt.get("Action")
    # IAM renders a single-element Action as a bare string, not a list.
    if isinstance(actions, str):
        actions = [actions]
    assert set(actions) == set(expected_actions), (
        f"guardrail action set {sorted(set(actions))} != supplied allowlist "
        f"{sorted(set(expected_actions))}"
    )

    resource = stmt.get("Resource")
    if isinstance(resource, list):
        resource = resource[0] if len(resource) == 1 else resource
    assert resource == "*", (
        f"guardrail must grant on Resource '*'; got {resource!r}"
    )


@settings(
    max_examples=8,  # each example runs a real tofu plan (~6s after a one-time init)
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
# Representative shapes always exercised: a single action, a wildcard-only
# action, and a mix mirroring the stack's default starter allowlist.
@example(allowed_actions=["sts:GetCallerIdentity"])
@example(allowed_actions=["sso:*"])
@example(allowed_actions=["sso:*", "identitystore:*", "sts:GetCallerIdentity", "q:*"])
@given(allowed_actions=_allowlists)
def test_guardrail_renders_exactly_the_allowlist(allowed_actions):
    """The guardrail SCP is a single Allow equal to the supplied allowlist.

    Feature: workshop-account-governance, Property 1: Guardrail renders exactly
    the supplied allowlist
    Validates: Requirements 4.3, 4.4
    """
    document = gov.plan_guardrail_document(allowed_actions)

    # Single Allow, action set == input, Resource "*", no extra statement.
    _assert_single_allow_equals(document, allowed_actions)

    # Nothing outside the allowlist is granted, and nothing is denied by this
    # policy (allowlist semantics — the SCP boundary does the implicit denying).
    statements = document.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]
    for stmt in statements:
        assert stmt.get("Effect") != "Deny", (
            f"guardrail must contain no Deny statement; got {stmt!r}"
        )
