"""Pure Python mirror of the keyless backend.hcl body + per-stack dispatch.

Feature: foundation-idc-service

The ``backend/terraform/outputs.tf`` stack renders every consuming stack's
``backend.hcl`` body from a single shared heredoc and hands each stack the
identical rendered body::

    locals {
      _backend_hcl_shared = {
        bucket         = local.state_bucket_name
        region         = data.aws_region.current.region
        dynamodb_table = aws_dynamodb_table.locks.name
      }

      _backend_hcl_body = <<-EOT
        bucket         = "${local._backend_hcl_shared.bucket}"
        region         = "${local._backend_hcl_shared.region}"
        dynamodb_table = "${local._backend_hcl_shared.dynamodb_table}"
        encrypt        = true
      EOT

      _backend_hcl_for = {
        subscription  = local._backend_hcl_body
        claim_service = local._backend_hcl_body
        foundation    = local._backend_hcl_body
      }
    }

The body is **keyless** on purpose: the per-stack state ``key`` is supplied at
``tofu init`` time via ``-backend-config="key=..."``, so one bootstrapped
``backend.hcl`` body serves every stack and nothing in the file pins a single
state path. The foundation stack (task 3.1) joins ``_backend_hcl_for`` with the
*same* ``_backend_hcl_body`` — isolation comes from the init-time key, never
from the file — so the three bodies are byte-identical.

This module is a *faithful* mirror of that HCL so the property test can exercise
the render + dispatch deterministically, offline, over many Hypothesis-generated
``(bucket, region, dynamodb_table)`` triples — no ``tofu`` process, no AWS.

HCL semantics mirrored:

- The ``<<-EOT`` *indented* heredoc strips the common leading indentation from
  every line (the least-indented line sets the amount), so the rendered body
  lines carry no leading whitespace. The interpolations keep the HCL field
  alignment (``bucket`` / ``region`` / ``dynamodb_table`` padded to the same
  column, ``encrypt`` likewise).
- A heredoc includes the newline before its closing delimiter, so the rendered
  body ends with a trailing newline.
- ``_backend_hcl_for`` maps every stack name to the *same* ``_backend_hcl_body``
  value, so the per-stack bodies are identical by construction.

Keep this a faithful mirror: when the heredoc or the ``_backend_hcl_for`` map in
``outputs.tf`` changes, this mirror changes with it. It lives under ``tests/`` in
its own file so sibling test tasks never collide on it, and is importable via the
shared conftest ``sys.path`` shim (``tests/`` is on the path).
"""

from __future__ import annotations

# The three stacks that share the identical keyless backend body. Matches the
# keys of ``_backend_hcl_for`` in backend/terraform/outputs.tf.
STACKS = ("subscription", "claim_service", "foundation")


def backend_hcl_body(bucket: str, region: str, dynamodb_table: str) -> str:
    """Mirror the rendered ``_backend_hcl_body`` heredoc.

    Returns the keyless backend.hcl body carrying exactly ``bucket``, ``region``,
    ``dynamodb_table``, and ``encrypt = true`` — field-aligned, with the leading
    indentation stripped (``<<-EOT``) and a trailing newline (the heredoc newline
    before ``EOT``). No ``key`` line is emitted; the state key is an init-time
    argument.
    """
    return (
        f'bucket         = "{bucket}"\n'
        f'region         = "{region}"\n'
        f'dynamodb_table = "{dynamodb_table}"\n'
        "encrypt        = true\n"
    )


def backend_hcl_for(bucket: str, region: str, dynamodb_table: str) -> dict[str, str]:
    """Mirror ``_backend_hcl_for``: every stack maps to the same rendered body.

    Returns a dict from stack name (``subscription`` / ``claim_service`` /
    ``foundation``) to the single ``backend_hcl_body`` value, so the three bodies
    are identical by construction — exactly as the HCL hands each stack
    ``local._backend_hcl_body``.
    """
    body = backend_hcl_body(bucket, region, dynamodb_table)
    return {stack: body for stack in STACKS}
