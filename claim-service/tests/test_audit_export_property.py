"""Property test for the audit export.

Feature: credential-claim-service, Property 11
Property 11: The audit export covers every claimed email
Validates: Requirements 7.1

For any set of ``EMAIL#`` lock items (each ``PK = "EMAIL#<email>"`` with a
``username`` and a ``claimed_at``), mapping each item through
``email_item_to_row`` and writing the rows with ``write_audit_csv`` yields
exactly one CSV data row per item — no more, no fewer — and every row maps the
recovered email (the ``EMAIL#`` prefix stripped) to that item's ``username`` and
``claimed_at``. In other words, the export covers every claimed email exactly
once.

Emails are modeled as a *set*: the live service keeps one ``EMAIL#`` lock item
per Normalized_Email (``PK`` is unique), so the generated items carry distinct
emails. The CSV is written under a ``tmp_path`` so the test never touches the
real git-ignored ``output/`` directory.
"""

from __future__ import annotations

import csv
import uuid

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from export_audit import (
    CSV_HEADER,
    EMAIL_PREFIX,
    email_item_to_row,
    write_audit_csv,
)

# An email as it appears after the EMAIL# prefix. We exclude the empty string
# so each item models a genuinely claimed email, and exclude any value that
# itself begins with the EMAIL# prefix. The latter reflects a real production
# invariant: the service derives the PK as ``EMAIL#<normalized_email>`` from a
# normalized email (lowercase + strip of an address with a single ``@``), so a
# stored email is never itself a literal ``EMAIL#...`` string and a *nested*
# ``EMAIL#EMAIL#...`` PK cannot occur. Generating one would make
# ``removeprefix(EMAIL_PREFIX)`` strip only the outer prefix and leave an
# ``EMAIL#``-leading value — an input the live key space never produces.
email_value = st.text(min_size=1, max_size=40).filter(
    lambda e: not e.startswith(EMAIL_PREFIX)
)

# Free-form attribute values that ride along on the lock item.
username_value = st.text(min_size=0, max_size=40)
claimed_at_value = st.text(min_size=0, max_size=40)


@st.composite
def email_item_sets(draw):
    """Draw a set of EMAIL# items with distinct emails (one lock per email)."""
    emails = draw(
        st.lists(email_value, min_size=0, max_size=30, unique=True)
    )
    items = []
    for email in emails:
        items.append(
            {
                "PK": f"{EMAIL_PREFIX}{email}",
                "username": draw(username_value),
                "claimed_at": draw(claimed_at_value),
            }
        )
    return items


# ``tmp_path`` is function-scoped, so Hypothesis reuses the same directory
# across generated examples. That is safe here: each example writes to a fresh
# uniquely-named file and reads only that file back, so no state leaks between
# inputs. Suppress the health check that warns about the shared fixture.
@settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(items=email_item_sets())
def test_audit_export_covers_every_claimed_email(items, tmp_path):
    """Every EMAIL# item becomes exactly one audit row, round-tripping cleanly.

    The CSV holds one data row per input item (no more, no fewer), and each row
    recovers the email (EMAIL# prefix stripped) alongside that item's username
    and claimed_at (Requirement 7.1).
    """
    rows = [email_item_to_row(item) for item in items]

    destination = tmp_path / f"audit-{uuid.uuid4().hex}.csv"
    count = write_audit_csv(rows, destination)

    # One mapped row per claimed email — no more, no fewer.
    assert count == len(items)

    # Read the CSV back the way an operator would.
    with destination.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(CSV_HEADER)
        read_rows = list(reader)

    # Exactly one data row per item.
    assert len(read_rows) == len(items)

    # The export covers every claimed email exactly once, each mapped to its
    # own username and claimed_at — compare as sets of (email, username,
    # claimed_at) triples so order does not matter and duplicates would show up.
    expected = {
        (
            item["PK"].removeprefix(EMAIL_PREFIX),
            item["username"],
            item["claimed_at"],
        )
        for item in items
    }
    actual = {
        (row["email"], row["username"], row["claimed_at"])
        for row in read_rows
    }
    assert actual == expected

    # Every recovered email carries the EMAIL# prefix stripped (none leaks it).
    assert all(not row["email"].startswith(EMAIL_PREFIX) for row in read_rows)
