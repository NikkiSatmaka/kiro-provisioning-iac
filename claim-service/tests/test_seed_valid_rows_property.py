"""Property test for seeding valid rows.

Feature: credential-claim-service, Property 9
Property 9: Seeding writes one available credential per valid row
Validates: Requirements 6.2

For any ``otps.csv`` whose rows each carry a non-empty username and a non-empty
OTP, ``classify_rows`` buckets exactly one ``SeedRow`` per input row (and marks
none invalid), and ``credential_item`` produces exactly one item per row keyed
``CRED#<username>`` with ``status == "available"``.

``seed_claim_pool`` trims surrounding whitespace before judging a field
"non-empty" (classify_row), so a valid row's username/OTP must be non-empty
*after* stripping. The generators below model exactly that input space: values
that remain non-empty once trimmed.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from seed_claim_pool import SeedRow, classify_rows, credential_item

# A field value that is guaranteed non-empty after .strip() — i.e. it contains
# at least one non-whitespace character. This is what the seed script treats as
# a valid (present) username/OTP.
nonempty_after_strip = st.text(min_size=1).filter(lambda s: s.strip() != "")

# One raw CSV row (as csv.DictReader yields it) whose username and otp are both
# present once trimmed.
valid_row = st.fixed_dictionaries(
    {
        "username": nonempty_after_strip,
        "otp": nonempty_after_strip,
    }
)

# Non-empty list of such rows — a whole "valid" otps.csv body.
valid_rows = st.lists(valid_row, min_size=1, max_size=50)

SIGN_IN_URL = st.text(min_size=0, max_size=80)
REGION = st.text(min_size=0, max_size=20)


@settings(max_examples=200)
@given(rows=valid_rows, sign_in_url=SIGN_IN_URL, region=REGION)
def test_classify_rows_marks_every_valid_row_as_one_seedrow(
    rows, sign_in_url, region
):
    """Every valid row becomes exactly one SeedRow; none are invalid."""
    classification = classify_rows(rows)

    # One SeedRow per input row, in order; nothing bucketed invalid.
    assert len(classification.valid) == len(rows)
    assert classification.invalid == []
    assert all(isinstance(sr, SeedRow) for sr in classification.valid)

    # The trimmed username/otp carry through to the SeedRow.
    for raw, seed_row in zip(rows, classification.valid):
        assert seed_row.username == raw["username"].strip()
        assert seed_row.otp == raw["otp"].strip()


@settings(max_examples=200)
@given(rows=valid_rows, sign_in_url=SIGN_IN_URL, region=REGION)
def test_credential_item_is_available_and_keyed_per_valid_row(
    rows, sign_in_url, region
):
    """credential_item yields exactly one available item per valid row.

    Each produced item is keyed ``CRED#<username>`` and carries
    ``status == "available"`` (Requirement 6.2).
    """
    classification = classify_rows(rows)

    items = [
        credential_item(sr, sign_in_url, region) for sr in classification.valid
    ]

    # Exactly one item per valid row.
    assert len(items) == len(classification.valid) == len(rows)

    for seed_row, item in zip(classification.valid, items):
        assert item["PK"] == f"CRED#{seed_row.username}"
        assert item["username"] == seed_row.username
        assert item["otp"] == seed_row.otp
        assert item["status"] == "available"
        assert item["sign_in_url"] == sign_in_url
        assert item["region"] == region
