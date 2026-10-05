"""Property 6: the empty-string provider selector passes through or falls back.

Feature: foundation-idc-service, Property 6: The empty-string provider selector
passes through or falls back
Validates: Requirements 5.3, 5.4, 5.5

Property 6: *For any* string, the provider selector
(``foundation_provider_selector.select_or_null``, the pure mirror of the HCL
ternary ``s != "" ? s : null``) yields:

- ``None`` for the empty string (fallback — the provider resolves region/profile
  from the environment / default credentials); and
- the string verbatim for every non-empty value (passthrough).

This is the single rule governing ``var.aws_region`` and ``var.aws_profile`` on
BOTH the ``aws`` and ``awscc`` providers, so the same mirror stands in for all
four selector sites.

The property drives the mirror against an *independent* reference oracle written
from the rule directly — ``None`` iff the input is empty — rather than
re-deriving the mirror's own expression. Over ``st.text()`` arbitrary strings
(plus a short-string-biased generator that lands many examples right on the
empty/non-empty boundary) the two must agree on every input; targeted
``@example`` cases pin the empty-string fallback and representative passthroughs
(a region, a profile name, whitespace-only, and a single space). A regression
that fell back on whitespace, dropped the passthrough, or returned ``""`` instead
of ``None`` would make the mirror disagree with the oracle and fail here.

Harness note: ``foundation_provider_selector`` lives under ``tests/`` in its own
module and is importable via the shared conftest ``sys.path`` shim (``tests/`` is
on the path), mirroring the sibling property tests.
"""

from __future__ import annotations

import foundation_provider_selector as fps
from hypothesis import example, given, settings
from hypothesis import strategies as st


def _selector_oracle(s: str) -> str | None:
    """Independent reference for the empty-string selector.

    Written directly from the rule — ``None`` iff the input is exactly the empty
    string, otherwise the input unchanged — so it is a genuine cross-check rather
    than a copy of the mirror's expression.
    """
    if len(s) == 0:
        return None
    return s


# Arbitrary text over the full unicode space exercises the passthrough side
# broadly, including whitespace, punctuation, and non-ASCII values.
_arbitrary = st.text(min_size=0, max_size=64)

# A short-string-biased generator lands many examples right on the empty /
# non-empty boundary (empty, single char, two chars), where arbitrary
# ``st.text()`` rarely produces the empty string.
_short_biased = st.text(min_size=0, max_size=3)

_any_string = st.one_of(_arbitrary, _short_biased)


@settings(max_examples=400, deadline=None)
@given(s=_any_string)
# --- fallback case: the empty string -----------------------------------------
@example(s="")  # empty -> None (fallback)
# --- passthrough cases: representative non-empty values -----------------------
@example(s="us-east-1")  # a region -> passthrough
@example(s="eu-west-2")  # another region -> passthrough
@example(s="my-profile")  # an AWS profile name -> passthrough
@example(s=" ")  # single space is non-empty -> passthrough (NOT fallback)
@example(s="  ")  # whitespace-only is non-empty -> passthrough
@example(s="\t")  # tab is non-empty -> passthrough
def test_selector_matches_oracle(s):
    """The selector agrees with the independent oracle on every input.

    Feature: foundation-idc-service, Property 6: The empty-string provider
    selector passes through or falls back
    Validates: Requirements 5.3, 5.4, 5.5
    """
    assert fps.select_or_null(s) == _selector_oracle(s), (
        f"selector and oracle disagree on {s!r}: "
        f"select_or_null={fps.select_or_null(s)!r}, oracle={_selector_oracle(s)!r}"
    )


@settings(max_examples=200, deadline=None)
@given(s=st.text(min_size=1, max_size=64))
def test_non_empty_passes_through_verbatim(s):
    """Any non-empty string is returned verbatim (never None, never altered).

    This isolates the passthrough half of the rule: with ``min_size=1`` the
    empty-string fallback can never fire, so the selector must return the exact
    input unchanged for every value — including whitespace-only strings, which
    are non-empty and therefore pass through.

    Feature: foundation-idc-service, Property 6
    Validates: Requirements 5.3, 5.4, 5.5
    """
    result = fps.select_or_null(s)
    assert result is not None
    assert result == s


def test_empty_string_falls_back_to_none():
    """The empty string is the sole input that falls back to None.

    This pins the fallback half of the rule directly: ``select_or_null("")`` must
    be ``None`` (HCL ``null``), the behavior that lets the provider resolve the
    region/profile from the environment or default credentials.

    Feature: foundation-idc-service, Property 6
    Validates: Requirements 5.3, 5.4, 5.5
    """
    assert fps.select_or_null("") is None
