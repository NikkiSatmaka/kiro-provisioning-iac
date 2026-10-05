"""Integration/example tests: workshop_accounts/workshop_id validations,
removed-variable supersession, and the per-user manifest fields.

Feature: multi-workshop-provisioning, Task 3.8
Validates: Requirements 3.1, 3.2, 3.3, 3.8, 3.9, 4.3

Pillar 2 replaces the baseline ``idc_account_map`` and the count/prefix/strategy
generators with two explicit, validated inputs and threads a per-user
``account_id`` through the manifest. This suite pins the config facts that
change proves (tasks 3.1 and 3.3):

* ``workshop_accounts`` is a map keyed by Account_Id whose values hold groups
  with a user count (R3.1), guarded by three validation rules:
    - every key is a 12-digit account id, else reject (R3.8);
    - every group name is non-empty, else reject (R3.9);
    - every ``user_count`` is in the inclusive range 0..500, else reject (R3.2);
  and a well-formed nested map is accepted.
* ``workshop_id`` enforces the slug grammar (1-63 lowercase alphanumeric +
  hyphens, begin/end alphanumeric, no consecutive hyphens).
* Removed-variable supersession: the generators (``user_count``,
  ``group_count``, ``user_prefix``, …) and the baseline ``idc_account_map`` have
  no ``variable`` block anymore, so a tfvars that still sets one references an
  UNDECLARED variable — it fails to resolve rather than silently taking effect
  (R3.3).
* The ``provisioning_manifest`` output carries a per-user ``account_id`` and the
  document-level ``workshop_id`` (R4.3).

Two layers, so the suite is useful with or without a toolchain:

* Static text-fact assertions read the ``.tf`` sources directly and ALWAYS run.
* The ``tofu``-backed assertions evaluate each variable's REAL ``validation``
  condition offline via ``tofu console`` (pure functions — ``can``, ``regex``,
  ``alltrue`` — no backend/provider), and probe a removed variable's
  reference through the console; they skip cleanly when no ``tofu`` binary is on
  PATH.
"""

from __future__ import annotations

import pytest
from _terraform_harness import (
    REMOVED_SUBSCRIPTION_VARS,
    console_reference_resolves,
    full_config_validates,
    read_outputs_tf,
    read_variables_tf,
    tofu_available,
    tofu_validate,
    variable_block,
    variable_declared,
    workshop_accounts_accepts,
    workshop_accounts_rule_accepts,
    workshop_id_accepts,
)

requires_tofu = pytest.mark.skipif(
    not tofu_available(), reason="tofu binary not on PATH"
)

# A well-formed nested account > groups > users map used as the "accept" case.
VALID_ACCOUNTS = {
    "123456789012": {"groups": {"team-a": {"user_count": 3}}},
    "210987654321": {"groups": {"team-b": {"user_count": 0}, "team-c": {"user_count": 500}}},
}


# --- Static schema facts: the nested map input exists (R3.1) ----------------

def test_workshop_accounts_variable_declared_as_nested_map():
    """workshop_accounts is a map of accounts -> groups -> { user_count } (R3.1)."""
    block = variable_block("workshop_accounts")
    assert "map(object(" in block
    assert "groups" in block
    assert "user_count = number" in block


def test_workshop_id_variable_declared():
    """workshop_id exists as a string variable (R3.1 context, slug input)."""
    block = variable_block("workshop_id")
    assert "type        = string" in block or "type = string" in block


# --- tofu-backed: workshop_accounts validation rules (R3.2, R3.8, R3.9) -----

@requires_tofu
def test_workshop_accounts_rejects_non_twelve_digit_account_key():
    """A non-12-digit account key fails the account-id rule (R3.8)."""
    assert (
        workshop_accounts_rule_accepts(
            "12-digit AWS account id",
            {"123": {"groups": {"team": {"user_count": 1}}}},
        )
        is False
    )
    # A 13-digit and a non-numeric key are rejected too.
    assert (
        workshop_accounts_rule_accepts(
            "12-digit AWS account id",
            {"1234567890123": {"groups": {"team": {"user_count": 1}}}},
        )
        is False
    )
    assert (
        workshop_accounts_rule_accepts(
            "12-digit AWS account id",
            {"12345678901x": {"groups": {"team": {"user_count": 1}}}},
        )
        is False
    )


@requires_tofu
def test_workshop_accounts_rejects_empty_group_name():
    """An empty group name fails the non-empty-group rule (R3.9)."""
    assert (
        workshop_accounts_rule_accepts(
            "group name",
            {"123456789012": {"groups": {"": {"user_count": 1}}}},
        )
        is False
    )
    # Whitespace-only is empty after trimming, so it is rejected too.
    assert (
        workshop_accounts_rule_accepts(
            "group name",
            {"123456789012": {"groups": {"   ": {"user_count": 1}}}},
        )
        is False
    )


