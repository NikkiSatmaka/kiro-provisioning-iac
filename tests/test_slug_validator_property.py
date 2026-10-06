"""Property 8: the slug validator accepts exactly the specified slug grammar.

Feature: multi-workshop-provisioning, Property 8: the slug validator accepts
exactly the specified slug grammar
Validates: Requirements 5.2, 5.8, 8.3, 8.4

Property 8: *For any* string, the ``workshop_id`` slug validator
(``workshop_slug.is_valid_slug``, the pure mirror of the HCL two-regex check)
accepts it **iff** it satisfies every rule of the slug grammar:

- length is 1-63 characters (reject empty, reject over-length);
- every character is a lowercase ASCII letter, digit, or hyphen (reject
  uppercase, whitespace, and any other character);
- the first and last characters are alphanumeric (reject leading/trailing
  hyphen);
- it contains no two consecutive hyphens (reject double-hyphen).

The property drives the mirror against an *independent* reference oracle
(``_grammar_oracle``) written from the rules directly — character by character,
no regex — rather than re-deriving the same regex the validator uses. Over
``st.text()`` arbitrary strings (plus a slug-biased generator that lands many
examples right on the accept/reject boundary) the two must agree on every input;
targeted ``@example`` cases pin each reject reason and each accept shape. A
regression that allowed uppercase, dropped the length cap, or stopped rejecting
double hyphens would make the mirror disagree with the oracle and fail here.

Harness note: ``workshop_slug`` lives under ``tests/`` in its own module and is
importable via the shared conftest ``sys.path`` shim (``tests/`` is on the
path), mirroring the sibling property tests.
"""

from __future__ import annotations

import string

import workshop_slug as ws
from hypothesis import example, given, settings
from hypothesis import strategies as st

# The exact character class the grammar permits in the interior of a slug:
# lowercase ASCII letters, digits, and the hyphen. The first/last character must
# be from the alphanumeric subset (no hyphen).
_LOWER_ALNUM = frozenset(string.ascii_lowercase + string.digits)
_SLUG_CHARS = _LOWER_ALNUM | {"-"}


def _grammar_oracle(s: str) -> bool:
    """Independent reference predicate for the slug grammar.

    Written directly from the rules — not from the validator's regex — so it is a
    genuine cross-check rather than a copy. Returns True iff ``s`` is a valid
    slug: length 1-63, all chars lowercase-alphanumeric-or-hyphen, first and last
    alphanumeric, no two consecutive hyphens.
    """
    if not (1 <= len(s) <= 63):
        return False
    if any(ch not in _SLUG_CHARS for ch in s):
        return False
    if s[0] not in _LOWER_ALNUM or s[-1] not in _LOWER_ALNUM:
        return False
    if "--" in s:
        return False
    return True


# A slug-biased generator: strings drawn mostly from the slug alphabet so a large
# fraction of examples sit right on the accept/reject boundary (valid slugs,
# leading/trailing hyphens, double hyphens, exactly-63 and 64-length values),
# where arbitrary ``st.text()`` would almost always land in the trivially-reject
# region.
_slug_alphabet = st.sampled_from(sorted(_SLUG_CHARS))
_slug_biased = st.text(alphabet=_slug_alphabet, min_size=0, max_size=66)

# Arbitrary text over the full unicode space exercises the reject side broadly:
# uppercase, whitespace, punctuation, non-ASCII, and the empty string.
_arbitrary = st.text(min_size=0, max_size=66)

_any_string = st.one_of(_arbitrary, _slug_biased)


@settings(max_examples=400, deadline=None)
@given(s=_any_string)
# --- reject cases: one per grammar rule --------------------------------------
@example(s="")  # empty -> reject (length < 1)
@example(s="   ")  # whitespace -> reject (non-slug chars)
@example(s="a b")  # internal whitespace -> reject
@example(s="Workshop")  # uppercase -> reject
@example(s="kiro-2025-10-10-" + "x" * 48)  # 64 chars -> reject (over-length)
@example(s="a" * 64)  # 64 chars, all alnum -> reject (over-length)
@example(s="-abc")  # leading hyphen -> reject
@example(s="abc-")  # trailing hyphen -> reject
@example(s="-")  # lone hyphen -> reject (both ends non-alnum)
@example(s="a--b")  # double hyphen -> reject
@example(s="a---b")  # triple hyphen -> reject
@example(s="a_b")  # underscore -> reject (not in slug alphabet)
@example(s="caf\u00e9")  # non-ASCII -> reject
# --- accept cases: each valid shape ------------------------------------------
@example(s="a")  # single char -> accept
@example(s="0")  # single digit -> accept
@example(s="a-b-c")  # interior hyphens -> accept
@example(s="kiro-2025-10-10")  # realistic slug -> accept
@example(s="a" * 63)  # exactly 63 chars -> accept (upper bound)
@example(s="a" + "b" * 61 + "c")  # 63 chars, mixed -> accept
def test_slug_validator_matches_grammar_oracle(s):
    """The validator agrees with the independent grammar oracle on every input.

    Feature: multi-workshop-provisioning, Property 8: the slug validator accepts
    exactly the specified slug grammar
    Validates: Requirements 5.2, 5.8, 8.3, 8.4
    """
    assert ws.is_valid_slug(s) == _grammar_oracle(s), (
        f"validator and grammar oracle disagree on {s!r}: "
        f"is_valid_slug={ws.is_valid_slug(s)}, oracle={_grammar_oracle(s)}"
    )


@settings(max_examples=200, deadline=None)
@given(
    s=st.text(alphabet=sorted(_LOWER_ALNUM), min_size=1, max_size=63)
)
def test_pure_lower_alnum_1_to_63_always_accepted(s):
    """Any 1-63 char string of only lowercase alphanumerics is a valid slug.

    This is the hyphen-free core of the grammar: no hyphen means no leading /
    trailing / double-hyphen rule can fire, so acceptance depends only on the
    length bound and the character class — both satisfied by construction.

    Feature: multi-workshop-provisioning, Property 8
    Validates: Requirements 5.2, 5.8, 8.3, 8.4
    """
    assert ws.is_valid_slug(s) is True


@settings(max_examples=200, deadline=None)
@given(
    body=st.text(alphabet=sorted(_SLUG_CHARS), min_size=1, max_size=61)
)
def test_leading_or_trailing_hyphen_always_rejected(body):
    """A hyphen at either end always makes the slug invalid.

    Prepending or appending '-' violates the begin/end-alphanumeric rule, so the
    validator must reject regardless of the interior, exercising the
    leading/trailing-hyphen reject reason over many interiors.

    Feature: multi-workshop-provisioning, Property 8
    Validates: Requirements 5.2, 5.8, 8.3, 8.4
    """
    assert ws.is_valid_slug("-" + body) is False
    assert ws.is_valid_slug(body + "-") is False
