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

import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SCRIPT = REPO_ROOT / "backend" / "scripts" / "destroy_workshop_state.sh"

MISE_TOML = REPO_ROOT / "mise.toml"

# The shared helper library the long task bodies source.
LIB_PATH = REPO_ROOT / "scripts" / "mise-tasks.sh"
LIB_SOURCE_LINE = ". ../../scripts/mise-tasks.sh"

TASK_NAME = "backend-destroy-workshop"


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


# ===========================================================================
# FEAT-002: task-registration assertions (parse mise.toml)
# ===========================================================================


def _load_tasks() -> dict:
    """Return the ``[tasks.*]`` table parsed from ``mise.toml``."""
    with MISE_TOML.open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("tasks", {})


def _task(name: str) -> dict:
    tasks = _load_tasks()
    assert name in tasks, f"mise.toml declares no [tasks.{name}]"
    return tasks[name]


def _task_run(name: str) -> str:
    run = _task(name).get("run")
    assert isinstance(run, str), f"task {name} has no string `run` body"
    return run


def test_task_registered_in_backend_dir():
    """``backend-destroy-workshop`` exists and runs in ``backend/terraform``."""
    assert _task(TASK_NAME).get("dir") == "backend/terraform", (
        f"task {TASK_NAME} does not run in backend/terraform"
    )


def test_task_description_states_scope_and_contrast():
    """The description pins the purge scope, WORKSHOP_ID need, and contrast."""
    desc = _task(TASK_NAME).get("description", "")
    assert "workshops/" in desc, (
        "description does not name the workshops/<WID>/ purge scope"
    )
    assert "backend-destroy" in desc, (
        "description does not contrast with backend-destroy"
    )
    assert "WORKSHOP_ID" in desc, (
        "description does not state the WORKSHOP_ID requirement"
    )


def test_task_body_sources_lib_and_guards_workshop_id():
    """The body sources the shared lib and runs the WORKSHOP_ID guard."""
    run = _task_run(TASK_NAME)
    assert LIB_SOURCE_LINE in run, (
        f"task {TASK_NAME} does not source {LIB_SOURCE_LINE!r}"
    )
    assert "require_workshop_id" in run, (
        f"task {TASK_NAME} does not call require_workshop_id"
    )


def test_task_resolves_bucket_table_from_tofu_outputs():
    """The body resolves the bucket + table from the backend stack outputs.

    The backend/ stack is the bootstrap stack (LOCAL state, no backend.hcl of its
    own), so the purge must read the shared bucket + lock table from THIS stack's
    own Terraform outputs — never from a phantom backend.hcl. Assert the body
    reads both outputs, exports them for the script, and no longer references the
    backend.hcl-based guards (require_backend_hcl / reject_residual_key).
    """
    run = _task_run(TASK_NAME)
    assert "tofu output -raw state_bucket_name" in run, (
        f"task {TASK_NAME} does not read state_bucket_name from tofu output"
    )
    assert "tofu output -raw lock_table_name" in run, (
        f"task {TASK_NAME} does not read lock_table_name from tofu output"
    )
    assert "STATE_BUCKET" in run and "LOCK_TABLE" in run, (
        f"task {TASK_NAME} does not pass STATE_BUCKET/LOCK_TABLE to the script"
    )
    assert "require_backend_hcl" not in run, (
        f"task {TASK_NAME} must not call require_backend_hcl (no backend.hcl here)"
    )
    assert "reject_residual_key" not in run, (
        f"task {TASK_NAME} must not call reject_residual_key (no backend.hcl here)"
    )


def test_task_invokes_cleanup_script():
    """The body invokes FEAT-001's script via the backend/scripts/ rel path."""
    run = _task_run(TASK_NAME)
    assert "../scripts/destroy_workshop_state.sh" in run, (
        f"task {TASK_NAME} does not invoke ../scripts/destroy_workshop_state.sh"
    )