@requires_tofu
@pytest.mark.parametrize("bad_count", [-1, 501, 1000])
def test_workshop_accounts_rejects_user_count_outside_range(bad_count):
    """A user_count outside 0..500 fails the range rule (R3.2)."""
    assert (
        workshop_accounts_rule_accepts(
            "user_count",
            {"123456789012": {"groups": {"team": {"user_count": bad_count}}}},
        )
        is False
    )


@requires_tofu
@pytest.mark.parametrize("good_count", [0, 1, 250, 500])
def test_workshop_accounts_accepts_user_count_within_range(good_count):
    """A user_count on the inclusive boundary and interior is accepted (R3.2)."""
    assert (
        workshop_accounts_rule_accepts(
            "user_count",
            {"123456789012": {"groups": {"team": {"user_count": good_count}}}},
        )
        is True
    )


@requires_tofu
def test_workshop_accounts_accepts_valid_nested_map():
    """A well-formed nested map passes ALL three validation rules (R3.1)."""
    assert workshop_accounts_accepts(VALID_ACCOUNTS) is True


# --- tofu-backed: the workshop_id slug grammar ------------------------------

@requires_tofu
@pytest.mark.parametrize(
    "slug",
    ["a", "kiro", "kiro-2025-10-10", "a1-b2-c3", "a" * 63],
)
def test_workshop_id_accepts_valid_slugs(slug):
    """Valid slugs — lowercase alnum + single hyphens, up to 63 chars — pass."""
    assert workshop_id_accepts(slug) is True


@requires_tofu
@pytest.mark.parametrize(
    "slug",
    [
        "",  # empty
        "   ",  # whitespace only
        "Kiro",  # uppercase
        "kiro_2025",  # underscore not allowed
        "-kiro",  # leading hyphen
        "kiro-",  # trailing hyphen
        "ki--ro",  # consecutive hyphens
        "a" * 64,  # over 63 chars
    ],
)
def test_workshop_id_rejects_invalid_slugs(slug):
    """Empty/whitespace/uppercase/leading-trailing/double-hyphen/over-63 fail."""
    assert workshop_id_accepts(slug) is False


# --- Removed-variable supersession (R3.3) -----------------------------------

@pytest.mark.parametrize("removed", REMOVED_SUBSCRIPTION_VARS)
def test_removed_generator_variable_has_no_block(removed):
    """Each removed generator / idc_account_map has no variable block (R3.3).

    With no ``variable "<name>"`` declaration, a tfvars line that still sets the
    value references an undeclared variable — it cannot silently take effect.
    """
    assert variable_declared(removed) is False


@requires_tofu
@pytest.mark.parametrize("removed", REMOVED_SUBSCRIPTION_VARS)
def test_removed_variable_reference_does_not_resolve(removed):
    """``var.<removed>`` no longer resolves in the toolchain (R3.3).

    Evaluating a reference to an undeclared variable errors in ``tofu console``;
    we assert it does NOT resolve, which is the same reason a tfvars still
    setting it fails to resolve rather than silently applying its value.
    """
    assert console_reference_resolves(removed) is False


def test_no_generator_locals_remain_in_variables():
    """None of the removed names reappear as a declared variable (R3.3)."""
    text = read_variables_tf()
    for removed in REMOVED_SUBSCRIPTION_VARS:
        assert f'variable "{removed}"' not in text


# --- Manifest carries per-user account_id and workshop_id (R4.3) ------------

def test_manifest_carries_per_user_account_id():
    """Each manifest users[k] entry carries a per-user account_id (R4.3)."""
    text = read_outputs_tf()
    manifest = text[text.index('output "provisioning_manifest"') :]
    users_block = manifest[manifest.index("users = {") :]
    assert "account_id = local.user_account_id[k]" in users_block


def test_manifest_carries_workshop_id():
    """provisioning_manifest surfaces the document-level workshop_id (R4.3)."""
    text = read_outputs_tf()
    manifest = text[text.index('output "provisioning_manifest"') :]
    assert "workshop_id" in manifest and "var.workshop_id" in manifest


# --- tofu-backed: the full config still validates ---------------------------

@requires_tofu
def test_full_config_validates():
    """The subscription config (new schema, generators gone) passes validate.

    This is the end-to-end check that the removed-variable supersession did not
    leave a dangling reference: if any .tf still read a removed generator or
    idc_account_map, validate would fail with an undeclared-variable error.
    """
    if not full_config_validates():
        proc = tofu_validate()
        pytest.fail(f"tofu validate failed:\n{proc.stdout}\n{proc.stderr}")
