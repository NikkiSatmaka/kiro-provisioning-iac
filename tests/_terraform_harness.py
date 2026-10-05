"""Drive the subscription Terraform offline for schema/wiring assertions.

Feature: idc-region-account-mapping, Task 2.4

The integration tests for the Terraform schema and manifest wiring need to run
``tofu`` without AWS credentials or network. Two things get in the way of that:

* ``backend.tf`` declares a remote ``backend "s3" {}``; ``tofu init`` against it
  would try to reach S3. We copy the config into a throwaway directory and drop
  ``backend.tf`` so ``tofu init -backend=false`` initializes purely locally.
* ``tofu validate`` does NOT evaluate variable ``validation`` blocks — those run
  at plan time, which needs the provider and ``data.aws_region``. So to exercise
  the ``idc_account_map`` 12-digit rule offline we evaluate the *same* condition
  expression (read out of ``variables.tf``, never hand-copied) through
  ``tofu console``, which runs pure functions without touching the backend.

Everything here degrades cleanly: ``tofu_available()`` lets the tofu-backed
tests skip when no ``tofu`` binary is on PATH, while the static text-fact tests
always run.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

# Repo root is the parent of this tests/ directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
SUBSCRIPTION_TF_DIR = REPO_ROOT / "subscription" / "terraform"
VARIABLES_TF = SUBSCRIPTION_TF_DIR / "variables.tf"
OUTPUTS_TF = SUBSCRIPTION_TF_DIR / "outputs.tf"
LOCALS_TF = SUBSCRIPTION_TF_DIR / "locals.tf"


def tofu_available() -> bool:
    """True when a ``tofu`` binary is on PATH (tofu-backed tests skip if not)."""
    return shutil.which("tofu") is not None


def read_variables_tf() -> str:
    return VARIABLES_TF.read_text()


def read_outputs_tf() -> str:
    return OUTPUTS_TF.read_text()


def read_locals_tf() -> str:
    return LOCALS_TF.read_text()


def extract_idc_account_map_regex() -> str:
    """Pull the account-id regex literal out of the ``idc_account_map`` block.

    Reading the pattern from ``variables.tf`` (rather than hardcoding
    ``^[0-9]{12}$`` here) means a regression that loosens or breaks the
    validation regex is caught: the console check below runs the *actual*
    pattern the variable enforces.
    """
    text = read_variables_tf()
    # Narrow to the idc_account_map block so we don't match a regex elsewhere.
    block = _variable_block(text, "idc_account_map")
    m = re.search(r'regex\(\s*"([^"]+)"', block)
    if not m:
        raise AssertionError(
            "No regex(...) found in the idc_account_map validation block; "
            "the 12-digit account-id rule appears to be missing."
        )
    return m.group(1)


def _variable_block(text: str, name: str) -> str:
    """Return the source of ``variable "<name>" { ... }`` via brace matching."""
    start = text.find(f'variable "{name}"')
    if start == -1:
        raise AssertionError(f'variable "{name}" not found in variables.tf')
    brace = text.find("{", start)
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError(f'unterminated variable "{name}" block')


@lru_cache(maxsize=1)
def _initialized_tf_dir() -> Path:
    """Copy the subscription Terraform to a temp dir and init it offline.

    The S3 backend block is dropped so ``tofu init -backend=false`` runs with no
    network; the provider plugins come from the committed lock file. Cached for
    the test session so ``tofu validate``/``console`` reuse one init.
    """
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="idc-tf-harness-"))
    for tf in SUBSCRIPTION_TF_DIR.glob("*.tf"):
        shutil.copy(tf, tmp / tf.name)
    lock = SUBSCRIPTION_TF_DIR / ".terraform.lock.hcl"
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


def tofu_validate() -> subprocess.CompletedProcess[str]:
    """Run ``tofu validate`` in the offline-initialized config."""
    return subprocess.run(
        ["tofu", "validate", "-no-color"],
        cwd=_initialized_tf_dir(),
        capture_output=True,
        text=True,
    )


def tofu_console_eval(expression: str) -> str:
    """Evaluate a pure OpenTofu expression via ``tofu console`` and return it.

    ``tofu console`` reads the expression on stdin and prints the result; it
    runs pure functions (``can``, ``regex``, ``alltrue``) without reaching the
    provider or backend, which is exactly what the offline validation-rule
    assertions need.
    """
    proc = subprocess.run(
        ["tofu", "console", "-no-color"],
        cwd=_initialized_tf_dir(),
        input=expression + "\n",
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"tofu console failed for {expression!r}:\n{proc.stderr}"
        )
    return proc.stdout.strip().splitlines()[-1].strip()


def idc_account_map_valid(account_map: dict[str, str]) -> bool:
    """Evaluate the variable's own validation condition over ``account_map``.

    Mirrors the ``validation`` block in ``variables.tf``
    (``alltrue([for v in values(var.idc_account_map) : can(regex(PATTERN, v))])``)
    using the regex read from the file, so True/False matches whether a real
    plan would accept or reject the given map.
    """
    pattern = extract_idc_account_map_regex()
    entries = ", ".join(
        f'"{k}" = "{v}"' for k, v in account_map.items()
    )
    literal = "{" + entries + "}"
    expr = f'alltrue([for v in values({literal}) : can(regex("{pattern}", v))])'
    result = tofu_console_eval(expr)
    return result == "true"


# ===========================================================================
# Additions for multi-workshop-provisioning Task 1.5
# (Foundation IdC inputs + per-group assignment wiring)
# ===========================================================================
#
# Task 1.5 asserts facts that are stable regardless of the still-in-flight
# Pillar 2 work (tasks 3.1/3.2 rewrite locals.tf). Those stable facts are:
#
#   * idc_instance_arn / identity_store_id exist as string vars with NO default
#   * their own validation rejects empty / whitespace and accepts a real value,
#     with an error message that names the missing variable
#   * no awscc_sso_instance resource and no awscc provider remain in the sources
#   * identity_center.tf wires exactly one shared permission set and one
#     account assignment per group (for_each = local.groups)
#
# The full `tofu validate`/plan (one permission set + one assignment per group
# evaluated by the toolchain) depends on locals.tf being rewritten by task 3.2;
# `full_config_validates()` lets that assertion skip cleanly until then.

IDENTITY_CENTER_TF = SUBSCRIPTION_TF_DIR / "identity_center.tf"
VERSIONS_TF = SUBSCRIPTION_TF_DIR / "versions.tf"
PROVIDERS_TF = SUBSCRIPTION_TF_DIR / "providers.tf"


def read_identity_center_tf() -> str:
    return IDENTITY_CENTER_TF.read_text()


def read_versions_tf() -> str:
    return VERSIONS_TF.read_text()


def read_providers_tf() -> str:
    return PROVIDERS_TF.read_text()


def variable_block(name: str) -> str:
    """Public accessor for a ``variable "<name>" { ... }`` block source."""
    return _variable_block(read_variables_tf(), name)


def variable_has_default(name: str) -> bool:
    """True when the variable block declares a ``default`` argument.

    A no-default variable is a *required* input: OpenTofu errors if it is not
    supplied. Matching the ``default`` argument at the block's top level (via a
    simple ``default =`` / ``default  =`` scan) is enough here because the
    foundation variables are flat string vars with no nested blocks that could
    carry a ``default`` of their own.
    """
    block = variable_block(name)
    return re.search(r"(?m)^\s*default\s*=", block) is not None


def extract_validation_condition(var_name: str) -> str:
    """Return the ``condition`` expression of a variable's validation block.

    Reads the real expression out of ``variables.tf`` so the offline rule check
    below runs the *actual* condition the variable enforces, not a hand-copied
    duplicate that could drift.
    """
    block = variable_block(var_name)
    m = re.search(r"condition\s*=\s*(.+)", block)
    if not m:
        raise AssertionError(
            f'variable "{var_name}" has no validation condition; the '
            "required-input rule appears to be missing."
        )
    return m.group(1).strip()


def extract_validation_error_message(var_name: str) -> str:
    """Return the ``error_message`` string literal of a validation block."""
    block = variable_block(var_name)
    m = re.search(r'error_message\s*=\s*"((?:[^"\\]|\\.)*)"', block)
    if not m:
        raise AssertionError(
            f'variable "{var_name}" validation has no error_message.'
        )
    return m.group(1)


def required_string_var_accepts(var_name: str, value: str) -> bool:
    """Evaluate a required-input variable's own validation condition offline.

    The foundation variables guard with ``length(trimspace(var.X)) > 0``. We
    substitute the ``var.X`` reference in the real condition with the supplied
    literal and evaluate it through ``tofu console`` (pure functions only, no
    backend/provider), so True/False matches whether a plan would accept or
    reject ``value`` for that variable.
    """
    condition = extract_validation_condition(var_name)
    literal = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    expr = condition.replace(f"var.{var_name}", literal)
    return tofu_console_eval(expr) == "true"


@lru_cache(maxsize=1)
def full_config_validates() -> bool:
    """True when the whole subscription config passes ``tofu validate``.

    Used to gate the plan-level assertion (one permission set + one assignment
    per group as the toolchain evaluates it): while task 3.2 is still rewriting
    ``locals.tf``, the config references removed generators and validate fails
    with undeclared-variable errors unrelated to task 1.5, so that assertion
    skips rather than failing on another task's in-flight state.
    """
    if not tofu_available():
        return False
    return tofu_validate().returncode == 0


# ===========================================================================
# Additions for multi-workshop-provisioning Task 3.8
# (workshop_accounts / workshop_id validations + removed-variable supersession)
# ===========================================================================
#
# Pillar 2 replaces the baseline `idc_account_map` and the count/prefix/strategy
# generators with two explicit inputs:
#
#   * workshop_accounts: map(object({ groups = map(object({ user_count })) }))
#     with THREE validation blocks — 12-digit account key, non-empty group
#     name, and user_count in 0..500.
#   * workshop_id: a slug (1-63 lowercase alphanumeric + hyphens, begin/end
#     alphanumeric, no consecutive hyphens).
#
# `workshop_accounts` carries more than one validation block, so we select a
# block by a stable substring of its own error_message (never a hand-copied
# condition) and evaluate the real condition offline through `tofu console`,
# substituting the `var.<name>` reference with an HCL literal built from a
# Python value. True/False then matches whether a real plan would accept or
# reject that input.
#
# Removed-variable supersession is a pure text fact: the generator variables and
# idc_account_map no longer have `variable "<name>"` blocks, so any tfvars that
# still sets them references an undeclared variable. We assert the blocks are
# gone (so a reference "fails to resolve rather than silently taking effect")
# and, when tofu is available, that evaluating `var.<removed>` through the
# console errors because the variable is undeclared.

OBJ = object()  # sentinel so callers can pass a bare value where needed


def _hcl_literal(value) -> str:
    """Render a Python value as an OpenTofu/HCL expression literal.

    Supports the shapes the workshop_accounts fixtures use: str, int/float,
    bool, None (-> null), list, and dict (-> HCL object with quoted keys).
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, list):
        return "[" + ", ".join(_hcl_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        entries = ", ".join(
            f'{_hcl_literal(str(k))} = {_hcl_literal(v)}' for k, v in value.items()
        )
        return "{" + entries + "}"
    raise TypeError(f"cannot render {type(value)!r} as an HCL literal")


def _validation_blocks(var_name: str) -> list[str]:
    """Return the source of every ``validation { ... }`` block of a variable."""
    block = variable_block(var_name)
    blocks: list[str] = []
    for m in re.finditer(r"validation\s*{", block):
        brace = block.index("{", m.start())
        depth = 0
        for i in range(brace, len(block)):
            if block[i] == "{":
                depth += 1
            elif block[i] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(block[m.start() : i + 1])
                    break
    return blocks


def validation_block_by_message(var_name: str, message_substring: str) -> str:
    """Return the single validation block whose error_message contains the hint.

    `workshop_accounts` carries multiple validation blocks; selecting by a
    stable fragment of the block's own error_message keeps the offline rule
    check pinned to the right rule without hand-copying the condition.
    """
    matches = [
        b for b in _validation_blocks(var_name) if message_substring in b
    ]
    if not matches:
        raise AssertionError(
            f'variable "{var_name}" has no validation block whose '
            f"error_message contains {message_substring!r}."
        )
    if len(matches) > 1:
        raise AssertionError(
            f'{message_substring!r} matched {len(matches)} validation blocks '
            f'on variable "{var_name}"; use a more specific substring.'
        )
    return matches[0]


def _condition_of(block: str) -> str:
    """Pull the ``condition = <expr>`` out of one validation block.

    The condition may span several lines (the workshop_accounts rules use
    multi-line ``alltrue(flatten([...]))`` expressions), so we take everything
    from ``condition =`` up to the ``error_message =`` line that follows it.
    """
    m = re.search(r"condition\s*=\s*(.+?)\n\s*error_message\s*=", block, re.DOTALL)
    if not m:
        raise AssertionError("validation block has no condition before error_message")
    return m.group(1).strip()


def _console_bool(expr: str) -> bool:
    """Evaluate a pure boolean expression via ``tofu console``."""
    return tofu_console_eval(expr) == "true"


def workshop_accounts_rule_accepts(message_substring: str, accounts: dict) -> bool:
    """Evaluate one workshop_accounts validation rule over a concrete map.

    Selects the rule by its error_message hint, reads the real condition from
    variables.tf, substitutes the `var.workshop_accounts` reference with an HCL
    literal built from ``accounts``, and evaluates it offline. True == the rule
    would accept the input; False == the rule would reject it.
    """
    block = validation_block_by_message("workshop_accounts", message_substring)
    condition = _condition_of(block)
    expr = condition.replace("var.workshop_accounts", _hcl_literal(accounts))
    return _console_bool(expr)


def workshop_accounts_accepts(accounts: dict) -> bool:
    """True iff a map passes ALL of workshop_accounts' validation rules."""
    return all(
        workshop_accounts_rule_accepts(hint, accounts)
        for hint in (
            "12-digit AWS account id",
            "group name",
            "user_count",
        )
    )


def workshop_id_accepts(value: str) -> bool:
    """Evaluate the real workshop_id slug condition over a concrete value."""
    condition = extract_validation_condition("workshop_id")
    expr = condition.replace("var.workshop_id", _hcl_literal(value))
    return _console_bool(expr)


# ---- Removed-variable supersession ----------------------------------------

# The generators and idc_account_map that Pillar 2 removed. A tfvars that still
# sets any of these now references an UNDECLARED variable.
REMOVED_SUBSCRIPTION_VARS = (
    "user_count",
    "group_count",
    "user_prefix",
    "group_prefix",
    "sequence_start",
    "sequence_padding",
    "membership_strategy",
    "user_emails",
    "display_name_template",
    "idc_account_map",
)


def variable_declared(name: str) -> bool:
    """True when ``variable "<name>" { ... }`` still exists in variables.tf."""
    return f'variable "{name}"' in read_variables_tf()


def console_reference_resolves(name: str) -> bool:
    """True when ``var.<name>`` resolves in ``tofu console`` (i.e. is declared).

    A reference to an undeclared variable makes `tofu console` exit non-zero;
    we surface that as False so the test can assert a removed variable no longer
    resolves (its tfvars value would be ignored / rejected, not silently applied).
    """
    proc = subprocess.run(
        ["tofu", "console", "-no-color"],
        cwd=_initialized_tf_dir(),
        input=f"var.{name}\n",
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0
