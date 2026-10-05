"""Pure Python mirror of the empty-string provider selector.

Feature: foundation-idc-service

Both providers in ``foundation/terraform/providers.tf`` resolve their
``region`` and ``profile`` from operator-supplied variables using the same HCL
ternary::

    region  = var.aws_region  != "" ? var.aws_region  : null
    profile = var.aws_profile != "" ? var.aws_profile : null

That is: when the variable holds the empty string, the attribute falls back to
``null`` (letting the provider resolve it from the environment / default
profile); otherwise the operator-supplied value passes through verbatim. The
exact same rule governs ``aws_region`` and ``aws_profile`` on BOTH the ``aws``
and ``awscc`` providers.

``select_or_null`` is a *faithful* mirror of that ternary so the property test
can exercise the passthrough/fallback rule deterministically, offline, over many
Hypothesis-generated strings — no ``tofu`` process, no AWS. HCL's ``null`` maps
to Python's ``None``. Keep this a faithful mirror: when the HCL ternary changes,
this mirror changes with it.

This module lives under ``tests/`` in its own file so sibling test tasks writing
in the same wave never collide on it, and is importable via the shared conftest
``sys.path`` shim (``tests/`` is on the path).
"""

from __future__ import annotations


def select_or_null(s: str) -> str | None:
    """Return ``None`` for the empty string, else ``s`` verbatim.

    Mirrors the HCL ternary ``s != "" ? s : null`` exactly: the empty string
    falls back to ``null`` (``None`` in Python); every other string passes
    through unchanged. This is the single rule applied to ``var.aws_region`` and
    ``var.aws_profile`` on both the ``aws`` and ``awscc`` providers.
    """
    return s if s != "" else None
