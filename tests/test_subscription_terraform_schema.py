"""Integration/example tests for the subscription Terraform schema + manifest.

Feature: idc-region-account-mapping, Task 2.4
Validates: Requirements 4.1, 4.2, 5.1, 5.2, 5.3

These tests pin the schema and wiring facts that tasks 2.1-2.3 add to
``subscription/terraform/``:

* ``kiro_region`` and ``idc_account_map`` variables exist with the intended
  types/defaults (R4.1, R4.2).
* The ``idc_account_map`` validation enforces a 12-digit AWS account id: it
  rejects a non-12-digit value and accepts both a valid 12-digit value and the
  empty map ``{}`` (R4.1, R4.2).
* The ``provisioning_manifest`` output and the standalone ``account_id`` output
  wire ``kiro_region``, a document-level ``account_id``, and a per-user
  ``account_id`` through (R5.1, R5.2, R5.3).

Two layers, so the suite is useful with or without a toolchain:

* Static text-fact assertions read the ``.tf`` sources directly and ALWAYS run.
* The ``tofu``-backed assertions (``tofu validate`` for config validity and
  ``tofu console`` for the validation-block rule) run the real toolchain against
  a throwaway, offline-initialized copy of the config; they skip cleanly when no
  ``tofu`` binary is on PATH (see ``_terraform_harness``).
"""

from __future__ import annotations

import pytest
from _terraform_harness import (
    extract_idc_account_map_regex,
    idc_account_map_valid,
    read_locals_tf,
    read_outputs_tf,
    read_variables_tf,
    tofu_available,
    tofu_validate,
)

requires_tofu = pytest.mark.skipif(
    not tofu_available(), reason="tofu binary not on PATH"
)


# --- Static schema facts: variables exist (R4.1, R4.2) ----------------------

def test_kiro_region_variable_declared_with_default():
    """kiro_region exists as a string variable defaulting to us-east-1."""
    text = read_variables_tf()
    assert 'variable "kiro_region"' in text
    # Its default is the only region Kiro supports today.
    assert 'default     = "us-east-1"' in text or 'default = "us-east-1"' in text


def test_idc_account_map_variable_declared_as_string_map():
    """idc_account_map exists as a map(string) defaulting to the empty map."""
    text = read_variables_tf()
    assert 'variable "idc_account_map"' in text
    assert "map(string)" in text


def test_idc_account_map_has_twelve_digit_validation():
    """The idc_account_map validation enforces a 12-digit account id (R4.1)."""
    # Reading the pattern out of the block also proves a validation block exists.
    assert extract_idc_account_map_regex() == "^[0-9]{12}$"


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
    """Each manifest users[k] entry carries a per-user account_id (R5.3)."""
    text = read_outputs_tf()
    manifest = text[text.index('output "provisioning_manifest"') :]
    users_block = manifest[manifest.index("users = {") :]
    assert "account_id = local.user_account_id[k]" in users_block


def test_locals_resolve_account_id_from_map_and_per_user():
    """locals derive account_id from the map and a per-user map (R5.3)."""
    text = read_locals_tf()
    assert 'idc_key = "default"' in text
    assert "lookup(var.idc_account_map, local.idc_key" in text
    assert "user_account_id = {" in text


# --- tofu-backed: config validity -------------------------------------------

@requires_tofu
def test_tofu_validate_succeeds():
    """The config (with the new variables/outputs) passes tofu validate."""
    proc = tofu_validate()
    assert proc.returncode == 0, f"tofu validate failed:\n{proc.stdout}\n{proc.stderr}"


# --- tofu-backed: the idc_account_map validation rule -----------------------

@requires_tofu
def test_idc_account_map_rejects_non_twelve_digit_value():
    """A non-12-digit account id fails the idc_account_map validation (R4.2)."""
    assert idc_account_map_valid({"default": "123"}) is False
    # A 13-digit value and a non-numeric value are rejected too.
    assert idc_account_map_valid({"default": "1234567890123"}) is False
    assert idc_account_map_valid({"default": "12345678901x"}) is False


@requires_tofu
def test_idc_account_map_accepts_valid_twelve_digit_value():
    """A valid 12-digit account id passes the validation (R4.1, R4.2)."""
    assert idc_account_map_valid({"default": "123456789012"}) is True


@requires_tofu
def test_idc_account_map_accepts_empty_map():
    """The default empty map {} passes the validation (R4.1)."""
    assert idc_account_map_valid({}) is True
