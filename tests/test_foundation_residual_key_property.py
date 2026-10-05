"""Property 4: the residual-key guard flags exactly key-assigning files.

Feature: foundation-idc-service, Property 4: The residual-key guard flags
exactly the files that assign a key
Validates: Requirements 4.7

Property 4: *For any* ``backend.hcl`` text, the mise residual-``key`` guard
(mirrored by ``foundation_residual_key.residual_key_present``, a faithful mirror
of ``grep -Eq '^[[:space:]]*key[[:space:]]*=' backend.hcl``) reports the key
**present iff at least one non-comment line assigns a ``key = ...``**, and
reports it **absent otherwise** (R4.7).

A line assigns a key when, from the line start, there is optional whitespace,
the literal ``key``, optional whitespace, then ``=``. The leading anchor means a
comment line (leading ``#``) can never match, and a near-miss such as
``keyboard = x`` or ``region = foundation/terraform.tfstate`` can never match —
so the guard flags exactly the files pinning a state key and nothing else.

The test drives the mirror over Hypothesis-assembled ``backend.hcl`` texts built
from two labelled line kinds — lines that DO assign a key and lines that do NOT
(comments, other settings, near-misses, blanks) — and checks the guard's verdict
against an independent oracle: present iff the assembled text contains at least
one key-assigning line.

Harness note: ``foundation_residual_key`` lives under ``tests/`` and is
importable via the shared conftest ``sys.path`` shim (``tests/`` is on the
path), mirroring the sibling property tests.
"""

from __future__ import annotations

import foundation_residual_key as frk
from hypothesis import given, settings
from hypothesis import strategies as st

# Whitespace that POSIX [[:space:]] matches *within a line* in the C locale:
# space, tab, carriage-return, form-feed, vertical-tab (newline is the line
# separator and is consumed by the line split).
_INLINE_WS = st.text(alphabet=" \t\r\f\v", max_size=4)

# Arbitrary trailing content after the ``=`` of a key assignment — the value.
# Excludes newlines (that would start a new line) and double-quotes kept simple;
# the predicate ignores everything after ``=`` so the value is unconstrained
# otherwise.
_rest_of_line = st.text(
    alphabet=st.characters(blacklist_characters="\n", min_codepoint=32),
    max_size=24,
)


@st.composite
def _key_assigning_line(draw):
    """A line that DOES match ``^[[:space:]]*key[[:space:]]*=``.

    Optional leading whitespace, the literal ``key``, optional whitespace, then
    ``=``, then arbitrary trailing content. By construction this is exactly the
    shape the guard flags, so the oracle labels it a match.
    """
    lead = draw(_INLINE_WS)
    mid = draw(_INLINE_WS)
    rest = draw(_rest_of_line)
    return f"{lead}key{mid}={rest}"


@st.composite
def _non_matching_line(draw):
    """A line that does NOT match the guard predicate.

    Covers the realistic ``backend.hcl`` non-matches and tricky near-misses:
    comments, the other backend settings, a ``key`` that is really ``keyboard``,
    a ``key`` with no ``=``, a value that merely mentions a state key, and blank
    lines. Each branch is independently guaranteed non-matching, and a final
    assertion keeps the generator honest against the mirror.
    """
    lead = draw(_INLINE_WS)
    value = draw(_rest_of_line)
    kind = draw(
        st.sampled_from(
            [
                "comment",            # starts with '#': anchor fails
                "comment-key",        # '# key = ...' commented out
                "other-setting",      # bucket/region/dynamodb_table/encrypt
                "keyboard",           # 'key' followed by more letters, not ws/=
                "key-no-equals",      # 'key' then whitespace then non-'='
                "value-mentions-key", # key path only in a value, not as setting
                "blank",              # empty / whitespace-only line
                "arbitrary",          # free text not starting with 'key'
            ]
        )
    )

    if kind == "comment":
        line = f"{lead}# {value}"
    elif kind == "comment-key":
        inner = draw(_INLINE_WS)
        line = f"{lead}#{inner}key = {value}"
    elif kind == "other-setting":
        setting = draw(st.sampled_from(["bucket", "region", "dynamodb_table", "encrypt"]))
        line = f'{lead}{setting} = "{value}"'
    elif kind == "keyboard":
        suffix = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=6))
        line = f"{lead}key{suffix} = {value}"
    elif kind == "key-no-equals":
        gap = draw(_INLINE_WS)
        # After 'key' and whitespace, a non-'=' char so the predicate fails.
        tail = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=6))
        line = f"{lead}key{gap}{tail}"
    elif kind == "value-mentions-key":
        line = f'{lead}region = "key=foundation/terraform.tfstate"'
    elif kind == "blank":
        line = draw(_INLINE_WS)
    else:  # arbitrary free text, forced not to start with 'key'
        body = draw(
            st.text(
                alphabet=st.characters(blacklist_characters="\n", min_codepoint=32),
                max_size=24,
            )
        )
        line = f"z{body}"

    # Keep the generator honest: this branch must truly be a non-match. If a
    # future edit to the predicate or a branch makes it match, fail loudly in
    # the generator rather than silently weakening the oracle.
    assert not frk.line_assigns_key(line), (
        f"generator produced a matching line for kind {kind!r}: {line!r}"
    )
    return line


