"""Audit export for the Credential Claim Service.

Scans the DynamoDB table for ``EMAIL#`` lock items and writes a CSV mapping each
claimed email to the credential it received and the time it was claimed
(Requirement 7.1). The output is a timestamped file under
``claim-service/output/`` which is excluded from version control, since the rows
contain participant emails (PII) (Requirements 7.2, 13.3).

Run via the ``claim-audit`` mise task (or directly) after a workshop and before
teardown. The table name is derived from the workshop id as
``credential-claim-<workshop_id>`` — the same ``local.name`` OpenTofu uses — so
the audit reads exactly the table that workshop's claim service created and no
other workshop's table (Requirements 6.6, 7.6). The workshop id comes from the
``WORKSHOP_ID`` environment variable or ``--workshop-id``; set ``--table`` (or
the legacy ``TABLE_NAME`` env var) only to override the derived name.

Usage::

    WORKSHOP_ID=<slug> python scripts/export_audit.py
    python scripts/export_audit.py --workshop-id <slug>

PII note: emails are read only to produce the git-ignored audit CSV; they are
not logged. Only aggregate counts and the output path are printed.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

# Deployment region for the Claim Service, derived only from the environment
# (AWS_REGION), defaulting to us-east-1 when unset (Requirement 4.2 / 10.1).
# Never hardcoded to a specific region.
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Key prefix identifying an Email_Lock_Item (``EMAIL#<normalized_email>``).
EMAIL_PREFIX = "EMAIL#"

# CSV column order for the Audit_Export (Requirement 7.1).
CSV_HEADER = ("email", "username", "account_id", "claimed_at")

# Audit CSVs land here; the directory is git-ignored (Requirements 7.2, 13.3).
# scripts/ -> claim-service/ -> output/
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

# Each workshop's claim table name is derived as ``credential-claim-<workshop_id>``
# (design: "One claim service per workshop"; claim-service/terraform local.name),
# so the audit reads exactly the table that workshop's claim service created and
# no other workshop's table (Requirements 6.6, 7.6).
TABLE_NAME_PREFIX = "credential-claim-"


def resolve_table_name(workshop_id: str | None, table_override: str | None) -> str:
    """Resolve the claim table name for a workshop.

    Precedence mirrors the seed script (design: "seed/audit derive the table
    name from workshop_id"):

    1. An explicit table override (``--table`` or ``TABLE_NAME``) wins — the
       operator escape hatch for a non-standard name.
    2. Otherwise the name is derived from ``workshop_id`` as
       ``credential-claim-<workshop_id>`` so the audit targets exactly the
       workshop's own table and no other's (Requirements 6.6, 7.6).

    Exits non-zero when neither an override nor a (non-empty, whitespace-
    trimmed) ``workshop_id`` is supplied, so the script never reads a guessed
    or shared table.
    """
    if table_override and table_override.strip():
        return table_override.strip()
    wid = (workshop_id or "").strip()
    if not wid:
        print(
            "ERROR: no table to audit. Supply --workshop-id (or set "
            "WORKSHOP_ID), or set TABLE_NAME to an explicit table name.",
            file=sys.stderr,
        )
        sys.exit(1)
    return f"{TABLE_NAME_PREFIX}{wid}"


def _is_resource_not_found(exc: ClientError) -> bool:
    """True when a botocore ClientError is DynamoDB's ResourceNotFoundException.

    Matched on the error code (not an exception class) so it holds whether the
    error comes from a live client or a stubbed one in tests.
    """
    return (
        exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException"
    )


def email_item_to_row(item: dict[str, Any]) -> dict[str, str]:
    """Map one ``EMAIL#`` DynamoDB item to an audit CSV row.

    Pure and side-effect free so it can be exercised directly in tests
    (Property 11). The email is recovered by stripping the ``EMAIL#`` prefix
    from the item's ``PK``; ``username``, ``account_id`` and ``claimed_at`` are
    read straight from the item, defaulting to empty strings when absent so a
    malformed or pre-change item still produces a row rather than crashing the
    export (Requirement 7.2).

    Returns a dict keyed by :data:`CSV_HEADER` columns.
    """
    pk = str(item.get("PK", ""))
    email = pk.removeprefix(EMAIL_PREFIX)
    return {
        "email": email,
        "username": str(item.get("username", "")),
        "account_id": str(item.get("account_id", "")),
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


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--workshop-id",
        default=os.environ.get("WORKSHOP_ID"),
        help=(
            "Workshop slug used to derive the claim table name "
            "credential-claim-<workshop_id>. Defaults to the WORKSHOP_ID "
            "environment variable. Required unless --table/TABLE_NAME is set."
        ),
    )
    p.add_argument(
        "--table",
        default=os.environ.get("TABLE_NAME"),
        help=(
            "Explicit DynamoDB table name, overriding the name derived from "
            "--workshop-id. Defaults to the TABLE_NAME environment variable."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Export the audit CSV. Returns a process exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    # Resolve the workshop's own table (credential-claim-<workshop_id>) before
    # touching AWS, so a missing/invalid id fails before any request and the
    # audit can only ever read this workshop's table (Requirements 6.6, 7.6).
    table_name = resolve_table_name(args.workshop_id, args.table)

    table = boto3.resource("dynamodb", region_name=REGION).Table(table_name)
    rows = (email_item_to_row(item) for item in scan_email_items(table))

    destination = _timestamped_output_path()
    try:
        count = write_audit_csv(rows, destination)
    except ClientError as exc:
        # The workshop's table does not exist: name the workshop_id and stop
        # without reading any other workshop's table (Requirement 7.7). The scan
        # is lazy, so this is the first request that touches the table — nothing
        # of substance was written yet. Remove the header-only file we opened.
        if _is_resource_not_found(exc):
            try:
                destination.unlink()
            except FileNotFoundError:
                pass
            wid = (args.workshop_id or "").strip()
            print(
                f"ERROR: claim table {table_name!r} for workshop "
                f"{wid or '(unknown)'!r} does not exist. Deploy the claim "
                "service for this workshop before auditing.",
                file=sys.stderr,
            )
            return 1
        raise

    print(f"Wrote {count} claimed-email row(s) to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
