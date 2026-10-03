"""Audit export for the Credential Claim Service.

Scans the DynamoDB table for ``EMAIL#`` lock items and writes a CSV mapping each
claimed email to the credential it received and the time it was claimed
(Requirement 7.1). The output is a timestamped file under
``claim-service/output/`` which is excluded from version control, since the rows
contain participant emails (PII) (Requirements 7.2, 13.3).

Run via the ``claim-audit`` mise task (or directly) after a workshop and before
teardown. The table is read from the ``TABLE_NAME`` environment variable, the
same variable the Lambda handler uses.

Usage::

    TABLE_NAME=<table> python scripts/export_audit.py

PII note: emails are read only to produce the git-ignored audit CSV; they are
not logged. Only aggregate counts and the output path are printed.
"""

from __future__ import annotations

import csv
import os
import sys
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3

# Deployment region for the Claim Service, derived only from the environment
# (AWS_REGION), defaulting to us-east-1 when unset (Requirement 4.2 / 10.1).
# Never hardcoded to a specific region.
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Key prefix identifying an Email_Lock_Item (``EMAIL#<normalized_email>``).
EMAIL_PREFIX = "EMAIL#"

# CSV column order for the Audit_Export (Requirement 7.1).
CSV_HEADER = ("email", "username", "claimed_at")

# Audit CSVs land here; the directory is git-ignored (Requirements 7.2, 13.3).
# scripts/ -> claim-service/ -> output/
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def email_item_to_row(item: dict[str, Any]) -> dict[str, str]:
    """Map one ``EMAIL#`` DynamoDB item to an audit CSV row.

    Pure and side-effect free so it can be exercised directly in tests
    (Property 11). The email is recovered by stripping the ``EMAIL#`` prefix
    from the item's ``PK``; ``username`` and ``claimed_at`` are read straight
    from the item, defaulting to empty strings when absent so a malformed item
    still produces a row rather than crashing the export.

    Returns a dict keyed by :data:`CSV_HEADER` columns.
    """
    pk = str(item.get("PK", ""))
    email = pk.removeprefix(EMAIL_PREFIX)
    return {
        "email": email,
        "username": str(item.get("username", "")),
        "claimed_at": str(item.get("claimed_at", "")),
    }


def scan_email_items(table: Any) -> Iterator[dict[str, Any]]:
    """Yield every ``EMAIL#`` item in the table.

    Uses a ``Scan`` with ``FilterExpression begins_with(PK, "EMAIL#")`` and
    follows ``LastEvaluatedKey`` pagination so a pool larger than one scan page
    is fully covered.
    """
    scan_kwargs: dict[str, Any] = {
        "FilterExpression": "begins_with(PK, :prefix)",
        "ExpressionAttributeValues": {":prefix": EMAIL_PREFIX},
    }
    while True:
        response = table.scan(**scan_kwargs)
        yield from response.get("Items", [])
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return
        scan_kwargs["ExclusiveStartKey"] = last_key


def write_audit_csv(rows: Iterable[dict[str, str]], destination: Path) -> int:
    """Write audit ``rows`` to ``destination`` as CSV and return the row count.

    The parent directory is created if needed. The header is always written,
    so an empty pool yields a header-only file.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CSV_HEADER))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def _timestamped_output_path(now: datetime | None = None) -> Path:
    """Build the ``output/audit-<timestamp>.csv`` path for this run."""
    moment = now or datetime.now(UTC)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")
    return OUTPUT_DIR / f"audit-{stamp}.csv"


def main() -> int:
    """Export the audit CSV. Returns a process exit code."""
    table_name = os.environ.get("TABLE_NAME")
    if not table_name:
        print("TABLE_NAME environment variable is required", file=sys.stderr)
        return 1

    table = boto3.resource("dynamodb", region_name=REGION).Table(table_name)
    rows = (email_item_to_row(item) for item in scan_email_items(table))

    destination = _timestamped_output_path()
    count = write_audit_csv(rows, destination)

    print(f"Wrote {count} claimed-email row(s) to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
