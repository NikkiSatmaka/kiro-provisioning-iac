"""Pure Python mirror of the Foundation IdC teardown confirmation guard.

Feature: foundation-idc-service

The ``foundation-destroy`` mise task in ``mise.toml`` gates the destructive
``tofu destroy`` behind a typed-phrase confirmation. It prompts the operator,
reads a line into ``CONFIRM``, and proceeds only when that string equals the
fixed phrase exactly::

    printf 'Type exactly "destroy-foundation" to proceed: '
    read -r CONFIRM
    if [ "$CONFIRM" != "destroy-foundation" ]; then
      echo "ERROR: confirmation phrase did not match ..." >&2
      exit 1
    fi

The POSIX ``[ "$CONFIRM" = "destroy-foundation" ]`` test is a plain byte-for-byte
string equality: it does NOT trim surrounding whitespace, is case-sensitive, and
treats near-misses and the empty string as mismatches (R7.2, R7.3, R7.4). On a
match the task falls through to the backend guards + ``tofu destroy``; on any
mismatch it exits non-zero and deletes nothing.

``accepts`` is a *faithful* mirror of that equality so the property test can
exercise the typed-phrase acceptor deterministically, offline, over many
Hypothesis-generated strings — no shell, no ``tofu`` process, no AWS. Keep this
a faithful mirror: when the phrase or the equality test in ``mise.toml`` changes,
this mirror changes with it.

The fixed phrase is exposed as a module constant so the sibling property test can
build near-misses from it rather than re-hardcoding the literal.

This module lives under ``tests/`` in its own file so sibling test tasks writing
in the same wave never collide on it, and is importable via the shared conftest
``sys.path`` shim (``tests/`` is on the path).
"""

from __future__ import annotations

#: The fixed confirmation phrase the operator must type to proceed with the
#: destructive foundation teardown.
PHRASE = "destroy-foundation"


def accepts(confirm: str) -> bool:
    """Mirror ``[ "$CONFIRM" = "destroy-foundation" ]``.

    Return ``True`` iff ``confirm`` equals the fixed phrase ``destroy-foundation``
    exactly — a byte-for-byte, case-sensitive comparison with no trimming of
    surrounding whitespace. Every other string (case variants, whitespace-padded
    forms, near-misses, and the empty string) returns ``False``, matching the
    shell guard that then exits non-zero and deletes nothing.
    """
    return confirm == PHRASE
