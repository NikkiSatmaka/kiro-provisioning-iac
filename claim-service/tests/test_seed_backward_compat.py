"""Example tests for seed-script backward compatibility.

Feature: idc-region-account-mapping, Task 5.4

Threading a child AWS ``account_id`` through the seed pipeline must not disturb
the inputs the pre-change seed already consumed:

* The ``otps.csv`` contract is unchanged — the header is still ``username,otp``
  and an existing-style CSV loads via ``load_rows`` exactly as before.
* Account resolution degrades gracefully: a username present in the OTP CSV but
  absent from the manifest ``users`` map falls back to the document-level
  ``account_id``; when that is also empty it falls back to ``""``. OTP-only rows
  therefore still seed, carrying an empty ``account_id`` rather than failing.

These are example tests (not property tests); they pin the specific backward-
compatibility facts rather than quantifying over inputs. The account-resolution
rule is exercised through the pure/lookup path (the same
``lookup.get(username, account_id)`` precedence ``seed`` applies before calling
``credential_item``), so no AWS is involved.

Validates: Requirements 8.1
"""

from __future__ import annotations

import pathlib

from seed_claim_pool import (
    SeedRow,
    classify_rows,
    credential_item,
    load_rows,
)


def _resolve_account_id(
    username: str, user_account_map: dict[str, str], account_id: str
) -> str:
    """Mirror ``seed``'s per-user account resolution precedence.

    ``seed`` resolves each row's account as ``lookup.get(row.username,
    account_id)`` — the manifest-derived per-user map first, then the
    document-level default (itself defaulting to ``""``). This helper replays
    that exact precedence so the example asserts against the real rule without
    the AWS write path.
    """
    return user_account_map.get(username, account_id)


# ---------------------------------------------------------------------------
# otps.csv contract: header stays username,otp and existing CSVs still load
# ---------------------------------------------------------------------------


def test_existing_style_otps_csv_header_and_rows_load_unchanged(
    tmp_path: pathlib.Path,
) -> None:
    """A pre-change ``otps.csv`` (header ``username,otp``, no extra columns)
    loads via ``load_rows`` and classifies exactly as before.

    Validates: Requirements 8.1.
    """
    csv_path = tmp_path / "otps.csv"
    csv_path.write_text(
        "username,otp\n"
        "alice,otp-aaa\n"
        "bob,otp-bbb\n"
    )

    rows = load_rows(csv_path)

    # The header is exactly username,otp — no new column was introduced, and
    # each row exposes only those two fields.
    assert [set(row.keys()) for row in rows] == [{"username", "otp"}, {"username", "otp"}]
    assert rows == [
        {"username": "alice", "otp": "otp-aaa"},
        {"username": "bob", "otp": "otp-bbb"},
    ]

    # Classification behaves as before: both rows are valid, none invalid.
    classification = classify_rows(rows)
    assert classification.invalid == []
    assert [sr.username for sr in classification.valid] == ["alice", "bob"]
    assert [sr.otp for sr in classification.valid] == ["otp-aaa", "otp-bbb"]


# ---------------------------------------------------------------------------
# Account resolution fallback: manifest map -> document account_id -> ""
# ---------------------------------------------------------------------------


def test_username_absent_from_manifest_falls_back_to_document_account_id() -> None:
    """A username in the OTP CSV but not in the manifest ``users`` map resolves
    to the document-level ``account_id`` (not to ``""``).

    Validates: Requirements 8.1.
    """
    row = SeedRow(username="carol", otp="otp-ccc")
    user_account_map: dict[str, str] = {}  # carol has no per-user entry
    document_account_id = "123456789012"

    resolved = _resolve_account_id("carol", user_account_map, document_account_id)
    assert resolved == document_account_id

    item = credential_item(row, "https://signin", "ap-southeast-1", resolved)
    assert item["account_id"] == document_account_id
    # The rest of the item is well-formed and still seeds as before.
    assert item["PK"] == "CRED#carol"
    assert item["status"] == "available"


def test_username_absent_and_empty_document_account_id_falls_back_to_empty() -> None:
    """When the username is absent from the manifest map AND the document-level
    ``account_id`` is empty (a pre-change manifest), resolution yields ``""`` and
    the OTP-only row still produces a well-formed item.

    Validates: Requirements 8.1.
    """
    row = SeedRow(username="dave", otp="otp-ddd")
    user_account_map: dict[str, str] = {}
    document_account_id = ""  # pre-change manifest predates the field

    resolved = _resolve_account_id("dave", user_account_map, document_account_id)
    assert resolved == ""

    item = credential_item(row, "https://signin", "ap-southeast-1", resolved)
    assert item["account_id"] == ""
    # Empty account_id does not break the item: it still seeds as before.
    assert item["PK"] == "CRED#dave"
    assert item["username"] == "dave"
    assert item["otp"] == "otp-ddd"
    assert item["status"] == "available"


def test_credential_item_account_id_defaults_to_empty_when_omitted() -> None:
    """``credential_item`` keeps its pre-change call shape: omitting
    ``account_id`` defaults it to ``""`` so existing callers/items are unchanged.

    Validates: Requirements 8.1.
    """
    row = SeedRow(username="erin", otp="otp-eee")
    item = credential_item(row, "https://signin", "ap-southeast-1")
    assert item["account_id"] == ""
