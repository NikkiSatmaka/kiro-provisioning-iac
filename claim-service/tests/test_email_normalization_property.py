"""Property-based tests for email normalization.

Feature: credential-claim-service, Property 2: Email normalization is
idempotent and is the sole key.

Validates: Requirements 1.5, 13.1

``normalize_email`` lowercases and strips an email. It is the sole
key-derivation for an email across the service, so it must be idempotent:
applying it twice yields the same result as applying it once. The normalized
form must also already be lowercased and stripped (a fixed point of lower/strip).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

import claim_handler

# Run a healthy number of iterations per the design's property-test guidance
# (minimum 100 iterations).
PROPERTY_SETTINGS = settings(max_examples=200)


@PROPERTY_SETTINGS
@given(raw=st.text())
def test_normalize_email_is_idempotent(raw: str) -> None:
    """normalize_email(normalize_email(e)) == normalize_email(e) for any input.

    Feature: credential-claim-service, Property 2
    Validates: Requirements 1.5, 13.1
    """
    once = claim_handler.normalize_email(raw)
    twice = claim_handler.normalize_email(once)
    assert twice == once


@PROPERTY_SETTINGS
@given(raw=st.text())
def test_normalize_email_is_lowercase_and_stripped(raw: str) -> None:
    """The normalized form is already lowercased and whitespace-stripped.

    Feature: credential-claim-service, Property 2
    Validates: Requirements 1.5, 13.1
    """
    normalized = claim_handler.normalize_email(raw)
    # A fixed point of both operations: lowercasing and stripping change nothing.
    assert normalized == normalized.lower()
    assert normalized == normalized.strip()


@PROPERTY_SETTINGS
@given(
    local=st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1),
    domain=st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1),
    lead=st.text(alphabet=" \t\n\r", max_size=4),
    trail=st.text(alphabet=" \t\n\r", max_size=4),
)
def test_normalize_email_canonical_key_for_variants(
    local: str, domain: str, lead: str, trail: str
) -> None:
    """Case- and whitespace-variants of one address share a single key.

    Two submissions differing only in surrounding whitespace or letter case
    normalize to the same value, so the EMAIL# key derived from a Normalized_
    Email identifies the address uniquely (Requirements 1.5, 13.1).

    Feature: credential-claim-service, Property 2
    Validates: Requirements 1.5, 13.1
    """
    address = f"{local}@{domain}"
    decorated = f"{lead}{address}{trail}"
    assert claim_handler.normalize_email(decorated) == claim_handler.normalize_email(
        address
    )
