r"""Pure Python mirror of the mise residual-``key`` backend.hcl guard.

Feature: foundation-idc-service

The foundation lifecycle tasks (``foundation-plan`` / ``foundation-apply`` /
``foundation-destroy``) refuse to run against a ``backend.hcl`` that pins a
state ``key``, because the per-stack state key is supplied at ``tofu init`` time
via ``-backend-config="key=foundation/terraform.tfstate"`` and a residual ``key``
line in the file would conflict with it (R4.7). The guard in ``mise.toml`` is::

    if grep -Eq '^[[:space:]]*key[[:space:]]*=' backend.hcl; then
      echo "ERROR: remove the 'key' line from backend.hcl; it is supplied at init time." >&2
      exit 1
    fi

``grep -Eq`` is line-oriented: it reports a match (exit 0) iff *at least one*
line of the file matches the extended-regex ``^[[:space:]]*key[[:space:]]*=``.
Per line, that regex means: from the start of the line, optional leading
whitespace, then the literal ``key``, then optional whitespace, then ``=``.

This module is a *faithful* mirror of that predicate so the property test can
exercise it deterministically, offline, over many Hypothesis-generated
``backend.hcl`` texts — no ``grep`` process, no shell. Keep it faithful: when the
guard's regex in ``mise.toml`` changes, this mirror changes with it.

Semantics mirrored carefully:

- **Line-oriented.** ``grep`` splits input into lines on ``\n`` and tests each
  line independently; ``^`` anchors to the start of a *line*, not the whole
  text. A whole-text regex with a lone ``^`` would be wrong, so we split and
  test per line, matching ``grep``'s behavior.
- **POSIX ``[[:space:]]``.** In the C/POSIX locale ``[[:space:]]`` is the set
  ``{space, tab, newline, carriage-return, form-feed, vertical-tab}``. Because
  the match runs *within a single line* (newlines already consumed by the line
  split), the horizontally-relevant members are space, tab, carriage-return,
  form-feed, and vertical-tab. We mirror that exact set rather than Python's
  ``\s`` (which also matches assorted Unicode spaces grep's C locale does not).
- **Comments fall out naturally.** A comment line begins with ``#``, so after
  optional whitespace the next char is ``#`` not ``key`` — it cannot match. The
  predicate therefore reports present *iff a non-comment line assigns a key*,
  with no special comment handling needed. A line like ``keyboard = x`` also
  cannot match: after ``key`` the regex requires optional whitespace then ``=``,
  and ``board`` is neither.

This module lives under ``tests/`` in its own file so sibling test tasks never
collide on it, and is importable via the shared conftest ``sys.path`` shim
(``tests/`` is on the path).
"""

from __future__ import annotations

import re

# POSIX [[:space:]] in the C locale: space, tab, newline, carriage-return,
# form-feed, vertical-tab. The line split below already consumes newlines, so
# per-line the relevant members are the horizontal/control whitespace chars.
# We build the regex from an explicit character class rather than Python's
# ``\s`` so the mirror matches grep's C-locale semantics exactly (``\s`` would
# additionally match Unicode spaces the C locale excludes).
_POSIX_SPACE = " \t\r\f\v"
_SPACE_CLASS = f"[{re.escape(_POSIX_SPACE)}]"

#: Faithful mirror of the extended-regex ``^[[:space:]]*key[[:space:]]*=``
#: applied to a *single line* (grep is line-oriented, so no MULTILINE needed —
#: each line is matched on its own).
LINE_KEY_RE = re.compile(rf"^{_SPACE_CLASS}*key{_SPACE_CLASS}*=")


def line_assigns_key(line: str) -> bool:
    """Mirror the per-line match of ``^[[:space:]]*key[[:space:]]*=``.

    Return ``True`` iff the line, from its start, has optional whitespace, then
    the literal ``key``, then optional whitespace, then ``=`` — exactly what the
    extended-regex matches on one line. The leading ``^`` anchors to the line
    start, so a comment line (leading ``#``) never matches.
    """
    return LINE_KEY_RE.search(line) is not None


def residual_key_present(text: str) -> bool:
    """Mirror ``grep -Eq '^[[:space:]]*key[[:space:]]*=' backend.hcl``.

    ``grep`` is line-oriented and ``-q`` reports a match iff *at least one* line
    matches. Split ``text`` into lines (grep splits on ``\\n``) and return
    ``True`` iff any line assigns a key per :func:`line_assigns_key`. A text with
    no key-assigning line (empty, comments only, other settings) returns
    ``False`` — the guard stays quiet and the task proceeds.
    """
    # ``str.split("\n")`` yields grep's line view: the text between newlines,
    # with no trailing empty "line" beyond a final newline that could spuriously
    # match (an empty line can never match the predicate anyway, since it has no
    # ``key`` / ``=``).
    return any(line_assigns_key(line) for line in text.split("\n"))