def test_typed_phrase_gate_only_in_apply_branch():
    """``require_typed_phrase`` appears ONLY inside the APPLY=1 branch.

    The script must stay non-interactive, so the typed-phrase gate belongs to
    the mise task and only on the mutating path. Assert the phrase occurs after
    the APPLY branch opens and that the gated ``--apply`` invocation is present.
    """
    run = _task_run(TASK_NAME)
    assert run.count("require_typed_phrase") == 1, (
        f"task {TASK_NAME} should gate exactly once, in the APPLY branch"
    )
    apply_idx = run.find('"${APPLY:-0}" = "1"')
    assert apply_idx != -1, f"task {TASK_NAME} has no APPLY=1 branch"
    gate_idx = run.find("require_typed_phrase")
    assert gate_idx > apply_idx, (
        "require_typed_phrase must appear inside the APPLY branch, not before it"
    )
    assert 'require_typed_phrase "destroy-workshop-state" "deleting nothing."' in run, (
        f"task {TASK_NAME} does not use the expected typed phrase"
    )
    assert '../scripts/destroy_workshop_state.sh "$WID" --apply' in run, (
        f"task {TASK_NAME} does not invoke the script with --apply when mutating"
    )


# ===========================================================================
# FEAT-002: fail-closed sh harness (offline, no tofu/aws)
# ===========================================================================
#
# Execute the real task body (with the shared library sourced by absolute path)
# under ``sh`` in a throwaway working dir. A ``require_workshop_id`` failure or a
# missing ``backend.hcl`` must stop the task before it would ever reach the
# cleanup script. A ``destroy_workshop_state.sh`` stub on PATH-adjacent rel path
# is NOT needed: the guards fail before the script is invoked.


def _run_task_body(body: str, *, backend_hcl: str | None, env_extra: dict) -> tuple:
    """Run a task ``run`` body under ``sh`` in an isolated backend/terraform dir.

    The body sources the shared helper via ``. ../../scripts/mise-tasks.sh``; it
    is rewritten to source the REAL library by absolute path since the temp
    ``work/`` dir has no ``scripts/`` sibling. ``backend.hcl`` is written only
    when ``backend_hcl`` is not None. Returns ``(returncode, stdout, stderr)``.
    """
    body = body.replace(LIB_SOURCE_LINE, f". {LIB_PATH}")
    with tempfile.TemporaryDirectory(prefix="destroy-ws-guard-") as tmp:
        work = Path(tmp) / "work"
        work.mkdir()
        if backend_hcl is not None:
            (work / "backend.hcl").write_text(backend_hcl)

        env = dict(os.environ)
        # Scrub any inherited WORKSHOP_ID so env_extra is authoritative.
        env.pop("WORKSHOP_ID", None)
        env.update(env_extra)

        proc = subprocess.run(
            ["sh", "-c", body],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr


def test_task_fails_closed_without_workshop_id():
    """WORKSHOP_ID unset -> non-zero exit naming WORKSHOP_ID, before any work."""
    body = _task_run(TASK_NAME)
    rc, _out, err = _run_task_body(body, backend_hcl=None, env_extra={})
    assert rc != 0, "task did not fail with WORKSHOP_ID unset"
    assert "WORKSHOP_ID is required" in err, (
        f"error does not name the missing WORKSHOP_ID: {err!r}"
    )


def test_script_fails_closed_without_bucket_table_env():
    """The script fails closed (naming the env contract) when bucket/table unset.

    The purge now reads STATE_BUCKET/LOCK_TABLE from the environment (resolved by
    the task from the backend stack outputs). With a valid workshop id but
    neither var set, the script must exit non-zero before touching AWS and name
    the missing contract — no tofu/AWS needed to prove the fail-closed guard.
    """
    env = dict(os.environ)
    for _var in ("STATE_BUCKET", "LOCK_TABLE"):
        env.pop(_var, None)
    proc = subprocess.run(
        ["sh", str(SCRIPT), "kiro-2025-10-10"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode != 0, "script did not fail with STATE_BUCKET/LOCK_TABLE unset"
    assert "STATE_BUCKET and LOCK_TABLE" in proc.stderr, (
        f"error does not name the missing env contract: {proc.stderr!r}"
    )
