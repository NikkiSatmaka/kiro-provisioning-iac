"""Integration/example tests for the subscription Terraform schema + manifest.

Feature: idc-region-account-mapping, Task 2.4 (baseline)
Updated by: multi-workshop-provisioning, Task 3.8

These tests pin the schema and wiring facts that survive into the
multi-workshop-provisioning schema:

* ``kiro_region`` exists as a string variable defaulting to ``us-east-1``
  (R4.1 of the baseline — the Kiro sign-in region).
* The ``provisioning_manifest`` output and the standalone ``account_id`` output
  wire ``kiro_region``, a document-level ``account_id``, and a per-user
  ``account_id`` through (baseline R5.1-R5.3).

Note on supersession: the baseline ``idc_account_map`` variable and the
map-based ``local.idc_key`` / ``lookup(var.idc_account_map, …)`` resolution it
drove were REMOVED by multi-workshop-provisioning Pillar 2. Account resolution
now runs through the explicit nested ``workshop_accounts`` map
(``local.user_account_id`` / ``local.account_id``). The assertions that pinned
the removed ``idc_account_map`` schema and its locals have been dropped from
this file; the new schema's validations and the removed-variable supersession
are covered by ``test_workshop_accounts_validation.py``. The per-user and
document-level ``account_id`` wiring facts below still hold under the new
locals, so they stay.

Two layers, so the suite is useful with or without a toolchain:

* Static text-fact assertions read the ``.tf`` sources directly and ALWAYS run.
* The ``tofu``-backed assertion (``tofu validate`` for config validity) runs the
  real toolchain against a throwaway, offline-initialized copy of the config; it
  skips cleanly when no ``tofu`` binary is on PATH (see ``_terraform_harness``).
"""

from __future__ import annotations

import pytest
from _terraform_harness import (
    read_outputs_tf,
    read_variables_tf,
    tofu_available,
    tofu_validate,
)

requires_tofu = pytest.mark.skipif(
    not tofu_available(), reason="tofu binary not on PATH"
)


# --- Static schema facts: variables exist (R4.1) ----------------------------

def test_kiro_region_variable_declared_with_default():
    """kiro_region exists as a string variable defaulting to us-east-1."""
    text = read_variables_tf()
    assert 'variable "kiro_region"' in text
    # Its default is the only region Kiro supports today.
    assert 'default     = "us-east-1"' in text or 'default = "us-east-1"' in text


# --- Static wiring facts: manifest + outputs (R5.1, R5.2, R5.3) -------------

def test_standalone_account_id_output_exposed():
    """A standalone account_id output exposes local.account_id (R5.2)."""
    text = read_outputs_tf()
    assert 'output "account_id"' in text
    assert "local.account_id" in text


def test_manifest_carries_kiro_region_and_document_account_id():
    """provisioning_manifest wires kiro_region and a document-level account_id.

    (R5.1 for the document-level account_id; the kiro_region field is the
    sign-in region threaded alongside it.)
    """
    text = read_outputs_tf()
    manifest = text[text.index('output "provisioning_manifest"') :]
    assert "kiro_region" in manifest and "var.kiro_region" in manifest
    assert "account_id" in manifest and "local.account_id" in manifest


def test_manifest_carries_per_user_account_id():
    """Each manifest users[k] entry carries a per-user account_id (R5.3).

    Under the multi-workshop schema this is resolved through
    ``local.user_account_id`` (user -> group -> owning account) rather than the
    removed ``idc_account_map`` lookup, but the wiring field is unchanged.
    """
    text = read_outputs_tf()
    manifest = text[text.index('output "provisioning_manifest"') :]
    users_block = manifest[manifest.index("users = {") :]
    assert "account_id = local.user_account_id[k]" in users_block


# --- tofu-backed: config validity -------------------------------------------

@requires_tofu
def test_tofu_validate_succeeds():
    """The config (with the new variables/outputs) passes tofu validate."""
    proc = tofu_validate()
    assert proc.returncode == 0, f"tofu validate failed:\n{proc.stdout}\n{proc.stderr}"
