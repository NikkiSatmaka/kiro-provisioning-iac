"""Property 7: the teardown guard accepts exactly the fixed phrase.

Feature: foundation-idc-service, Property 7: The teardown guard accepts exactly
the fixed phrase
Validates: Requirements 7.2, 7.3, 7.4

Property 7: *For any* string, the teardown guard
(``foundation_teardown_guard.accepts``, the pure mirror of the shell equality
``[ "$CONFIRM" = "destroy-foundation" ]``) proceeds iff the string equals the
fixed phrase ``destroy-foundation`` exactly and rejects everything else:

- the exact phrase ``destroy-foundation`` is accepted (R7.2);
- every other string is rejected — case variants (``DESTROY-FOUNDATION``,
  ``Destroy-Foundation``), surrounding whitespace (``" destroy-foundation"``,
  ``"destroy-foundation\n"``), near-misses (missing/extra characters, the
  underscore/space variants), and the empty string (R7.3, R7.4);
- so a mismatch deletes nothing — the guard is case-sensitive and does NOT trim.

The property drives the mirror against an *independent* reference oracle written
from the rule directly — accept iff the input is byte-for-byte the phrase —
rather than re-deriving the mirror's own expression. Over arbitrary strings
(plus generators that land many examples right on the near-miss boundary) the
two must agree on every input; targeted ``@example`` cases pin the exact-match
acceptance and the case/whitespace/near-miss/empty rejections. A regression that
trimmed whitespace, matched case-insensitively, or accepted a near-miss would
make the mirror disagree with the oracle and fail here.

Harness note: ``foundation_teardown_guard`` lives under ``tests/`` in its own
module and is importable via the shared conftest ``sys.path`` shim (``tests/`` is
on the path), mirroring the sibling property tests (e.g.
``test_foundation_provider_selector_property.py``).
"""

from __future__ import annotations

import foundation_teardown_guard as ftg
from hypothesis import example, given, settings
from hypothesis import strategies as st

_PHRASE = ftg.PHRASE  # "destroy-foundation"


def _guard_oracle(confirm: str) -> bool:
    """Independent reference for the typed-phrase guard.

    Written directly from the rule — accept iff the input is byte-for-byte equal
    to the fixed phrase, with no trimming and case-sensitive — so it is a genuine
    cross-check rather than a copy of the mirror's expression.
    """
    return confirm == "destroy-foundation"


# Arbitrary text over the full unicode space exercises the reject side broadly,
# including whitespace, punctuation, and non-ASCII values; st.text() almost
# never lands on the exact phrase on its own.
_arbitrary = st.text(min_size=0, max_size=48)

# A near-miss generator biases toward strings close to the phrase so many
# examples sit right on the accept/reject boundary: the phrase with whitespace
# padding, a trailing newline, case flips, and single-character perturbations.
_whitespace = st.text(alphabet=" \t\n\r", min_size=0, max_size=3)


@st.composite
def _near_misses(draw):
    """Draw strings close to the fixed phrase (padding, case, perturbations)."""
    kind = draw(st.integers(min_value=0, max_value=4))
    if kind == 0:
        # Surrounding whitespace (leading and/or trailing) — must NOT be trimmed.
        lead = draw(_whitespace)
        trail = draw(_whitespace)
        return f"{lead}{_PHRASE}{trail}"
    if kind == 1:
        # Case variants over the ASCII letters of the phrase.
        return "".join(
            c.upper() if draw(st.booleans()) else c for c in _PHRASE
        )
    if kind == 2:
        # Delimiter swaps / common near-misses.
        return draw(
            st.sampled_from(
                [
                    _PHRASE.replace("-", "_"),  # destroy_foundation
                    _PHRASE.replace("-", " "),  # destroy foundation
                    _PHRASE.replace("-", ""),   # destroyfoundation
                    _PHRASE + "s",              # destroy-foundations
                    _PHRASE[:-1],               # destroy-foundatio
                    _PHRASE[1:],                # estroy-foundation
                    "destroy",                  # prefix only
                    "foundation",               # suffix word only
                ]
            )
        )
    if kind == 3:
        # Insert a stray character at an arbitrary position.
        pos = draw(st.integers(min_value=0, max_value=len(_PHRASE)))
        ch = draw(st.characters(min_codepoint=33, max_codepoint=126))
        return _PHRASE[:pos] + ch + _PHRASE[pos:]
    # kind == 4: drop a single character.
    pos = draw(st.integers(min_value=0, max_value=len(_PHRASE) - 1))
    return _PHRASE[:pos] + _PHRASE[pos + 1 :]


