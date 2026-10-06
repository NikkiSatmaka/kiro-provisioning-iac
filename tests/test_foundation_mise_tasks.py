"""Text-fact + example/fail-closed tests for the foundation mise tasks.

Feature: foundation-idc-service, Task 5.7
Validates: Requirements 4.6, 4.7, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.4, 7.7

Pillar 3 adds the three ``mise`` lifecycle tasks for the foundation stack:
``foundation-plan`` / ``foundation-apply`` / ``foundation-destroy``.
``foundation-plan`` and ``foundation-apply`` run in ``foundation/terraform``,
guard ``backend.hcl`` (existence + residual ``key =``), and supply the
foundation state key at init time via
``-backend-config="key=foundation/terraform.tfstate"``.
``foundation-destroy`` is a **documented no-op**: the stack adopts the
organization IdC instance read-only and owns nothing to destroy, so the task
runs no tofu, inits no backend, and deletes nothing (disabling IdC is a
management-account console action, never a repo task).

This suite pins that contract at two levels:

* **Text facts** (parse ``mise.toml`` with ``tomllib``) — the plan/apply tasks
  exist, run in the foundation stack dir, carry the init-time foundation key,
  and run the right ``tofu`` verb (``plan`` / ``apply``); foundation-destroy is
  a no-op that runs no tofu. It also pins the per-workshop isolation: NO
  ``provision*`` / ``teardown*`` / ``claim-*`` task references
  ``foundation/terraform.tfstate`` or ``awscc_sso_instance`` (R7.1, R7.7).
* **Example / fail-closed shell runs** — the guard bodies are executed with
  ``sh`` in a throwaway dir with a ``tofu`` stub on PATH that records every call.
  A missing ``backend.hcl`` exits non-zero naming the file (R4.6); a residual
  ``key =`` line exits non-zero (R4.7); foundation-destroy exits zero and NEVER
  reaches tofu (R7.4).

Everything runs offline: the ``tofu`` stub makes real init/plan/apply/destroy
calls unreachable, so the only thing under test is the guard logic that fails
closed BEFORE ``tofu`` would mutate anything.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MISE_TOML = REPO_ROOT / "mise.toml"

# The init-time key every foundation task must supply (R6.4). Because the IdC
# instance is a single shared resource, the key is the bare, prefix-free
# ``foundation/terraform.tfstate`` (no ``workshops/<id>/`` segment).
FOUNDATION_KEY = "foundation/terraform.tfstate"
INIT_KEY_ARG = f'-backend-config="key={FOUNDATION_KEY}"'

FOUNDATION_TASKS = ("foundation-plan", "foundation-apply", "foundation-destroy")

# The mutating-against-the-backend tasks. foundation-destroy is deliberately
# NOT here: foundation adopts the org IdC instance read-only and owns nothing to
# destroy, so foundation-destroy is a documented no-op that runs no tofu, inits
# no backend, and guards nothing. These are the tasks that DO init the backend
# and run a tofu verb.
FOUNDATION_TOFU_TASKS = ("foundation-plan", "foundation-apply")

# tofu verb each backend-initializing foundation task runs after a clean init.
TASK_VERB = {
    "foundation-plan": "tofu plan",
    "foundation-apply": "tofu apply",
}


def _load_tasks() -> dict:
    """Return the ``[tasks.*]`` table parsed from ``mise.toml``."""
    with MISE_TOML.open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("tasks", {})


def _task_run(name: str) -> str:
    """Return the ``run`` body of a named task."""
    tasks = _load_tasks()
    assert name in tasks, f"mise.toml declares no [tasks.{name}]"
    run = tasks[name].get("run")
    assert isinstance(run, str), f"task {name} has no string `run` body"
    return run


# --- R6.1/R6.2/R6.3/R6.4: the three tasks exist, keyed, right verb ----------


@pytest.mark.parametrize("name", FOUNDATION_TASKS)
def test_foundation_task_exists_in_foundation_dir(name):
    """Each foundation task exists and runs in ``foundation/terraform`` (R6.1-6.3).

    The three lifecycle tasks mirror the sibling stacks' plan/apply/destroy
    conventions and must run against the foundation stack directory.
    """
    tasks = _load_tasks()
    assert name in tasks, f"mise.toml declares no [tasks.{name}]"
    assert tasks[name].get("dir") == "foundation/terraform", (
        f"task {name} does not run in foundation/terraform"
    )


@pytest.mark.parametrize("name", FOUNDATION_TOFU_TASKS)
def test_foundation_task_supplies_init_time_key(name):
    """Each foundation task passes the foundation key at ``tofu init`` (R6.4).

    The state path is NOT in backend.hcl; every task supplies it via
    ``-backend-config="key=foundation/terraform.tfstate"`` so init targets the
    one shared, prefix-free foundation state object.
    """
    run = _task_run(name)
    assert "tofu init -reconfigure" in run, (
        f"task {name} does not run `tofu init -reconfigure` before mutating"
    )
    assert INIT_KEY_ARG in run, (
        f"task {name} does not supply the init-time key {INIT_KEY_ARG!r}"
    )


@pytest.mark.parametrize("name", FOUNDATION_TOFU_TASKS)
def test_foundation_task_runs_expected_verb(name):
    """Each foundation task runs its expected ``tofu`` verb (R6.1-6.3).

    plan runs ``tofu plan`` (changes nothing), apply runs ``tofu apply``, and
    destroy runs ``tofu destroy`` — each after a clean init.
    """
    run = _task_run(name)
    verb = TASK_VERB[name]
    assert verb in run, f"task {name} does not run `{verb}`"


# --- R4.6/R4.7: both guards present in every foundation task ----------------


@pytest.mark.parametrize("name", FOUNDATION_TOFU_TASKS)
def test_foundation_task_guards_backend_hcl(name):
    """Each foundation task guards backend.hcl existence + residual key (R4.6, R4.7).

    A missing backend.hcl must stop with a message naming the file; a residual
    ``key =`` must stop with the init-time-key message. Both guards run before
    any ``tofu init``.
    """
    run = _task_run(name)
    assert "if [ ! -f backend.hcl ]" in run, (
        f"task {name} does not guard a missing backend.hcl (R4.6)"
    )
    assert "backend.hcl not found" in run, (
        f"task {name} missing-file message does not name backend.hcl (R4.6)"
    )
    assert "key[[:space:]]*=" in run, (
        f"task {name} does not grep backend.hcl for a residual `key =` (R4.7)"
    )
    assert "remove the 'key' line from backend.hcl" in run, (
        f"task {name} does not error on a residual key (R4.7)"
    )


# --- R6.5: init failure is fail-closed --------------------------------------


@pytest.mark.parametrize("name", FOUNDATION_TOFU_TASKS)
def test_foundation_task_fails_closed_on_init(name):
    """A non-zero ``tofu init`` stops the task before plan/apply/destroy (R6.5).

    ``set -eu`` plus the explicit ``|| { ...; exit 1; }`` on init guarantees the
    task never reaches its mutating verb after a failed init.
    """
    run = _task_run(name)
    assert run.lstrip().startswith("set -eu"), (
        f"task {name} does not start with `set -eu` (fail-closed, R6.5)"
    )
    assert "backend init failed" in run, (
        f"task {name} does not fail closed on a non-zero `tofu init` (R6.5)"
    )


# --- R7.2/R7.4: the typed-phrase guard on destroy ---------------------------


def test_foundation_destroy_is_a_documented_no_op():
    """``foundation-destroy`` is a documented no-op that runs no tofu (R7.2, R7.4).

    Foundation adopts the organization IdC instance read-only and owns nothing
    to destroy, so the task must NOT run ``tofu destroy`` (or any tofu verb),
    must NOT init a backend, and must say it deletes nothing.
    """
    run = _task_run("foundation-destroy")
    assert "tofu destroy" not in run, (
        "foundation-destroy must not run `tofu destroy` (it owns nothing)"
    )
    assert "tofu init" not in run, (
        "foundation-destroy must not init a backend (it is a no-op)"
    )
    assert "tofu apply" not in run and "tofu plan" not in run, (
        "foundation-destroy must run no tofu verb"
    )
    assert "no-op" in run, (
        "foundation-destroy must document that it is a no-op that deletes nothing"
    )


# --- R7.1/R7.7: per-workshop isolation --------------------------------------


def _per_workshop_task_names() -> list[str]:
    """Every provision*/teardown*/claim-* task name declared in mise.toml."""
    names = [
        n
        for n in _load_tasks()
        if n.startswith(("provision", "teardown", "claim-"))
    ]
    assert names, "expected some provision*/teardown*/claim-* tasks in mise.toml"
    return names


@pytest.mark.parametrize("name", _per_workshop_task_names())
def test_per_workshop_task_never_references_foundation(name):
    """No per-workshop task touches the foundation state or resource (R7.1, R7.7).

    The shared IdC instance is excluded from the per-workshop lifecycle: no
    ``provision*`` / ``teardown*`` / ``claim-*`` task may reference the
    foundation state key or the ``awscc_sso_instance`` resource, so a routine
    provision/teardown can never create or delete it.
    """
    run = _task_run(name)
    assert FOUNDATION_KEY not in run, (
        f"per-workshop task {name} references the foundation state key "
        f"{FOUNDATION_KEY!r} (R7.1, R7.7)"
    )
    assert "awscc_sso_instance" not in run, (
        f"per-workshop task {name} references awscc_sso_instance (R7.1, R7.7)"
    )


# ===========================================================================
# Example / fail-closed shell runs
# ===========================================================================
#
# The guard bodies are run with ``sh`` in a throwaway ``foundation/terraform``
# directory. A ``tofu`` stub on PATH records every invocation to a log file, so
# a test can prove ``tofu`` (and specifically ``tofu destroy``) was never
# reached. The stub exits 0, so if a guard failed to stop the task the ``tofu``
# call WOULD be logged — the absence of the log is the assertion.


_TOFU_STUB = """#!/bin/sh
# Record each tofu invocation so the test can assert what (if anything) ran.
printf '%s\\n' "$*" >> "$TOFU_LOG"
exit 0
"""


def _run_guard(body: str, *, backend_hcl: str | None, stdin: str = "") -> tuple:
    """Run a task ``run`` body under ``sh`` in an isolated foundation dir.

    A ``tofu`` stub is placed first on PATH and logs its args to ``$TOFU_LOG``.
    ``backend.hcl`` is written only when ``backend_hcl`` is not None (None models
    the missing-file case). Returns ``(returncode, stdout, stderr, tofu_calls)``
    where ``tofu_calls`` is the list of logged ``tofu`` invocations.
    """
    with tempfile.TemporaryDirectory(prefix="foundation-guard-") as tmp:
        tmpdir = Path(tmp)

        # A fake foundation/terraform working dir.
        work = tmpdir / "work"
        work.mkdir()
        if backend_hcl is not None:
            (work / "backend.hcl").write_text(backend_hcl)

        # A bin/ dir holding the tofu stub, placed first on PATH.
        bindir = tmpdir / "bin"
        bindir.mkdir()
        stub = bindir / "tofu"
        stub.write_text(_TOFU_STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        tofu_log = tmpdir / "tofu.log"

        env = dict(os.environ)
        env["PATH"] = f"{bindir}{os.pathsep}" + env.get("PATH", "")
        env["TOFU_LOG"] = str(tofu_log)

        proc = subprocess.run(
            ["sh", "-c", body],
            cwd=work,
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )

        calls = (
            tofu_log.read_text().splitlines() if tofu_log.exists() else []
        )
        return proc.returncode, proc.stdout, proc.stderr, calls


@pytest.mark.parametrize("name", FOUNDATION_TOFU_TASKS)
def test_missing_backend_hcl_exits_nonzero_naming_file(name):
    """A foundation tofu task with no backend.hcl exits non-zero naming it (R4.6).

    The existence guard stops the task before init; the error names the missing
    file so the operator knows what to bootstrap. foundation-destroy is excluded:
    it is a no-op that inits no backend.
    """
    body = _task_run(name)

    rc, _out, err, calls = _run_guard(body, backend_hcl=None, stdin="")

    assert rc != 0, f"{name} did not fail on a missing backend.hcl"
    assert "backend.hcl" in err, (
        f"{name} error does not name the missing backend.hcl: {err!r}"
    )
    assert calls == [], (
        f"{name} reached tofu despite a missing backend.hcl: {calls}"
    )


@pytest.mark.parametrize("name", FOUNDATION_TOFU_TASKS)
def test_residual_key_in_backend_hcl_exits_nonzero(name):
    """A backend.hcl with a residual ``key =`` line exits non-zero (R4.7).

    The residual-key guard stops the task before init; a stray key would
    otherwise conflict with the init-time foundation key. foundation-destroy is
    excluded: it is a no-op that inits no backend.
    """
    body = _task_run(name)
    stdin = ""

    backend_hcl = (
        'bucket         = "kiro-tofu-state-000000000000"\n'
        'region         = "us-east-1"\n'
        'dynamodb_table = "kiro-tofu-locks"\n'
        "encrypt        = true\n"
        'key            = "foundation/terraform.tfstate"\n'  # the residual key
    )

    rc, _out, err, calls = _run_guard(body, backend_hcl=backend_hcl, stdin=stdin)

    assert rc != 0, f"{name} did not fail on a residual key in backend.hcl"
    assert "key" in err.lower(), (
        f"{name} error does not mention the residual key: {err!r}"
    )
    assert calls == [], (
        f"{name} reached tofu despite a residual key in backend.hcl: {calls}"
    )


def test_destroy_is_a_no_op_that_never_reaches_tofu():
    """foundation-destroy runs cleanly and never invokes tofu (R7.4).

    Foundation adopts the org IdC instance read-only, so the task owns nothing
    to destroy: running it must exit zero and never log a single tofu call,
    whether or not a backend.hcl is present. The absence of any logged tofu call
    is the assertion that it deletes nothing.
    """
    body = _task_run("foundation-destroy")

    # Even with a valid, keyless backend.hcl present, no tofu runs: the task is
    # a plain no-op that prints an explanation and exits.
    backend_hcl = (
        'bucket         = "kiro-tofu-state-000000000000"\n'
        'region         = "us-east-1"\n'
        'dynamodb_table = "kiro-tofu-locks"\n'
        "encrypt        = true\n"
    )

    rc, _out, _err, calls = _run_guard(body, backend_hcl=backend_hcl, stdin="")

    assert rc == 0, "foundation-destroy (a no-op) should exit cleanly"
    assert calls == [], (
        f"foundation-destroy is a no-op but reached tofu: {calls}"
    )
