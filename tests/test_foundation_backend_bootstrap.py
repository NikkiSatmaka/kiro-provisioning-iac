"""Text-fact tests for the foundation backend bootstrap extension.

Feature: foundation-idc-service, Task 3.4
Validates: Requirements 4.5

Pillar 2 extends the keyless backend bootstrap so the ``backend`` stack also
writes the foundation stack's ``backend.hcl`` — the ONLY change outside
``foundation/``. That extension is additive and spans two files:

* ``backend/terraform/outputs.tf`` gains a ``foundation`` entry in the
  ``_backend_hcl_for`` map (bound to the shared, keyless ``_backend_hcl_body``)
  and a new ``output "backend_hcl_foundation"`` beside the existing
  ``backend_hcl`` / ``backend_hcl_claim_service`` outputs.
* ``mise.toml`` ``[tasks.backend-bootstrap]`` writes that output to
  ``../../foundation/terraform/backend.hcl``, alongside the subscription and
  claim-service writes.

This suite pins that contract as static text facts, so it holds offline with no
toolchain. The byte-identity of the rendered body across stacks is covered by
the property test ``tests/test_foundation_backend_body_property.py`` (task 3.3);
here we only assert the wiring exists and the foundation body stays keyless.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

BACKEND_OUTPUTS_TF = REPO_ROOT / "backend" / "terraform" / "outputs.tf"
MISE_TOML = REPO_ROOT / "mise.toml"

# A ``key = ...`` HCL setting at the start of a line (ignoring leading
# whitespace) — the same shape the residual-key guard greps for. Used to prove
# the foundation body is keyless, like the other stacks.
KEY_LINE = re.compile(r"^\s*key\s*=", re.MULTILINE)


# --- R4.5: the foundation backend output is declared ------------------------


def test_outputs_declare_foundation_entry_in_backend_hcl_for():
    """``_backend_hcl_for`` carries a ``foundation`` entry (R4.5).

    The bootstrap renders each stack's backend.hcl from this map, so the
    foundation stack must have an entry bound to the shared keyless body —
    byte-identical to the other stacks (isolation comes from the init-time key).
    """
    text = BACKEND_OUTPUTS_TF.read_text()

    m = re.search(r"_backend_hcl_for\s*=\s*\{(.*?)\}", text, re.DOTALL)
    assert m, "could not locate the _backend_hcl_for map in outputs.tf"
    body = m.group(1)

    assert re.search(
        r"(?m)^\s*foundation\s*=\s*local\._backend_hcl_body\b", body
    ), (
        "_backend_hcl_for is missing a `foundation = local._backend_hcl_body` "
        "entry bound to the shared keyless body"
    )


def test_outputs_declare_backend_hcl_foundation_output():
    """``outputs.tf`` declares ``output "backend_hcl_foundation"`` (R4.5).

    The bootstrap writes the foundation backend.hcl from this output, mirroring
    the existing ``backend_hcl`` / ``backend_hcl_claim_service`` outputs, so it
    must exist and resolve to the ``foundation`` entry of ``_backend_hcl_for``.
    """
    text = BACKEND_OUTPUTS_TF.read_text()

    m = re.search(
        r'output\s+"backend_hcl_foundation"\s*\{(.*?)\n\}', text, re.DOTALL
    )
    assert m, 'outputs.tf does not declare output "backend_hcl_foundation"'
    block = m.group(1)

    assert re.search(
        r'value\s*=\s*local\._backend_hcl_for\["foundation"\]', block
    ), (
        'output "backend_hcl_foundation" is not bound to '
        'local._backend_hcl_for["foundation"]'
    )


def test_rendered_foundation_body_is_keyless():
    """The body behind the foundation output omits ``key`` (R4.5).

    The ``foundation`` entry is bound to ``_backend_hcl_body``; that shared
    heredoc must carry no ``key =`` line, so the state path is supplied only at
    init time via ``-backend-config="key=foundation/terraform.tfstate"``.
    """
    text = BACKEND_OUTPUTS_TF.read_text()

    m = re.search(
        r"_backend_hcl_body\s*=\s*<<-?EOT\n(.*?)\n\s*EOT", text, re.DOTALL
    )
    assert m, "could not locate the _backend_hcl_body heredoc in outputs.tf"
    rendered = m.group(1)

    assert KEY_LINE.search(rendered) is None, (
        "the shared backend body behind backend_hcl_foundation still emits `key`"
    )


# --- R4.5: the bootstrap task writes the foundation backend.hcl -------------


def test_backend_bootstrap_writes_foundation_backend_hcl():
    """``backend-bootstrap`` writes the foundation ``backend.hcl`` (R4.5).

    The mise task must pipe ``tofu output -raw backend_hcl_foundation`` into
    ``../../foundation/terraform/backend.hcl`` (the bootstrap runs in
    ``backend/terraform``, so that relative path lands in the foundation stack),
    alongside the subscription and claim-service writes.
    """
    toml = MISE_TOML.read_text()

    start = toml.index("[tasks.backend-bootstrap]")
    nxt = toml.find("\n[tasks.", start + 1)
    block = toml[start : nxt if nxt != -1 else len(toml)]

    assert re.search(
        r"tofu output -raw backend_hcl_foundation\s*>\s*"
        r"\.\./\.\./foundation/terraform/backend\.hcl",
        block,
    ), (
        "backend-bootstrap does not write "
        "`tofu output -raw backend_hcl_foundation > "
        "../../foundation/terraform/backend.hcl`"
    )
