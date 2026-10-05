"""Example test for audit export backward compatibility.

Feature: idc-region-account-mapping, Task 8.3
Validates: Requirements 7.1

The audit export gained an ``account_id`` column. Pre-change ``EMAIL#`` lock
items were written before that attribute existed, so they carry no
``account_id``. This test pins the backward-compatible behavior: the CSV header
includes the new column, and a pre-change item (``PK`` + ``username`` +
``claimed_at``, no ``account_id``) maps to a row whose ``account_id`` is the
empty string rather than crashing the export.
"""

from __future__ import annotations

from export_audit import CSV_HEADER, EMAIL_PREFIX, email_item_to_row


def test_csv_header_includes_account_id() -> None:
    """The audit CSV header carries the new ``account_id`` column."""
    assert "account_id" in CSV_HEADER


def test_pre_change_email_item_yields_empty_account_id() -> None:
    """A pre-change EMAIL# item (no account_id) maps cleanly with account_id "".

    The item predates the account_id attribute, so it has only the PK, a
    username and a claimed_at. Mapping it must not raise and must default
    account_id to the empty string while preserving the other fields.
    """
    pre_change_item = {
        "PK": f"{EMAIL_PREFIX}participant@example.com",
        "username": "ws-user-01",
        "claimed_at": "2024-01-01T00:00:00Z",
    }

    row = email_item_to_row(pre_change_item)

    assert row["account_id"] == ""
    assert row["email"] == "participant@example.com"
    assert row["username"] == "ws-user-01"
    assert row["claimed_at"] == "2024-01-01T00:00:00Z"
    # The row covers exactly the CSV columns, including the new one.
    assert set(row) == set(CSV_HEADER)
