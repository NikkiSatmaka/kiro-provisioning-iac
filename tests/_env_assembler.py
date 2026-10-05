"""Resolve the repository's environment the way the task layer assembles it.

Feature: idc-region-account-mapping, Task 1.3

The authoritative env assembler for every ``mise run`` task is the ``[env]``
block of the repository's root ``mise.toml`` (design: "Environment layer"). The
region split lives there:

    KIRO_REGION        = { default = "us-east-1" }
    IDC_REGION         = { default = "ap-southeast-1" }
    AWS_REGION         = "{{ env.IDC_REGION }}"          # tracks IDC_REGION
    AWS_DEFAULT_REGION = "{{ env.AWS_REGION }}"          # mirrors AWS_REGION

These tests exercise that *real* resolution rather than re-implementing it: we
read the actual ``[env]`` block out of the repo's ``mise.toml``, hand it to the
real ``mise`` template engine, and read back the resolved values. Reading the
block from the repo (never a hardcoded copy) means a regression that breaks the
``AWS_REGION`` tracking or the ``AWS_DEFAULT_REGION`` mirror in ``mise.toml``
fails these tests.

Why a throwaway temp config instead of the repo root directly: the repo's
``mise.toml`` does ``_.file = ".env"`` and the git-ignored ``.env`` pins
``IDC_REGION`` to a concrete value, which would always win over an injected
override — so a property over "any IDC_REGION" could never vary it. The temp
config carries only the ``[env]`` region block (no ``.env`` source), so an
ambient ``IDC_REGION`` in the child process is free to drive the template, which
is exactly the relationship Property 1 is about.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path

# Repo root is the parent of this tests/ directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
MISE_TOML = REPO_ROOT / "mise.toml"

# The region keys the split introduces / tracks. We extract exactly these from
# the repo's [env] block so the temp config mirrors the authoritative source
# without dragging in AWS_PROFILE, file paths, or the venv wiring.
REGION_ENV_KEYS = ("KIRO_REGION", "IDC_REGION", "AWS_REGION", "AWS_DEFAULT_REGION")


def mise_available() -> bool:
    """True when a ``mise`` binary is on PATH (tests skip cleanly if not)."""
    return shutil.which("mise") is not None


def read_mise_env_block() -> dict:
    """Return the raw ``[env]`` table from the repo's ``mise.toml``."""
    with MISE_TOML.open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("env", {})


def _region_env_toml() -> str:
    """Render an ``[env]`` block containing only the repo's region definitions.

    Pulls each of ``REGION_ENV_KEYS`` straight from the repo's ``mise.toml``
    ``[env]`` table and re-serializes it. ``{ default = "..." }`` tables are
    emitted as inline tables; plain template strings (``"{{ env.IDC_REGION }}"``)
    are emitted as quoted strings — matching how mise authored them.
    """
    block = read_mise_env_block()
    lines = ["[env]"]
    for key in REGION_ENV_KEYS:
        if key not in block:
            raise AssertionError(
                f"mise.toml [env] is missing {key!r}; the region split is "
                f"incomplete (expected one of {REGION_ENV_KEYS})."
            )
        value = block[key]
        if isinstance(value, dict):
            # e.g. { default = "us-east-1" }
            inner = ", ".join(f'{k} = "{v}"' for k, v in value.items())
            lines.append(f"{key} = {{ {inner} }}")
        else:
            # e.g. "{{ env.IDC_REGION }}"
            lines.append(f'{key} = "{value}"')
    return "\n".join(lines) + "\n"


def resolve_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Resolve the region env through the real mise template engine.

    Builds a trusted throwaway ``mise.toml`` carrying only the repo's region
    ``[env]`` definitions, runs ``mise env --json`` inside it with ``overrides``
    applied to the child environment, and returns the resolved variables.

    ``overrides`` (e.g. ``{"IDC_REGION": "eu-west-9"}``) are injected into the
    child process environment; mise's ``default = ...`` keeps any provided value
    and the ``{{ env.* }}`` templates resolve against it — the same way a shell
    export or ``.env`` entry would drive a real ``mise run``.
    """
    assert mise_available(), "mise is required to resolve the task-layer env"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config = tmp_path / "mise.toml"
        config.write_text(_region_env_toml())

        child_env = dict(os.environ)
        # Strip any region vars inherited from the runner so only the overrides
        # (or mise defaults) drive resolution; otherwise an ambient AWS_REGION
        # from the shell/CI could mask the template.
        for key in REGION_ENV_KEYS:
            child_env.pop(key, None)
        if overrides:
            child_env.update(overrides)
        # Don't let a stale global config or an ambient MISE_ENV perturb the
        # isolated resolution.
        child_env.pop("MISE_ENV", None)

        # Trust the throwaway config so `mise env` will evaluate it. Scoped to
        # this temp file; the TemporaryDirectory cleanup removes it after.
        subprocess.run(
            ["mise", "trust", str(config)],
            cwd=tmp_path,
            env=child_env,
            check=True,
            capture_output=True,
            text=True,
        )

        result = subprocess.run(
            ["mise", "-C", str(tmp_path), "env", "--json"],
            cwd=tmp_path,
            env=child_env,
            check=True,
            capture_output=True,
            text=True,
        )

    resolved = json.loads(result.stdout)

    # `mise env` only lists variables it adds or changes. A var that is already
    # present in the child environment and merely passed through unchanged (an
    # IDC_REGION override whose value mise keeps via `default`) is NOT re-emitted
    # in the output. The effective value of such a var is exactly what we put in
    # the child env, so backfill it from the override/child env to report the
    # full effective region environment a task would see.
    effective = {key: resolved[key] for key in REGION_ENV_KEYS if key in resolved}
    for key in REGION_ENV_KEYS:
        if key not in effective and key in child_env:
            effective[key] = child_env[key]
    return effective
