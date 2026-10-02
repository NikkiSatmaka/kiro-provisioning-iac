"""Property tests for malformed-email rejection.

Feature: credential-claim-service, Property 1
Property 1: Malformed emails are rejected without a write.
Validates: Requirements 1.3

``is_valid_email`` is a format-only check: an email is valid iff it has a
non-empty local part, exactly one ``@`` separator, and a non-empty domain.
Any string that violates one of those three structural rules must be rejected
(return ``False``) so the pipeline answers 400 and performs no write.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from claim_handler import is_valid_email

# Run >= 100 iterations per the design's property-test convention.
PROPERTY_SETTINGS = settings(max_examples=200)


def _is_malformed(email: str) -> bool:
    """Mirror of the format contract, used to classify generated strings.

    An email is well-formed iff it has exactly one ``@`` and both the part
    before and after it are non-empty. Malformed = the negation of that.
    """
    if email.count("@") != 1:
        return True
    local, _, domain = email.partition("@")
    return not local or not domain


# --- Property 1: Malformed emails are rejected -----------------------------

@PROPERTY_SETTINGS
@given(st.text())
def test_malformed_emails_are_rejected(email: str) -> None:
    """Feature: credential-claim-service, Property 1.

    For ANY generated string, if it is malformed (lacks a non-empty local
    part, a single ``@``, or a non-empty domain), ``is_valid_email`` returns
    ``False``. This is the structural core: a rejected email never reaches a
    write, so the pipeline mutates nothing.
    """
    if _is_malformed(email):
        assert is_valid_email(email) is False


@PROPERTY_SETTINGS
@given(
    local=st.text(min_size=1).filter(lambda s: "@" not in s),
    domain=st.text(min_size=1).filter(lambda s: "@" not in s),
)
def test_well_formed_emails_are_accepted(local: str, domain: str) -> None:
    """Feature: credential-claim-service, Property 1 (converse).

    A string built as ``local@domain`` with non-empty, ``@``-free halves is
    well-formed and must be accepted. Pins the boundary so the rejection
    property above cannot be satisfied by a validator that rejects everything.
    """
    assert is_valid_email(f"{local}@{domain}") is True


# --- Explicit malformed examples (edge cases) ------------------------------

_MALFORMED_EXAMPLES = [
    "",  # empty string
    "local@",  # non-empty local, empty domain
    "@example.com",  # empty local, non-empty domain
    "no-at-sign.example.com",  # zero @
    "two@@ats.com",  # two @
    "a@b@c",  # two @
    "@",  # both halves empty
    "   ",  # whitespace only, no @
]


@PROPERTY_SETTINGS
@given(st.sampled_from(_MALFORMED_EXAMPLES))
def test_known_malformed_examples_are_rejected(email: str) -> None:
    """Feature: credential-claim-service, Property 1 (named edge cases)."""
    assert is_valid_email(email) is False
