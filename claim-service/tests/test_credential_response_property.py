"""Property test: the claim response excludes account_id.

Feature: multi-workshop-provisioning, Property 11: claim response excludes
account_id.

Validates: Requirements 4.7

Requirement 4.7 states the Claim_Response SHALL exclude the Account_Id from its
payload. ``_credential_response`` is the pure projector that builds that
payload: it maps a ``CRED#`` item down to the HTTP 200 success body. Under the
multi-workshop structure each participant's credential carries a resolved
``account_id`` (Requirement 4.3), so the item handed to the projector OFTEN
holds that attribute — yet the participant-facing response must never surface
it (Requirement 4.7), nor any other internal attribute.

This test exercises the projector *directly* over a space of ``CRED#`` items
that always carry the four public fields plus ``status``, frequently carry
``account_id``, and may carry an arbitrary bag of other internal attributes. For
EVERY such item the returned object's key set must be EXACTLY
``{username, otp, sign_in_url, region}`` — so ``account_id`` is dropped even
when the input item carries one.
"""

from __future__ import annotations

import claim_handler
from hypothesis import given, settings
from hypothesis import strategies as st

# The four fields the 200 contract promises — nothing more may appear (R4.7).
EXPECTED_KEYS = {"username", "otp", "sign_in_url", "region"}

# Opaque, round-trippable field text: non-empty, no surrogate code points so the
# values survive JSON/DynamoDB serialization in production. The projector treats
# every field as an opaque string, so this models the seeded input space well.
field_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=40,
)

# A resolved Account_Id as it appears on a CRED# item: a 12-digit AWS account
# identifier (Requirement 4, Account_Id). Modelling the real shape keeps the
# generated items faithful to what the handler actually seeds.
account_id = st.text(alphabet="0123456789", min_size=12, max_size=12)

# Arbitrary extra internal attribute keys that are NOT one of the four public
# fields (and never "account_id", which we add explicitly), so a generated
# "extra" bag can never accidentally stand in for a public field or for the
# attribute under test. This proves the projector ignores ANY internal
# attribute, not just the known ones.
extra_keys = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=20,
).filter(lambda k: k not in EXPECTED_KEYS and k != "account_id")


@st.composite
def cred_items(draw) -> dict:
    """Draw a ``CRED#`` item: the four public fields plus internals.

    Always includes the four public fields and ``status`` (a claimed/available
    credential always has one). ``account_id`` is included *often* (but not
    always) so the sample contains both items that carry the forbidden
    attribute and items that do not — the response must omit it in the first
    case and still return exactly four fields in the second. An arbitrary bag of
    further internal attributes (keys guaranteed not to be a public field or
    ``account_id``) models the rest of a real item's bookkeeping.
    """
    item = {
        "username": draw(field_text),
        "otp": draw(field_text),
        "sign_in_url": draw(field_text),
        "region": draw(field_text),
        "status": draw(st.sampled_from(["available", "claimed"])),
    }
    # Often — but not always — attach a resolved account_id, so the sample
    # spans both the carries-account_id and the no-account_id cases.
    if draw(st.booleans()):
        item["account_id"] = draw(account_id)
    # An arbitrary bag of further internal attributes a real item may hold.
    item.update(draw(st.dictionaries(extra_keys, field_text, max_size=5)))
    return item


@settings(max_examples=200)
@given(item=cred_items())
def test_credential_response_excludes_account_id(item: dict) -> None:
    """The response is exactly four fields and never leaks account_id.

    Feature: multi-workshop-provisioning, Property 11
    Validates: Requirements 4.7
    """
    response = claim_handler._credential_response(item)

    # EXACTLY the four public fields — no more, no fewer. This simultaneously
    # proves account_id, status and every arbitrary internal attribute were
    # dropped (R4.7).
    assert set(response.keys()) == EXPECTED_KEYS, response

    # account_id in particular never appears, even when the input item carried
    # one (the case R4.7 is specifically about).
    assert "account_id" not in response

    # The four returned values equal the item's values for those keys.
    for key in EXPECTED_KEYS:
        assert response[key] == item[key]
