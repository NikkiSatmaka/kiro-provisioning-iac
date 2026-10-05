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
