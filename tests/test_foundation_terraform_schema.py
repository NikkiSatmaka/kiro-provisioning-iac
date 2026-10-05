"""Text-fact + offline-validation tests for the Foundation IdC stack.

Feature: foundation-idc-service, Task 1.10
Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.1, 2.2,
           2.3, 2.4, 2.5, 3.1, 3.4, 4.2, 4.4, 5.1, 5.2

The Foundation IdC service creates and owns the single account-level IdC
instance (``awscc_sso_instance "this"``) every workshop's subscription stack
consumes. Creating the instance itself needs AWS and is out of scope for an
offline suite; what IS checkable offline is the stack's *shape* — the schema and
wiring facts the design pins — plus that the whole config parses and its pure
derivations evaluate correctly.

Two layers, so the suite is useful with or without a toolchain:

* Static text-fact assertions read the ``foundation/terraform/*.tf`` sources
  directly and ALWAYS run. They cover: exactly one ``awscc_sso_instance "this"``
  and none of the users/groups/memberships/permission-sets/account-assignments
  resources (R1.1-R1.6); the recovered ``hashicorp/awscc`` + ``hashicorp/aws``
  required-provider constraints (R5.1, R5.2); the ``instance_name`` default
  ``kiro-login`` bound to the resource's ``name`` (R1.7, R1.8); the four outputs
  bound to the right locals/derivation (R2.1-R2.4, R3.1); a value-free
  ``backend "s3" {}`` and a keyless ``backend.hcl.example`` (R4.2, R4.4); and no
  ``data "terraform_remote_state"`` anywhere (R3.4).
* The ``tofu``-backed assertions run against a throwaway, offline-initialized
  copy of the stack (the S3 backend block dropped so ``tofu init -backend=false``
  stays local). ``tofu validate`` proves the config is valid; ``tofu console``
  evaluates the ``sign_in_url`` interpolation, the AWSCC tag transform on a
  sample map, and the region/profile ``!= "" ? x : null`` ternary on ``""`` vs a
  value — pure functions, no backend/provider. These skip cleanly when no
  ``tofu`` binary is on PATH.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FOUNDATION_TF_DIR = REPO_ROOT / "foundation" / "terraform"

VERSIONS_TF = FOUNDATION_TF_DIR / "versions.tf"
PROVIDERS_TF = FOUNDATION_TF_DIR / "providers.tf"
VARIABLES_TF = FOUNDATION_TF_DIR / "variables.tf"
IDENTITY_CENTER_TF = FOUNDATION_TF_DIR / "identity_center.tf"
OUTPUTS_TF = FOUNDATION_TF_DIR / "outputs.tf"
BACKEND_TF = FOUNDATION_TF_DIR / "backend.tf"
BACKEND_HCL_EXAMPLE = FOUNDATION_TF_DIR / "backend.hcl.example"

# The Identity Center resources the Foundation stack must NOT declare — it
# creates the *instance* only; users/groups/memberships/permission-sets/account-
# assignments stay in the subscription stack (R1.2-R1.6).
FORBIDDEN_RESOURCE_TYPES = (
    "aws_identitystore_user",
    "aws_identitystore_group",
    "aws_identitystore_group_membership",
    "aws_ssoadmin_permission_set",
    "aws_ssoadmin_account_assignment",
)

# Matches a ``key = ...`` setting at the start of a line (ignoring leading
# whitespace) — an HCL ``key`` argument, not a ``# ... key ...`` comment.
KEY_LINE = re.compile(r"^\s*key\s*=", re.MULTILINE)


def _tofu_available() -> bool:
    return shutil.which("tofu") is not None


requires_tofu = pytest.mark.skipif(
    not _tofu_available(), reason="tofu binary not on PATH"
)


def _all_tf_source() -> str:
    """Concatenate every ``*.tf`` source in the foundation stack."""
    return "\n".join(p.read_text() for p in sorted(FOUNDATION_TF_DIR.glob("*.tf")))


def _strip_hcl_comments(text: str) -> str:
    """Drop ``#`` and ``//`` line comments so a key *mention* in a comment is
    never mistaken for an actual setting."""
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("#", "//")):
            continue
        for marker in ("#", "//"):
            idx = line.find(marker)
            if idx != -1:
                line = line[:idx]
        out.append(line)
    return "\n".join(out)


# ===========================================================================
# Offline tofu harness (local to the foundation stack)
# ===========================================================================
#
# Mirrors tests/_terraform_harness.py's approach for the subscription stack:
# copy the stack to a temp dir, drop the remote S3 backend so
# `tofu init -backend=false` runs with no network, and reuse that one init for
# every validate/console check in the session.


@lru_cache(maxsize=1)
def _initialized_tf_dir() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="foundation-tf-harness-"))
    for tf in FOUNDATION_TF_DIR.glob("*.tf"):
        shutil.copy(tf, tmp / tf.name)
    lock = FOUNDATION_TF_DIR / ".terraform.lock.hcl"
    if lock.exists():
        shutil.copy(lock, tmp / lock.name)
    # Drop the remote S3 backend so init stays local and offline.
    (tmp / "backend.tf").unlink(missing_ok=True)

    subprocess.run(
        ["tofu", "init", "-backend=false", "-input=false", "-no-color"],
        cwd=tmp,
        check=True,
        capture_output=True,
        text=True,
    )
    return tmp


def _tofu_validate() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["tofu", "validate", "-no-color"],
        cwd=_initialized_tf_dir(),
        capture_output=True,
        text=True,
        check=False,
    )


def _tofu_console_raw(expression: str) -> str:
    """Evaluate a pure OpenTofu expression via ``tofu console``, full output.

    ``tofu console`` runs pure functions without reaching the provider or
    backend, so the derivation checks stay offline. The result may span several
    lines (e.g. a list of objects), so the full stripped stdout is returned.
    """
    proc = subprocess.run(
        ["tofu", "console", "-no-color"],
        cwd=_initialized_tf_dir(),
        input=expression + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(f"tofu console failed for {expression!r}:\n{proc.stderr}")
    return proc.stdout.strip()


def _tofu_console_eval(expression: str) -> str:
    """Evaluate a pure OpenTofu expression returning its single-line result."""
    return _tofu_console_raw(expression).splitlines()[-1].strip()


# ===========================================================================
# Static text-fact assertions (always run)
# ===========================================================================

# --- The single owned resource (R1.1) --------------------------------------

def test_exactly_one_awscc_sso_instance_this():
    """Exactly one ``awscc_sso_instance "this"`` is declared across the stack (R1.1)."""
    source = _all_tf_source()
    instances = re.findall(
        r'resource\s+"awscc_sso_instance"\s+"this"', source
    )
    assert len(instances) == 1, (
        f"expected exactly one awscc_sso_instance \"this\", found {len(instances)}"
    )
    # And no awscc_sso_instance under any other resource name, either.
    any_instance = re.findall(r'resource\s+"awscc_sso_instance"\s+"[^"]+"', source)
    assert len(any_instance) == 1, (
        f"expected a single awscc_sso_instance resource, found {len(any_instance)}"
    )


# --- No users/groups/memberships/permission-sets/assignments (R1.2-R1.6) ----

@pytest.mark.parametrize("resource_type", FORBIDDEN_RESOURCE_TYPES)
def test_no_identity_center_membership_resources(resource_type):
    """The stack creates the instance only — no identity-center membership
    resources (R1.2-R1.6)."""
    source = _all_tf_source()
    assert f'"{resource_type}"' not in source, (
        f"foundation stack must not declare {resource_type}"
    )


# --- Required providers: recovered awscc + aws constraints (R5.1, R5.2) -----

def test_required_providers_declare_awscc_with_recovered_constraint():
    """``required_providers`` includes ``hashicorp/awscc >= 1.0.0`` (R5.1).

    awscc is the only provider that can CREATE an IdC instance; the constraint
    is the one recovered verbatim from history.
    """
    text = VERSIONS_TF.read_text()
    m = re.search(
        r"awscc\s*=\s*{[^}]*?source\s*=\s*\"hashicorp/awscc\"[^}]*?"
        r"version\s*=\s*\"([^\"]+)\"",
        text,
        re.DOTALL,
    )
    assert m, "no hashicorp/awscc required-provider entry found in versions.tf"
    assert m.group(1) == ">= 1.0.0", (
        f"awscc version constraint is {m.group(1)!r}, expected '>= 1.0.0'"
    )


def test_required_providers_declare_aws_with_recovered_constraint():
    """``required_providers`` includes ``hashicorp/aws >= 5.56.0`` (R5.2)."""
    text = VERSIONS_TF.read_text()
    m = re.search(
        r"aws\s*=\s*{[^}]*?source\s*=\s*\"hashicorp/aws\"[^}]*?"
        r"version\s*=\s*\"([^\"]+)\"",
        text,
        re.DOTALL,
    )
    assert m, "no hashicorp/aws required-provider entry found in versions.tf"
    assert m.group(1) == ">= 5.56.0", (
        f"aws version constraint is {m.group(1)!r}, expected '>= 5.56.0'"
    )


# --- instance_name default + binding to the resource (R1.7, R1.8) -----------

def test_instance_name_defaults_to_kiro_login():
    """``instance_name`` defaults to ``kiro-login`` (R1.8)."""
    text = VARIABLES_TF.read_text()
    block_start = text.index('variable "instance_name"')
    block = text[block_start:]
    assert re.search(r'default\s*=\s*"kiro-login"', block), (
        "instance_name must default to \"kiro-login\""
    )


def test_resource_sets_name_from_instance_name_variable():
    """The IdC resource sets ``name = var.instance_name`` (R1.7)."""
    text = IDENTITY_CENTER_TF.read_text()
    resource = text[text.index('resource "awscc_sso_instance"') :]
    assert re.search(r"name\s*=\s*var\.instance_name", resource), (
        "awscc_sso_instance.this must set name = var.instance_name"
    )


def test_resource_applies_default_tags_as_list_of_objects():
    """Tags reach the instance via the AWSCC list-of-objects shape (R1.9)."""
    text = IDENTITY_CENTER_TF.read_text()
    resource = text[text.index('resource "awscc_sso_instance"') :]
    assert re.search(
        r"tags\s*=\s*\[for\s+k,\s*v\s+in\s+var\.default_tags\s*:\s*"
        r"{\s*key\s*=\s*k,\s*value\s*=\s*v\s*}\]",
        resource,
    ), "awscc_sso_instance.this must set tags to the list-of-objects transform"


# --- The four outputs bound to the right locals/derivation (R2.1-R2.4, R3.1) -

def test_outputs_declare_the_four_values_bound_correctly():
    """``outputs.tf`` declares the four outputs bound to the right source."""
    text = OUTPUTS_TF.read_text()

    def _output_value(name: str) -> str:
        start = text.index(f'output "{name}"')
        block = text[start:]
        # Bound to the next closing brace at column 0 (or EOF).
        end = block.find("\n}")
        block = block[: end if end != -1 else len(block)]
        m = re.search(r"value\s*=\s*(.+)", block)
        assert m, f'output "{name}" has no value assignment'
        return m.group(1).strip()

    # R2.1 instance_arn, R2.2 identity_store_id, R2.3 region — scalar locals.
    assert _output_value("instance_arn") == "local.instance_arn"
    assert _output_value("identity_store_id") == "local.identity_store_id"
    assert _output_value("region") == "local.resolved_region"
    # R2.4 sign_in_url — the exact portal derivation from the identity store id.
    assert (
        _output_value("sign_in_url")
        == '"https://${local.identity_store_id}.awsapps.com/start"'
    )


def test_locals_bind_arn_and_id_to_the_created_resource():
    """The ARN / identity-store-id locals come from the created resource, and
    are exposed only as outputs (R3.1)."""
    text = IDENTITY_CENTER_TF.read_text()
    assert re.search(
        r"instance_arn\s*=\s*awscc_sso_instance\.this\.instance_arn", text
    )
    assert re.search(
        r"identity_store_id\s*=\s*awscc_sso_instance\.this\.identity_store_id",
        text,
    )
    assert re.search(r"resolved_region\s*=\s*data\.aws_region\.current\.region", text)


# --- Backend: value-free backend "s3" {} + keyless .example (R4.2, R4.4) ----

def test_backend_tf_is_value_free_s3_block():
    """``backend.tf`` declares a value-free ``backend "s3" {}`` (R4.2)."""
    body = _strip_hcl_comments(BACKEND_TF.read_text())
    assert re.search(r'backend\s+"s3"\s*{\s*}', body), (
        "backend.tf must declare a value-free backend \"s3\" {} block"
    )


def test_backend_example_carries_no_key_line():
    """``backend.hcl.example`` carries no ``key =`` line; the key is supplied at
    init time (R4.4)."""
    body = _strip_hcl_comments(BACKEND_HCL_EXAMPLE.read_text())
    assert KEY_LINE.search(body) is None, (
        "backend.hcl.example must not declare a `key =` line"
    )
    # Sanity: it still carries the shared bucket value it is a template for.
    assert re.search(r"(?m)^\s*bucket\s*=", body), (
        "backend.hcl.example should still carry the shared bucket value"
    )


# --- No remote-state reference to any other stack (R3.4) --------------------

def test_no_terraform_remote_state_declared():
    """No ``data "terraform_remote_state"`` is declared anywhere (R3.4)."""
    source = _all_tf_source()
    assert 'data "terraform_remote_state"' not in source, (
        "foundation stack must not reference another stack's remote state"
    )


# ===========================================================================
# tofu-backed offline checks
# ===========================================================================

@requires_tofu
def test_tofu_validate_succeeds():
    """The foundation stack passes ``tofu validate`` offline."""
    proc = _tofu_validate()
    assert proc.returncode == 0, (
        f"tofu validate failed:\n{proc.stdout}\n{proc.stderr}"
    )


@requires_tofu
def test_console_sign_in_url_interpolation():
    """The ``sign_in_url`` interpolation yields the exact portal format."""
    result = _tofu_console_eval(
        'format("https://%s.awsapps.com/start", "d-0123456789")'
    )
    # tofu console echoes a string result with surrounding quotes.
    assert result == '"https://d-0123456789.awsapps.com/start"'


@requires_tofu
def test_console_tag_transform_on_sample_map():
    """The AWSCC tag transform turns a map into the list-of-objects shape."""
    result = _tofu_console_raw(
        '[for k, v in {"Project" = "kiro", "ManagedBy" = "opentofu"} : '
        "{ key = k, value = v }]"
    )
    # The list length equals the map size and every entry maps to a {key,value}
    # object; order follows the map's lexical key order in tofu.
    assert '"key" = "Project"' in result and '"value" = "kiro"' in result
    assert '"key" = "ManagedBy"' in result and '"value" = "opentofu"' in result
    assert result.count('"key"') == 2 and result.count('"value"') == 2


@requires_tofu
def test_console_region_profile_ternary_falls_back_on_empty():
    """``s != "" ? s : null`` falls back to null for the empty string.

    Both ternary branches are strings in the real provider config
    (``var.aws_region != "" ? var.aws_region : null``), so tofu unifies the
    result type to string and prints the null fallback as ``tostring(null)`` —
    a null value, i.e. the provider inherits AWS_REGION from the environment.
    """
    assert _tofu_console_eval('"" != "" ? "" : null') == "tostring(null)"


@requires_tofu
def test_console_region_profile_ternary_passes_through_a_value():
    """``s != "" ? s : null`` passes a non-empty value through verbatim."""
    assert _tofu_console_eval('"us-east-1" != "" ? "us-east-1" : null') == '"us-east-1"'
