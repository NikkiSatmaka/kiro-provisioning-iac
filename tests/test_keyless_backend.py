"""Smoke/integration tests for the keyless backend.hcl + init-time state key.

Feature: multi-workshop-provisioning, Task 5.6
Validates: Requirements 5.4, 5.5, 5.6, 5.9

Pillar 3 moves the per-workshop state path out of a static ``backend.hcl`` and
into an init-time flag. The ``key`` is removed from every stack's
``backend.hcl`` (and its tracked ``.example`` template) and from the rendered
backend body in ``backend/terraform/outputs.tf``; the mise mutating tasks then
supply it per workshop via
``tofu init -reconfigure -backend-config=backend.hcl -backend-config="key=workshops/<id>/<stack>/terraform.tfstate"``.

This suite pins that contract across the layers it can check reliably offline:

* R5.4 / R5.5 — every backend config (``subscription`` + ``claim-service``,
  both ``backend.hcl`` and ``backend.hcl.example``) omits a ``key =`` line and
  retains only the shared, non-secret values (bucket, region, dynamodb_table,
  encrypt). The tracked ``.example`` templates MUST exist; the git-ignored
  ``backend.hcl`` files are checked when present and skipped when absent.
* R5.5 — the rendered ``_backend_hcl_body`` in ``backend/terraform/outputs.tf``
  omits ``key`` and carries only bucket/region/dynamodb_table/encrypt (a static
  text fact that holds with no toolchain).
* R5.6 — the init-time key mechanism: the mise mutating tasks pass
  ``-backend-config="key=workshops/${WID}/<stack>/terraform.tfstate"`` at init.
  A full ``tofu init`` against S3 needs AWS/network, so the mechanism is checked
  statically; a lightweight ``tofu init -backend=false`` on a fixture proves the
  keyless config parses without a ``key`` when a ``tofu`` binary is on PATH, and
  skips cleanly when it is not.
* R5.9 — the mutating tasks grep ``backend.hcl`` for a residual ``key =`` and
  fail closed before init, so a stray key never reaches init.

Everything degrades cleanly: the static text-fact assertions always run; the
single ``tofu``-backed smoke skips when no ``tofu`` binary is present.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# The two stacks' backend configs. The ``.example`` templates are tracked and
# MUST exist; the bare ``backend.hcl`` files are git-ignored and may be absent
# on a fresh clone (checked when present, skipped when not).
BACKEND_EXAMPLES = (
    REPO_ROOT / "subscription" / "terraform" / "backend.hcl.example",
    REPO_ROOT / "claim-service" / "terraform" / "backend.hcl.example",
)
BACKEND_HCLS = (
    REPO_ROOT / "subscription" / "terraform" / "backend.hcl",
    REPO_ROOT / "claim-service" / "terraform" / "backend.hcl",
)

BACKEND_OUTPUTS_TF = REPO_ROOT / "backend" / "terraform" / "outputs.tf"
MISE_TOML = REPO_ROOT / "mise.toml"

# The shared helper library the long task bodies source. The keyed init-time arg
# and the residual-key grep were extracted here from the per-workshop mutating
# tasks (tofu_init_keyed / reject_residual_key), so the text facts R5.6/R5.9 now
# live in this library rather than inline. The tests below assert against the
# COMPOSITION of lib + task block — the same treatment as the foundation pinned
# test — so they keep validating the identical contract against the new
# structure without weakening any assertion.
LIB_PATH = REPO_ROOT / "scripts" / "mise-tasks.sh"

# The relative source line every long task body uses to pull in the helpers.
# Task dirs are uniformly two levels deep, so this resolves to LIB_PATH.
LIB_SOURCE_LINE = ". ../../scripts/mise-tasks.sh"


def _task_block(task: str) -> str:
    """Return the raw ``[tasks.<task>]`` text block from mise.toml."""
    toml = MISE_TOML.read_text()
    start = toml.index(f"[tasks.{task}]")
    # The next task header (or EOF) bounds this task's block.
    nxt = toml.find("\n[tasks.", start + 1)
    return toml[start : nxt if nxt != -1 else len(toml)]


def _task_block_resolved(task: str) -> str:
    """Return a task block with the sourced helper library text inlined.

    The keyed ``tofu init`` and the residual-key grep now live in
    ``scripts/mise-tasks.sh``; replacing the ``. ../../scripts/mise-tasks.sh``
    source line with the full library text yields the composition a shell
    actually runs, so the text-fact assertions still pin the real behavior.
    """
    block = _task_block(task)
    assert LIB_SOURCE_LINE in block, (
        f"task {task} does not source the shared helper library "
        f"({LIB_SOURCE_LINE!r}); the refactor expects it to"
    )
    return block.replace(LIB_SOURCE_LINE, LIB_PATH.read_text())

# Matches a ``key = ...`` setting at the start of a line (ignoring leading
# whitespace), i.e. an HCL ``key`` argument — not a commented ``# ... key ...``
# mention. This is the exact shape the mise residual-key guard greps for.
KEY_LINE = re.compile(r"^\s*key\s*=", re.MULTILINE)

# The mutating mise tasks that must supply the init-time key per workshop (R5.6)
# and guard against a residual key in backend.hcl (R5.9).
MUTATING_TASKS = ("subscription-apply", "subscription-destroy", "claim-deploy", "claim-destroy")


def _tofu_available() -> bool:
    return shutil.which("tofu") is not None


requires_tofu = pytest.mark.skipif(
    not _tofu_available(), reason="tofu binary not on PATH"
)


def _strip_hcl_comments(text: str) -> str:
    """Drop ``#`` and ``//`` line comments so a key *mention* in prose/comments
    is never mistaken for an actual ``key =`` setting."""
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("#", "//")):
            continue
        # Trim a trailing inline comment, but keep quoted ``#`` untouched by
        # only cutting at a ``#`` that is not inside quotes (the backend configs
        # never quote a ``#``, so a plain split is safe here).
        for marker in ("#", "//"):
            idx = line.find(marker)
            if idx != -1:
                line = line[:idx]
        out.append(line)
    return "\n".join(out)


# --- R5.4 / R5.5: no key line in the backend configs ------------------------

@pytest.mark.parametrize(
    "path", BACKEND_EXAMPLES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_backend_example_exists_and_omits_key(path):
    """Each tracked backend.hcl.example exists and has no ``key =`` line (R5.4).

    The ``.example`` templates are tracked, so they must exist; a key setting
    in the template would re-introduce the single-state-path pin the pillar
    removes.
    """
    assert path.exists(), f"tracked template missing: {path}"
    body = _strip_hcl_comments(path.read_text())
    assert KEY_LINE.search(body) is None, f"{path} still declares a `key =` line"


@pytest.mark.parametrize(
    "path", BACKEND_HCLS, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_backend_hcl_omits_key_when_present(path):
    """A bootstrapped (git-ignored) backend.hcl, if present, omits ``key`` (R5.4).

    ``backend.hcl`` is git-ignored and may be absent on a fresh clone; when it
    exists it must still carry no ``key =`` line so the init-time key is the
    sole source of the state path.
    """
    if not path.exists():
        pytest.skip(f"{path} not present (git-ignored; bootstrapped locally)")
    body = _strip_hcl_comments(path.read_text())
    assert KEY_LINE.search(body) is None, f"{path} still declares a `key =` line"


@pytest.mark.parametrize(
    "path", BACKEND_EXAMPLES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_backend_example_retains_only_shared_values(path):
    """The template carries only shared, non-secret backend values (R5.5).

    After the key is removed, the only settings that may appear are bucket,
    region, dynamodb_table, and encrypt. A ``bucket`` must be present (it is the
    one value every stack needs); any OTHER setting beyond the allowed set is a
    regression.
    """
    allowed = {"bucket", "region", "dynamodb_table", "encrypt"}
    body = _strip_hcl_comments(path.read_text())
    settings = {
        m.group(1)
        for m in re.finditer(r"(?m)^\s*([A-Za-z_]+)\s*=", body)
    }
    assert "bucket" in settings, f"{path} is missing the shared `bucket` value"
    assert settings <= allowed, (
        f"{path} declares unexpected backend settings: {settings - allowed}"
    )


# --- R5.5: the rendered backend body is keyless -----------------------------

def test_rendered_backend_body_omits_key_and_carries_only_shared_values():
    """``_backend_hcl_body`` renders a keyless body of the four shared values.

    The bootstrap writes each stack's backend.hcl from this heredoc, so the
    rendered body must itself omit ``key`` and carry only bucket, region,
    dynamodb_table, and encrypt (R5.5). Asserted as a static text fact so it
    holds with no toolchain.
    """
    text = BACKEND_OUTPUTS_TF.read_text()

    # Isolate the _backend_hcl_body heredoc (between <<-EOT and the closing EOT).
    m = re.search(r"_backend_hcl_body\s*=\s*<<-?EOT\n(.*?)\n\s*EOT", text, re.DOTALL)
    assert m, "could not locate the _backend_hcl_body heredoc in outputs.tf"
    body = m.group(1)

    assert KEY_LINE.search(body) is None, "rendered backend body still emits `key`"

    settings = {
        mm.group(1) for mm in re.finditer(r"(?m)^\s*([A-Za-z_]+)\s*=", body)
    }
    assert settings == {"bucket", "region", "dynamodb_table", "encrypt"}, (
        f"rendered body carries unexpected settings: {settings}"
    )


# --- R5.6 / R5.9: init-time key mechanism + residual-key guard --------------

@pytest.mark.parametrize("task", MUTATING_TASKS)
def test_mutating_task_supplies_init_time_key(task):
    """Each mutating mise task passes the init-time ``key=`` at ``tofu init`` (R5.6).

    The per-workshop state path is NOT in backend.hcl; it is supplied at init
    via ``-backend-config="key=workshops/${...}/<stack>/terraform.tfstate"``.

    The keyed ``tofu init`` now lives in the ``tofu_init_keyed`` helper, which
    each mutating task calls with its per-workshop state key as the first
    positional arg. Assert the mechanism against the lib+task composition: the
    helper runs ``tofu init -reconfigure`` and emits the keyed
    ``-backend-config="key=..."`` argument, and the task passes a
    ``workshops/<id>/<stack>/terraform.tfstate`` key — resolving a ``$SUB_KEY``
    style var back to its assignment — so both prove the SAME contract.
    """
    block = _task_block(task)
    resolved_block = _task_block_resolved(task)

    # The keyed init (and its -backend-config="key=..." arg) is emitted by the
    # sourced helper; assert it against the resolved lib+task composition.
    assert "tofu init -reconfigure" in resolved_block, (
        f"task {task} does not run `tofu init -reconfigure` before mutating"
    )
    assert '-backend-config="key=' in resolved_block, (
        f"task {task} does not pass -backend-config=\"key=...\" at init"
    )

    scoped_literal = r"workshops/\$\{?WID\}?/[a-z-]+/terraform\.tfstate"

    # The task supplies the state key as the first positional arg to
    # tofu_init_keyed. Two equivalent forms appear across the tasks: the
    # workshop-scoped path inline, or via a shell var (e.g. SUB_KEY) assigned
    # that path. Resolve a var reference back to its assignment so both forms
    # prove the SAME contract: key = workshops/<id>/<stack>/terraform.tfstate.
    m = re.search(r'tofu_init_keyed\s+"([^"]+)"', block)
    assert m, (
        f"task {task} does not call tofu_init_keyed with a state key"
    )
    key_expr = m.group(1)

    if re.fullmatch(scoped_literal, key_expr):
        resolved = key_expr
    else:
        # "$SUB_KEY" / "${SUB_KEY}" — resolve to the var's assignment.
        var = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", key_expr)
        assert var, (
            f"task {task} supplies an unexpected init-time key form: {key_expr!r}"
        )
        assign = re.search(
            rf'{var.group(1)}="(workshops/[^"]+)"', block
        )
        assert assign, (
            f"task {task} references key={key_expr!r} but does not assign it a "
            "workshops/<id>/<stack>/terraform.tfstate path"
        )
        resolved = assign.group(1)

    assert re.fullmatch(scoped_literal, resolved), (
        f"task {task} init-time key resolves to {resolved!r}, not the expected "
        "workshops/<id>/<stack>/terraform.tfstate scheme"
    )


@pytest.mark.parametrize("task", MUTATING_TASKS)
def test_mutating_task_rejects_residual_key_in_backend_hcl(task):
    """Each mutating task greps backend.hcl for a residual ``key =`` (R5.9).

    If a stray ``key`` survives in backend.hcl it would conflict with the
    init-time key, so every mutating task fails closed before init. We assert
    the guard greps for the same ``^\\s*key\\s*=`` shape and errors out.

    The residual-key guard now lives in the ``reject_residual_key`` helper, so
    assert against the resolved lib+task composition (see the module header).
    The task is also confirmed to CALL the guard, so the mechanism is wired.
    """
    block = _task_block(task)
    resolved_block = _task_block_resolved(task)

    # The task must invoke the extracted guard...
    assert "reject_residual_key" in block, (
        f"task {task} does not call reject_residual_key to fail closed on a "
        "residual key in backend.hcl"
    )
    # ...and the guard (now in the sourced lib) greps the same shape and errors.
    assert "key[[:space:]]*=" in resolved_block, (
        f"task {task} does not grep backend.hcl for a residual `key =`"
    )
    # The guard must error before init rather than warn-and-continue.
    assert re.search(r"remove the 'key' line from backend.hcl", resolved_block), (
        f"task {task} does not error on a residual key in backend.hcl"
    )


@requires_tofu
@pytest.mark.parametrize(
    "stack", ("subscription", "claim-service"), ids=("subscription", "claim-service")
)
def test_keyless_backend_config_parses_offline(stack):
    """A keyless backend.hcl parses at init without a ``key`` (R5.6, smoke).

    A full remote ``tofu init`` needs AWS/network/S3, which is out of scope for
    an offline suite. Instead we prove the config PARSES: copy the stack's
    backend.tf (the partial ``backend "s3" {}`` block) and a keyless backend.hcl
    into a throwaway dir and run ``tofu init -backend=false``. With
    ``-backend=false`` the backend is not actually initialized (no S3 call), but
    the backend block + ``-backend-config`` are still parsed, so a malformed or
    key-bearing config would surface here. The real per-workshop key is supplied
    at init time by the mise tasks (asserted above), never in the file.
    """
    stack_tf = REPO_ROOT / stack / "terraform"
    backend_tf = stack_tf / "backend.tf"
    assert backend_tf.exists(), f"{backend_tf} missing"

    # Prefer a bootstrapped backend.hcl; fall back to the tracked template with
    # its placeholders filled so init can parse concrete values offline.
    hcl_src = stack_tf / "backend.hcl"
    if hcl_src.exists():
        hcl_body = _strip_hcl_comments(hcl_src.read_text())
    else:
        hcl_body = (
            'bucket         = "kiro-tofu-state-000000000000"\n'
            'region         = "us-east-1"\n'
            'dynamodb_table = "kiro-tofu-locks"\n'
            "encrypt        = true\n"
        )
    # Guard the fixture itself: it must be keyless, matching the contract.
    assert KEY_LINE.search(hcl_body) is None

    with tempfile.TemporaryDirectory(prefix="keyless-backend-") as tmp:
        tmpdir = Path(tmp)
        # A minimal, provider-free config: just the partial backend block, so
        # `tofu init -backend=false` has nothing to download and stays offline.
        (tmpdir / "backend.tf").write_text(backend_tf.read_text())
        (tmpdir / "backend.hcl").write_text(hcl_body)

        proc = subprocess.run(
            [
                "tofu",
                "init",
                "-backend=false",
                "-input=false",
                "-no-color",
                "-backend-config=backend.hcl",
            ],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, (
            f"keyless backend config failed to parse at init for {stack}:\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
