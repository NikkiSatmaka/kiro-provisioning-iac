"""Lint/parse tests for the per-workshop state cleanup script.

Feature: backend-destroy-workshop, FEAT-001

Root-suite text-fact tests (same style as ``test_keyless_backend.py``) that pin
the cleanup engine's *shape* with no AWS/toolchain:

* the script ``backend/scripts/destroy_workshop_state.sh`` exists;
* it parses as POSIX ``sh`` (``sh -n`` returncode 0 — proves no bashisms break
  under ``sh``);
* ``shellcheck -s sh`` is clean WHEN shellcheck is installed, and the case
  SKIPS cleanly when it is not (shellcheck is not on this project's PATH);
* a regression guard proving the ``MUTATING_TASKS`` tuple in
  ``test_keyless_backend.py`` is left EXACTLY the four tofu-mutating tasks and
  does NOT gain ``backend-destroy-workshop`` (this task runs no ``tofu``, so it
  must never join that contract).

Task-registration assertions about the mise block live with FEAT-002; this
module stays green on its own.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SCRIPT = REPO_ROOT / "backend" / "scripts" / "destroy_workshop_state.sh"


def test_script_exists():
    """The cleanup script is present at the expected path."""
    assert SCRIPT.exists(), f"cleanup script missing: {SCRIPT}"


def test_script_passes_sh_n():
    """The script parses as POSIX ``sh`` (no bashisms break under ``sh -n``)."""
    proc = subprocess.run(
        ["sh", "-n", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"`sh -n` rejected the script:\n{proc.stdout}\n{proc.stderr}"
    )


@pytest.mark.skipif(
    shutil.which("shellcheck") is None, reason="shellcheck not on PATH"
)
def test_script_shellcheck_clean():
    """``shellcheck -s sh`` is clean (skips when shellcheck is absent)."""
    proc = subprocess.run(
        ["shellcheck", "-s", "sh", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"shellcheck flagged the script:\n{proc.stdout}\n{proc.stderr}"
    )


def test_mutating_tasks_tuple_excludes_this_task():
    """``MUTATING_TASKS`` stays the four tofu tasks; this task is NOT added.

    ``backend-destroy-workshop`` runs no ``tofu`` (no init/reconfigure/apply),
    so it must never join the init-time-key contract pinned in
    ``test_keyless_backend.py``. Import the tuple and assert it is exactly the
    four tofu-mutating tasks and does not contain this task — a regression guard
    that keeps FEAT-001 independent of the ``MUTATING_TASKS`` contract.
    """
    from test_keyless_backend import MUTATING_TASKS

    assert MUTATING_TASKS == (
        "subscription-apply",
        "subscription-destroy",
        "claim-deploy",
        "claim-destroy",
    )
    assert "backend-destroy-workshop" not in MUTATING_TASKS
