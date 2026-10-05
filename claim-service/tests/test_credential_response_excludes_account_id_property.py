"""Property test: the claim response excludes the account ID.

Feature: idc-region-account-mapping, Property 8: ``_credential_response``
returns exactly the four participant-facing fields and leaks no internal
attribute.

Validates: Requirements 8.2, 8.3

``_credential_response`` projects a ``CRED#`` item down to the HTTP 200 success
body. Requirement 8.3 fixes that body to EXACTLY the username, one-time
password, sign-in URL, and region; Requirement 8.2 adds that the account ID in
particular must never appear. This test exercises the projector *directly* (the
whole-handler counterpart lives in ``test_success_four_fields_property.py``):
for ANY ``CRED#`` item — including one carrying ``account_id`` plus any other
internal attributes (``status``, ``claimed_by_email``, ``claimed_at``, ``PK``,
and arbitrary extras) — the returned object's key set is EXACTLY
``{username, otp, sign_in_url, region}``, its values equal the item's values for
those four keys, and it contains ``account_id`` under no circumstance.
"""

from __future__ import annotations

import claim_handler
from hypothesis import given, settings
from hypothesis import strategies as st

# The four fields the 200 contract promises — nothing more may appear (R8.3).
EXPECTED_KEYS = {"username", "otp", "sign_in_url", "region"}

# Opaque, round-trippable field text: non-empty, no surrogate code points so the
# values survive JSON/DynamoDB serialization in production. The projector treats
# every field as an opaque string, so this models the seeded input space well.
field_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=40,
)

# Internal attribute keys a real CRED# item may carry beyond the four public
# fields. account_id is the attribute Requirement 8.2 specifically forbids in the
# response; the rest model the status/audit bookkeeping a claimed credential
# gains. Any value is fine — none of them may leak.
internal_keys = st.sampled_from(
    ["PK", "status", "claimed_by_email", "claimed_at", "account_id"]
)

# Arbitrary extra attribute keys that are NOT one of the four public fields, so a
# generated "extra" bag never accidentally supplies a public field. This proves
# the projector ignores *any* unknown internal attribute, not just the known set.
extra_keys = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=20,
).filter(lambda k: k not in EXPECTED_KEYS)


@st.composite
def cred_items(draw) -> dict:
    """Draw a CRED# item: the four public fields plus arbitrary internals.

    Always includes the four public fields, always includes ``account_id`` (the
    attribute R8.2 forbids in the response), and may include any subset of the
    other internal keys plus an arbitrary bag of extra attributes. Extra keys
    are constrained out of the four public fields so they cannot stand in for a
    required value.
    """
    item = {
        "username": draw(field_text),
        "otp": draw(field_text),
        "sign_in_url": draw(field_text),
        "region": draw(field_text),
        # account_id is ALWAYS present so every example proves non-leakage of
        # the specifically-forbidden attribute (R8.2), not merely of generic
        # internals.
        "account_id": draw(field_text),
    }
    # A subset of the known internal attributes a claimed credential carries.
    for key in draw(st.lists(internal_keys, unique=True)):
        if key not in item:
            item[key] = draw(field_text)
    # An arbitrary bag of further internal attributes (keys guaranteed not to
    # be one of the four public fields).
    item.update(draw(st.dictionaries(extra_keys, field_text, max_size=5)))
    return item


@settings(max_examples=200)
@given(item=cred_items())
def test_credential_response_excludes_account_id(item: dict) -> None:
    """The response is exactly the four fields and never leaks account_id.

    Feature: idc-region-account-mapping, Property 8
    Validates: Requirements 8.2, 8.3
    """
    response = claim_handler._credential_response(item)

    # EXACTLY the four public fields — no more, no fewer (R8.3). This also proves
    # account_id, status, claimed_by_email, claimed_at, PK and every arbitrary
    # extra attribute were dropped (R8.2, R8.3).
    assert set(response.keys()) == EXPECTED_KEYS, response

    # account_id in particular never appears, however it was spelled on input.
    assert "account_id" not in response

    # The four returned values equal the item's values for those keys.
    for key in EXPECTED_KEYS:
        assert response[key] == item[key]
