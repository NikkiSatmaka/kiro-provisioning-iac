"""Smoke/example tests for the region-split environment config facts.

Feature: idc-region-account-mapping, Task 1.3
Validates: Requirements 1.1, 1.2, 1.3

These example tests pin the configuration facts the region split introduces,
read from the files that actually carry them:

* ``mise.toml`` ``[env]`` is the authoritative env assembler for every
  ``mise run`` task. We assert it defines ``KIRO_REGION`` (default
  ``us-east-1``) and ``IDC_REGION`` (default ``ap-southeast-1``), that
  ``AWS_REGION`` is templated from ``IDC_REGION`` (``{{ env.IDC_REGION }}``), and
  that ``AWS_DEFAULT_REGION`` mirrors ``AWS_REGION`` (R1.1, R1.2, R1.3).
* ``.env.example`` (tracked template) documents the three variables with the
  intended defaults and makes ``AWS_REGION`` track ``IDC_REGION``.
* The end-to-end resolution: driving the real mise template engine with the
  defaults yields ``AWS_REGION == IDC_REGION == ap-southeast-1`` and
  ``AWS_DEFAULT_REGION == AWS_REGION`` — the assembled behavior a task sees
  (R1.3).

The resolution assertions run the real ``mise`` binary against the repo's own
``[env]`` definitions (see ``_env_assembler``); if ``mise`` is not installed the
resolution tests skip, while the pure text-fact tests always run.
"""

from __future__ import annotations

import pytest
from _env_assembler import (
    REPO_ROOT,
    mise_available,
    read_mise_env_block,
    resolve_env,
)

ENV_EXAMPLE = REPO_ROOT / ".env.example"


# --- mise.toml [env] definitions (the authoritative assembler) --------------

def test_mise_env_defines_kiro_region_default_us_east_1():
    """mise.toml [env] defines KIRO_REGION with default us-east-1 (R1.1)."""
    block = read_mise_env_block()
    assert "KIRO_REGION" in block, "KIRO_REGION missing from mise.toml [env]"
    assert block["KIRO_REGION"] == {"default": "us-east-1"}


def test_mise_env_defines_idc_region_default_ap_southeast_1():
    """mise.toml [env] defines IDC_REGION with default ap-southeast-1 (R1.2)."""
    block = read_mise_env_block()
    assert "IDC_REGION" in block, "IDC_REGION missing from mise.toml [env]"
    assert block["IDC_REGION"] == {"default": "ap-southeast-1"}


def test_mise_env_aws_region_templates_from_idc_region():
    """AWS_REGION is templated from IDC_REGION, not a region literal (R1.3)."""
    block = read_mise_env_block()
    assert block.get("AWS_REGION") == "{{ env.IDC_REGION }}"


def test_mise_env_aws_default_region_mirrors_aws_region():
    """AWS_DEFAULT_REGION mirrors AWS_REGION (preserved invariant)."""
    block = read_mise_env_block()
    assert block.get("AWS_DEFAULT_REGION") == "{{ env.AWS_REGION }}"


# --- .env.example (tracked template) ----------------------------------------

def test_env_example_documents_region_variables():
    """.env.example carries both region vars with their intended defaults."""
    text = ENV_EXAMPLE.read_text()
    assert "KIRO_REGION=us-east-1" in text
    assert "IDC_REGION=ap-southeast-1" in text


def test_env_example_aws_region_tracks_idc_region():
    """.env.example makes AWS_REGION track IDC_REGION (no region literal)."""
    text = ENV_EXAMPLE.read_text()
    assert "AWS_REGION=${IDC_REGION}" in text


# --- End-to-end resolution through the real mise assembler ------------------

@pytest.mark.skipif(not mise_available(), reason="mise binary not on PATH")
def test_defaults_resolve_to_documented_regions():
    """With no override, the assembled env matches the documented defaults.

    KIRO_REGION -> us-east-1, IDC_REGION -> ap-southeast-1, AWS_REGION tracks
    IDC_REGION, and AWS_DEFAULT_REGION mirrors AWS_REGION (R1.1, R1.2, R1.3).
    """
    env = resolve_env()
    assert env["KIRO_REGION"] == "us-east-1"
    assert env["IDC_REGION"] == "ap-southeast-1"
    assert env["AWS_REGION"] == env["IDC_REGION"] == "ap-southeast-1"
    assert env["AWS_DEFAULT_REGION"] == env["AWS_REGION"]


@pytest.mark.skipif(not mise_available(), reason="mise binary not on PATH")
def test_overriding_idc_region_drives_aws_region():
    """Setting IDC_REGION drives AWS_REGION (and the mirror) end to end (R1.3).

    A concrete, readable example of the Property 1 relationship: supplying
    IDC_REGION=eu-central-1 resolves AWS_REGION to eu-central-1 while KIRO_REGION
    stays at its own default, independent of the provisioning region.
    """
    env = resolve_env(overrides={"IDC_REGION": "eu-central-1"})
    assert env["IDC_REGION"] == "eu-central-1"
    assert env["AWS_REGION"] == "eu-central-1"
    assert env["AWS_DEFAULT_REGION"] == "eu-central-1"
    # KIRO_REGION is independent of the resource region.
    assert env["KIRO_REGION"] == "us-east-1"