# A labelled line: (text, is_key_assignment). The oracle is "any True".
_labelled_line = st.one_of(
    _key_assigning_line().map(lambda ln: (ln, True)),
    _non_matching_line().map(lambda ln: (ln, False)),
)


@settings(max_examples=300, deadline=None)
@given(lines=st.lists(_labelled_line, max_size=12))
def test_guard_flags_exactly_key_assigning_files(lines):
    """Guard reports present iff some line assigns a key, absent otherwise.

    Feature: foundation-idc-service, Property 4: The residual-key guard flags
    exactly the files that assign a key
    Validates: Requirements 4.7
    """
    text = "\n".join(ln for ln, _ in lines)
    # Independent oracle: the file assigns a key iff at least one of its lines
    # was generated as a key assignment.
    oracle_present = any(is_key for _, is_key in lines)

    assert frk.residual_key_present(text) == oracle_present, (
        f"guard verdict {frk.residual_key_present(text)!r} disagrees with oracle "
        f"{oracle_present!r} for text:\n{text!r}"
    )


@settings(max_examples=200, deadline=None)
@given(line=_key_assigning_line())
def test_single_key_line_is_always_flagged(line):
    """Any single key-assigning line is flagged present (per-line soundness).

    Validates: Requirements 4.7
    """
    assert frk.line_assigns_key(line) is True
    assert frk.residual_key_present(line) is True


@settings(max_examples=200, deadline=None)
@given(line=_non_matching_line())
def test_single_non_matching_line_is_never_flagged(line):
    """Any single non-matching line is reported absent (per-line completeness).

    Validates: Requirements 4.7
    """
    assert frk.line_assigns_key(line) is False
    assert frk.residual_key_present(line) is False


def test_known_examples():
    """Concrete anchor examples pin the predicate's intended behavior.

    Validates: Requirements 4.7
    """
    # Present: plain, indented, tab-separated, no-space.
    assert frk.residual_key_present('key = "foundation/terraform.tfstate"')
    assert frk.residual_key_present('    key = "x"')
    assert frk.residual_key_present("\tkey\t=\tx")
    assert frk.residual_key_present("key=x")
    # Present when buried among keyless lines.
    body = (
        'bucket         = "b"\n'
        'region         = "r"\n'
        'key            = "foundation/terraform.tfstate"\n'
        "encrypt        = true\n"
    )
    assert frk.residual_key_present(body)

    # Absent: the real keyless body, comments, near-misses, empties.
    keyless = (
        'bucket         = "b"\n'
        'region         = "r"\n'
        'dynamodb_table = "t"\n'
        "encrypt        = true\n"
    )
    assert not frk.residual_key_present(keyless)
    assert not frk.residual_key_present("# key = commented out")
    assert not frk.residual_key_present("keyboard = x")
    assert not frk.residual_key_present("")
    assert not frk.residual_key_present("\n\n   \n")
    assert not frk.residual_key_present('region = "key=foundation/terraform.tfstate"')