_any_string = st.one_of(_arbitrary, _near_misses())


@settings(max_examples=400, deadline=None)
@given(confirm=_any_string)
# --- accept case: the exact fixed phrase --------------------------------------
@example(confirm="destroy-foundation")  # exact match -> accepted
# --- reject cases: case variants ----------------------------------------------
@example(confirm="DESTROY-FOUNDATION")  # upper -> rejected (case-sensitive)
@example(confirm="Destroy-Foundation")  # title -> rejected
@example(confirm="destroy-Foundation")  # mixed -> rejected
# --- reject cases: surrounding whitespace (not trimmed) -----------------------
@example(confirm=" destroy-foundation")   # leading space -> rejected
@example(confirm="destroy-foundation ")   # trailing space -> rejected
@example(confirm=" destroy-foundation ")  # both -> rejected
@example(confirm="destroy-foundation\n")  # trailing newline -> rejected
@example(confirm="\tdestroy-foundation")  # leading tab -> rejected
# --- reject cases: near-misses ------------------------------------------------
@example(confirm="destroy_foundation")   # underscore -> rejected
@example(confirm="destroy foundation")   # space delimiter -> rejected
@example(confirm="destroyfoundation")    # no delimiter -> rejected
@example(confirm="destroy-foundations")  # extra char -> rejected
@example(confirm="destroy-foundatio")    # missing char -> rejected
@example(confirm="destroy")              # prefix only -> rejected
# --- reject case: the empty string --------------------------------------------
@example(confirm="")  # empty -> rejected
def test_guard_matches_oracle(confirm):
    """The guard agrees with the independent oracle on every input.

    Feature: foundation-idc-service, Property 7: The teardown guard accepts
    exactly the fixed phrase
    Validates: Requirements 7.2, 7.3, 7.4
    """
    assert ftg.accepts(confirm) == _guard_oracle(confirm), (
        f"guard and oracle disagree on {confirm!r}: "
        f"accepts={ftg.accepts(confirm)!r}, oracle={_guard_oracle(confirm)!r}"
    )


def test_exact_phrase_is_accepted():
    """The exact phrase ``destroy-foundation`` is the sole accepted input (R7.2)."""
    assert ftg.accepts("destroy-foundation") is True


@settings(max_examples=200, deadline=None)
@given(
    confirm=_any_string.filter(lambda s: s != "destroy-foundation"),
)
def test_everything_but_the_exact_phrase_is_rejected(confirm):
    """Any string that is not byte-for-byte the phrase is rejected (R7.3, R7.4).

    With the exact phrase filtered out, the guard must reject every remaining
    input — case variants, whitespace-padded forms, near-misses, and the empty
    string — so a mismatch deletes nothing.

    Feature: foundation-idc-service, Property 7
    Validates: Requirements 7.3, 7.4
    """
    assert ftg.accepts(confirm) is False


def test_case_and_whitespace_variants_are_rejected():
    """Case variants and whitespace padding never pass the guard (R7.3, R7.4).

    Pins directly that the guard is case-sensitive and does NOT trim surrounding
    whitespace — the behaviors a careless rewrite would most likely relax.
    """
    for variant in (
        "DESTROY-FOUNDATION",
        "Destroy-Foundation",
        " destroy-foundation",
        "destroy-foundation ",
        "destroy-foundation\n",
        "\tdestroy-foundation",
        "",
    ):
        assert ftg.accepts(variant) is False, f"{variant!r} should be rejected"
