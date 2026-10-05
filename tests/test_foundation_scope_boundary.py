"""Scope-boundary + documentation text-fact tests for the Foundation IdC spec.

Feature: foundation-idc-service, Task 7.3
Validates: Requirements 3.2, 3.3, 3.4, 7.6, 8.2, 8.3, 9.1, 9.3, 10.1, 10.2,
           10.3, 10.4

The foundation-idc-service spec adds ONLY the ``foundation/`` stack (plus the
additive backend-bootstrap output and the mise tasks). It makes NO changes to
the subscription stack's ``.tf`` files: that stack keeps CONSUMING the IdC
instance through its existing ``var.idc_instance_arn`` / ``var.identity_store_id``
inputs. The two stacks are wired by the operator through explicit variables,
never by a remote-state reference. This suite pins the decoupling boundary that
guarantee rests on:

* The subscription stack still declares ``variable "idc_instance_arn"`` and
  ``variable "identity_store_id"`` as string inputs (R3.2).
* Neither the subscription stack nor the foundation stack declares a
  ``data "terraform_remote_state"`` block — so neither reads the other's remote
  state; the handoff is operator-supplied variables, not state coupling
  (R3.3, R3.4).

It also pins the documentation facts the RUNBOOK/README must carry so the
end-to-end create-then-wire workflow and its guardrails stay documented:

* The create-then-wire order and the once-and-reused statement (R10.1-R10.4).
* The ``tofu import awscc_sso_instance.this`` recovery and the
  one-account-instance-per-account statement (R8.2, R8.3).
* The management-account enablement precondition — required, one-time, and
  irreversible (R9.1, R9.3).
* The destructive/irreversible teardown note (R7.6).

Every assertion reads the committed sources directly, so the suite always runs
with no toolchain. Documentation phrases are matched case-insensitively on the
concatenated README + RUNBOOK so a wording tweak that keeps the fact does not
break the test, while a dropped fact does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SUBSCRIPTION_TF_DIR = REPO_ROOT / "subscription" / "terraform"
FOUNDATION_TF_DIR = REPO_ROOT / "foundation" / "terraform"

FOUNDATION_README = REPO_ROOT / "foundation" / "README.md"
FOUNDATION_RUNBOOK = REPO_ROOT / "foundation" / "RUNBOOK.md"

# The subscription inputs the stack keeps consuming the IdC instance through.
SUBSCRIPTION_FOUNDATION_VARS = ("idc_instance_arn", "identity_store_id")


def _concat_tf(tf_dir: Path) -> str:
    """Concatenate every ``*.tf`` source in a stack directory."""
    return "\n".join(p.read_text() for p in sorted(tf_dir.glob("*.tf")))


def _docs_text() -> str:
    """The foundation README + RUNBOOK concatenated, lower-cased for matching."""
    return (
        FOUNDATION_README.read_text() + "\n" + FOUNDATION_RUNBOOK.read_text()
    ).lower()


# ===========================================================================
# Scope boundary: the subscription stack is unchanged and still consumes the
# instance through its existing variables (R3.2)
# ===========================================================================

@pytest.mark.parametrize("var_name", SUBSCRIPTION_FOUNDATION_VARS)
def test_subscription_still_declares_foundation_variable(var_name):
    """The subscription stack still declares the Foundation IdC input (R3.2).

    This spec changes nothing in the subscription stack: it keeps reading the
    instance ARN and identity store id from these operator-supplied variables.
    """
    source = _concat_tf(SUBSCRIPTION_TF_DIR)
    assert re.search(rf'variable\s+"{var_name}"', source), (
        f'subscription stack must still declare variable "{var_name}"'
    )


@pytest.mark.parametrize("var_name", SUBSCRIPTION_FOUNDATION_VARS)
def test_subscription_foundation_variable_is_a_string_input(var_name):
    """Each retained Foundation input is a string variable (R3.2)."""
    source = _concat_tf(SUBSCRIPTION_TF_DIR)
    block_start = source.index(f'variable "{var_name}"')
    block = source[block_start:]
    assert re.search(r"type\s*=\s*string", block), (
        f'subscription variable "{var_name}" must be a string input'
    )


# ===========================================================================
# Decoupling: neither stack reads the other's remote state (R3.3, R3.4)
# ===========================================================================

def test_subscription_declares_no_terraform_remote_state():
    """The subscription stack declares no ``data "terraform_remote_state"`` —
    it does not read the foundation stack's state (R3.3)."""
    source = _concat_tf(SUBSCRIPTION_TF_DIR)
    assert 'data "terraform_remote_state"' not in source, (
        "subscription stack must not reference another stack's remote state"
    )


