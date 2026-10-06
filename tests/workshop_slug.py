"""Pure Python mirror of the ``workshop_id`` slug validator.

Feature: multi-workshop-provisioning

Both ``subscription/terraform/variables.tf`` and
``claim-service/terraform/variables.tf`` guard ``var.workshop_id`` with the same
HCL validation. In HCL it is expressed as two regex checks combined with ``&&``::

    can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", var.workshop_id))
      && !can(regex("--", var.workshop_id))

That is: the value must match the anchored slug pattern AND must not contain a
double hyphen. The anchored pattern means:

- length 1-63 characters;
- every character is a lowercase ASCII letter, digit, or hyphen;
- the first and last characters are alphanumeric (no leading/trailing hyphen);

and the second ``!can(regex("--"))`` check forbids any run of two or more
consecutive hyphens.

``is_valid_slug`` is a *faithful* mirror of that two-regex form so the property
test can exercise the acceptance grammar deterministically, offline, over many
Hypothesis-generated strings — no ``tofu`` process, no AWS. Keep this a faithful
mirror: when the HCL validation changes, this mirror changes with it.

This module lives under ``tests/`` in its own file (separate from
``workshop_flatten`` and the renderer scripts) so sibling test tasks writing in
the same wave never collide on it, and is importable via the shared conftest
``sys.path`` shim (``tests/`` is on the path).
"""

from __future__ import annotations

import re

# The anchored slug pattern, byte-for-byte the HCL regex:
#   ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$
# A single alphanumeric char is valid; longer values start and end alphanumeric
# with 0..61 interior slug chars (letters, digits, hyphens) between — capping the
# total length at 1 + 61 + 1 = 63.
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

# The second guard: reject any value containing two consecutive hyphens, mirroring
# the HCL `!can(regex("--", ...))`.
_DOUBLE_HYPHEN_RE = re.compile(r"--")


def is_valid_slug(s: str) -> bool:
    """Return True iff ``s`` is accepted by the ``workshop_id`` slug validator.

    Mirrors the HCL two-regex form exactly: the value must match the anchored
    slug pattern AND must not contain a double hyphen. Equivalent, in plain
    terms, to: 1-63 characters, all lowercase alphanumeric or hyphen, first and
    last characters alphanumeric, and no two hyphens in a row.
    """
    return bool(_SLUG_RE.match(s)) and not _DOUBLE_HYPHEN_RE.search(s)
