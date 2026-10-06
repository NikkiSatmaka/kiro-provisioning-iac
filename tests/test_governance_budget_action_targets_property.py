"""Property 2: each budget action freezes only its own account.

Feature: workshop-account-governance, Property 2: Each budget action freezes
only its own account
Validates: Requirements 7.4, 7.5

Property 2: *For any* set of supplied ``account_ids``, every generated
``aws_budgets_budget_action.freeze`` instance's
``scp_action_definition.target_ids`` equals exactly the singleton list of its
OWN account id — never the workshop OU id, never another account's id — and
every action references the freeze policy (``aws_organizations_policy.freeze``)
and the budgets execution role (``aws_iam_role.budgets_execution``).

How it is exercised: ``aws_budgets_budget_action`` references ids/arns known
only after apply (the freeze policy id, the role arn, the budget name), so a
full offline render is harder than a pure value check. ``target_ids =
[each.key]`` is nonetheless a KNOWN value at plan time (a literal off the
``for_each`` key), so we render ``governance/terraform`` with ``tofu plan`` over
a multi-account set and read the planned ``target_ids`` per instance directly;
the still-unknown ``policy_id`` / ``execution_role_arn`` are asserted via the
plan's config-level reference expressions (which name the freeze policy and the
role). See ``governance_budget_action_plan`` for the harness.

Harness note: ``governance_budget_action_plan`` lives under ``tests/`` and is
importable via the shared conftest ``sys.path`` shim, mirroring the sibling
property tests. The tofu-backed test skips cleanly when no ``tofu`` binary is on
PATH.
"""

from __future__ import annotations

import governance_budget_action_plan as gov
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.skipif(
    not gov.tofu_available(),
    reason="tofu binary not on PATH; plan-backed Property 2 render unavailable",
)

# A 12-digit AWS account id. Avoid a leading zero only to keep the ids visually
# distinct in failure output; the stack treats them purely as opaque strings.
_account_id = st.integers(min_value=10 ** 11, max_value=10 ** 12 - 1).map(str)

# A multi-account set: 2..5 DISTINCT ids (a set, mirroring toset(var.account_ids)
# in the stack). Multi-account is the point of the property — one account's
# action must never carry another account's id or the OU.
_account_sets = st.lists(_account_id, min_size=2, max_size=5, unique=True)

# The OU id a buggy action might wrongly target instead of the single account.
# The stub harness names the OU workshop-<id>; a plan never yields a concrete
# r-/ou- id for it, but we still assert no target_ids entry is anything other
# than the instance's own account — covering an OU id, a parent id, or a sibling.
_FORBIDDEN_NON_ACCOUNT_TOKENS = ("r-", "ou-", "workshop-")


@settings(
    max_examples=8,  # each example runs a real tofu plan (~6s after a one-time init)
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(account_ids=_account_sets)
def test_each_action_targets_only_its_own_account(account_ids):
    """Every freeze action targets exactly its own account, nothing else.

    Feature: workshop-account-governance, Property 2: Each budget action freezes
    only its own account
    Validates: Requirements 7.4, 7.5
    """
    rendered = gov.plan_budget_action_targets(account_ids)

    # One action per supplied account — no account dropped, none invented.
    assert set(rendered.keys()) == set(account_ids), (
        f"freeze actions keyed {sorted(rendered)}, expected {sorted(set(account_ids))}"
    )

    for account_id, facts in rendered.items():
        target_ids = facts["target_ids"]

        # 1. target_ids is EXACTLY the singleton of this account id — never the
        #    OU, never another account (Requirement 7.4).
        assert target_ids == [account_id], (
            f"action for {account_id} has target_ids {target_ids!r}, "
            f"expected exactly [{account_id!r}]"
        )

        # 2. Belt-and-braces: nothing in target_ids looks like an OU/root/parent
        #    token — so a regression that pointed at the OU is caught even if the
        #    OU id ever became a concrete plan value.
        for tok in target_ids:
            assert not tok.startswith(_FORBIDDEN_NON_ACCOUNT_TOKENS), (
                f"action for {account_id} targets non-account id {tok!r}"
            )
            assert tok in account_ids, (
                f"action for {account_id} targets {tok!r}, not a supplied account"
            )

        # 3. The action references the freeze policy and the execution role —
        #    the planned values are known-after-apply, so their presence as refs
        #    is confirmed from the planned resource (Requirement 7.5 wiring).
        assert facts["references_freeze_policy"], (
            f"action for {account_id} does not reference the freeze policy id"
        )
        assert facts["references_execution_role"], (
            f"action for {account_id} does not reference the execution role arn"
        )

    # 4. Config-level wiring (shared by the for_each block): policy_id points at
    #    the FREEZE policy, execution_role_arn at the budgets execution role, and
    #    target_ids is each.key (so every instance targets its own account).
    any_facts = next(iter(rendered.values()))
    assert "aws_organizations_policy.freeze" in " ".join(
        any_facts["policy_id_references"]
    ), (
        "scp_action_definition.policy_id does not reference "
        f"aws_organizations_policy.freeze; got {any_facts['policy_id_references']!r}"
    )
    assert "aws_iam_role.budgets_execution" in " ".join(
        any_facts["role_references"]
    ), (
        "execution_role_arn does not reference aws_iam_role.budgets_execution; "
        f"got {any_facts['role_references']!r}"
    )
    assert any_facts["target_ids_references"] == ["each.key"], (
        "scp_action_definition.target_ids is not [each.key]; "
        f"got {any_facts['target_ids_references']!r}"
    )
