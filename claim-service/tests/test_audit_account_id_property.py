"""Property test for the account ID in the audit export.

Feature: idc-region-account-mapping, Property 7
Property 7: The audit row carries the claimed credential's account ID
Validates: Requirements 7.2

For any ``EMAIL#`` lock item, ``email_item_to_row`` produces a row whose
``account_id`` equals the item's ``account_id`` rendered as a string, defaulting
to ``""`` when the item has no ``account_id`` key. This covers both post-change
items (``account_id`` copied onto the lock at claim time) and pre-change /
malformed items (``account_id`` absent), which must still produce a row with an
empty account rather than crashing the export (Requirement 7.2).
"""

from __future__ import annotations

from export_audit import EMAIL_PREFIX, email_item_to_row
from hypothesis import given, settings
from hypothesis import strategies as st

# An email as it appears after the EMAIL# prefix (see the companion Property 11
# test for the rationale on excluding empty / nested-prefix values). Here the
# email is incidental; Property 7 is about the account_id, so a simple non-empty
# text generator suffices.
email_value = st.text(min_size=1, max_size=40).filter(
    lambda e: not e.startswith(EMAIL_PREFIX)
)

# account_id values stored on a lock item. Real items carry a 12-digit string,
# but the mapping must tolerate anything DynamoDB might surface, so we draw a
# broad set of values. ``None`` here is a sentinel meaning "omit the account_id
# key entirely" (modeling a pre-change or malformed item), handled below.
account_id_value = st.one_of(
    st.none(),
    st.text(min_size=0, max_size=40),
    st.from_regex(r"[0-9]{12}", fullmatch=True),
    st.integers(min_value=0, max_value=10**12),
)

# Other attributes that ride along on the lock item but are irrelevant here.
username_value = st.text(min_size=0, max_size=40)
claimed_at_value = st.text(min_size=0, max_size=40)


@st.composite
def email_items(draw):
    """Draw one EMAIL# item, sometimes omitting the account_id key entirely."""
    email = draw(email_value)
    item = {
        "PK": f"{EMAIL_PREFIX}{email}",
        "username": draw(username_value),
        "claimed_at": draw(claimed_at_value),
    }
    account_id = draw(account_id_value)
    # ``None`` models a pre-change / malformed item with no account_id key.
    if account_id is not None:
        item["account_id"] = account_id
    return item


@settings(max_examples=200)
@given(item=email_items())
def test_audit_row_carries_item_account_id(item):
    """The row's account_id is the item's account_id, defaulting to "".

    When the item carries an ``account_id``, the row reflects it as a string;
    when the key is absent, the row's ``account_id`` is the empty string
    (Requirement 7.2).
    """
    row = email_item_to_row(item)

    expected = str(item.get("account_id", ""))
    assert row["account_id"] == expected

    # A pre-change / malformed item (no account_id key) yields an empty
    # account_id rather than raising.
    if "account_id" not in item:
        assert row["account_id"] == ""