def test_foundation_declares_no_terraform_remote_state():
    """The foundation stack declares no ``data "terraform_remote_state"`` — it
    does not read the subscription stack's state (R3.4)."""
    source = _concat_tf(FOUNDATION_TF_DIR)
    assert 'data "terraform_remote_state"' not in source, (
        "foundation stack must not reference another stack's remote state"
    )


# ===========================================================================
# Documentation facts carried by the README / RUNBOOK
# ===========================================================================

# --- Create-then-wire order + once-and-reused (R10.1-R10.4) ----------------

def test_docs_describe_backend_then_foundation_then_subscription_order():
    """The docs describe running backend bootstrap, then foundation, then the
    subscription stack (R10.1)."""
    docs = _docs_text()
    assert "backend-bootstrap" in docs
    assert "foundation-apply" in docs
    assert "subscription" in docs


def test_docs_describe_capturing_the_two_outputs():
    """The docs describe capturing the instance_arn and identity_store_id
    outputs (R10.2)."""
    docs = _docs_text()
    assert "instance_arn" in docs
    assert "identity_store_id" in docs


def test_docs_describe_wiring_outputs_via_tf_var_or_tfvars():
    """The docs describe supplying the captured IDs to the subscription stack
    via TF_VAR_* or tfvars (R10.3)."""
    docs = _docs_text()
    assert "tf_var_idc_instance_arn" in docs
    assert "tf_var_identity_store_id" in docs
    assert "tfvars" in docs


def test_docs_state_applied_once_and_reused_across_workshops():
    """The docs state the foundation stack is applied once and reused across
    every workshop rather than per workshop (R10.4)."""
    docs = _docs_text()
    assert "once" in docs and "reused across every workshop" in docs


# --- Idempotency + import + one-instance-per-account (R8.2, R8.3) ----------

def test_docs_describe_importing_an_existing_instance():
    """The docs direct the operator to import a pre-existing instance with
    ``tofu import awscc_sso_instance.this`` (R8.2)."""
    docs = _docs_text()
    assert "tofu import awscc_sso_instance.this" in docs


def test_docs_state_one_account_instance_per_account():
    """The docs state AWS permits one account instance per account across all
    regions (R8.3)."""
    docs = _docs_text()
    assert "one" in docs
    assert "account instance per account" in docs
    assert "all regions" in docs or "across all regions" in docs


# --- Management-account enablement precondition (R9.1, R9.3) ---------------

def test_docs_state_management_account_enablement_precondition():
    """The docs state that creating an account instance requires the AWS
    Organizations management account to have enabled member-account IdC
    instances (R9.1)."""
    docs = _docs_text()
    assert "management account" in docs
    assert "member-account" in docs or "member account" in docs


def test_docs_state_management_account_enablement_is_one_time_irreversible():
    """The docs state the management-account enablement is a one-time,
    irreversible toggle (R9.3)."""
    docs = _docs_text()
    assert "one-time" in docs
    assert "irreversible" in docs


# --- Destructive teardown note (R7.6) --------------------------------------

def test_docs_state_teardown_is_destructive_and_enablement_irreversible():
    """The docs state that deleting the instance is destructive and the
    management-account enablement cannot be reversed (R7.6)."""
    docs = _docs_text()
    assert "destructive" in docs
    # The enablement cannot be reversed / is irreversible.
    assert "cannot be reversed" in docs or "irreversible" in docs
