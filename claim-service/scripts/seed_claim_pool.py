#!/usr/bin/env python3
"""Seed the Credential Claim Service pool from the subscription/ outputs.

WHAT THIS DOES
--------------
Populates the single DynamoDB table that backs the claim service with one
``CRED#<username>`` item per provisioned IdC user, so those credentials become
claimable by workshop participants (Requirements 6.1, 6.2, 6.3).

Inputs are the plain-file outputs the `subscription/` provisioning flow already
produces (this script never calls a `subscription/` resource — it only reads two
files and writes the claim table):

  * ``otps.csv``      — header ``username,otp``; one row per credential.
  * ``manifest.json`` — the exported ``provisioning_manifest`` tofu output,
                        read only for ``sign_in_url`` and ``region``.

For each VALID row (non-empty username AND non-empty OTP) it writes a credential
item::

    PK          = "CRED#<username>"
    username    = <username>
    otp         = <otp>
    sign_in_url = <from manifest>
    region      = <from manifest>
    status      = "available"

The ``PutItem`` is CONDITIONAL on ``attribute_not_exists(PK)`` so re-running the
seed is safe: an already-present (possibly already-claimed) credential is left
untouched rather than reset to ``available`` (design: "Seed script"). A row that
is missing a username or an OTP is reported to stderr and skipped — no item is
written for it (Requirement 6.3).

Row classification (valid / invalid-which-field) is factored into the pure
``classify_rows`` function so it is unit- and property-testable without AWS.

USAGE
-----
  # Dry run — classify + report, write nothing (safe, default):
  python seed_claim_pool.py \
      --otp-csv ../../subscription/output/otps.csv \
      --manifest ../../subscription/output/manifest.json \
      --table claim-service

  # Actually write the pool:
  python seed_claim_pool.py \
      --otp-csv ../../subscription/output/otps.csv \
      --manifest ../../subscription/output/manifest.json \
      --table claim-service \
      --apply

The table name must match the deployed table (OpenTofu ``var.table_name``).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import sys
from dataclasses import dataclass, field

import boto3

# ---------------------------------------------------------------------------
# Pure, AWS-free row processing (unit/property testable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SeedRow:
    """A single credential to seed, derived from one valid otps.csv row."""

    username: str
    otp: str


@dataclass(frozen=True)
class InvalidRow:
    """A skipped row, with the 1-based CSV line number and why it was skipped."""

    line: int
    reason: str
    raw: dict[str, str]


@dataclass
class Classification:
    """Result of classifying the rows of an otps.csv file."""

    valid: list[SeedRow] = field(default_factory=list)
    invalid: list[InvalidRow] = field(default_factory=list)


def classify_row(raw: dict[str, str], line: int) -> SeedRow | InvalidRow:
    """Classify one CSV row as a valid SeedRow or an InvalidRow.

    A row is valid only when it has BOTH a non-empty (trimmed) username and a
    non-empty (trimmed) OTP (Requirement 6.3). The username and OTP are trimmed
    of surrounding whitespace before use. This function is pure: it performs no
    I/O and no AWS calls, so it can be exercised directly by tests.
    """
    username = (raw.get("username") or "").strip()
    otp = (raw.get("otp") or "").strip()

    if not username and not otp:
        return InvalidRow(line=line, reason="missing username and otp", raw=raw)
    if not username:
        return InvalidRow(line=line, reason="missing username", raw=raw)
    if not otp:
        return InvalidRow(line=line, reason="missing otp", raw=raw)
    return SeedRow(username=username, otp=otp)


def classify_rows(rows: list[dict[str, str]]) -> Classification:
    """Classify every CSV row, preserving order, into valid/invalid buckets.

    ``rows`` are the dict rows as yielded by ``csv.DictReader`` (header already
    consumed). Line numbers are 1-based over the data rows (the first data row
    is line 1), matching how an operator would count rows under the header.
    """
    result = Classification()
    for idx, raw in enumerate(rows, start=1):
        outcome = classify_row(raw, idx)
        if isinstance(outcome, SeedRow):
            result.valid.append(outcome)
        else:
            result.invalid.append(outcome)
    return result


def credential_item(row: SeedRow, sign_in_url: str, region: str) -> dict[str, str]:
    """Build the DynamoDB item for one valid credential row.

    Pure: given a valid row plus the manifest-derived sign-in URL and region,
    returns the exact attribute map the seed PutItem writes. ``status`` is always
    ``"available"`` for a freshly seeded credential (Requirement 6.2).
    """
    return {
        "PK": f"CRED#{row.username}",
        "username": row.username,
        "otp": row.otp,
        "sign_in_url": sign_in_url,
        "region": region,
        "status": "available",
    }


# ---------------------------------------------------------------------------
# Input loading (file I/O — thin wrappers that fail closed with a clear message)
# ---------------------------------------------------------------------------

def load_rows(path: pathlib.Path) -> list[dict[str, str]]:
    """Read otps.csv into a list of dict rows. Fails closed if the file or the
    required ``username,otp`` header is absent."""
    if not path.exists():
        sys.exit(f"ERROR: otps CSV not found: {path}")
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        if "username" not in fields or "otp" not in fields:
            sys.exit("ERROR: otps CSV must have a header row: username,otp")
        return list(reader)


def load_manifest(path: pathlib.Path) -> tuple[str, str]:
    """Read ``sign_in_url`` and ``region`` from the manifest (Requirement 6.1).

    Accepts both the raw ``tofu output -json <name>`` shape and the wrapped
    ``{"value": ...}`` shape emitted by ``tofu output -json`` (all outputs),
    mirroring subscription/scripts/provision_passwords_and_output.py.
    """
    if not path.exists():
        sys.exit(
            f"ERROR: manifest not found: {path}\n"
            f"Generate it first:  tofu output -json provisioning_manifest > {path}"
        )
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        sys.exit(f"ERROR: manifest is not valid JSON: {exc}")

    if isinstance(data, dict) and "value" in data and "region" not in data:
        data = data["value"]

    region = (data.get("region") or "").strip()
    sign_in_url = (data.get("sign_in_url") or "").strip()
    if not region:
        sys.exit("ERROR: manifest is missing 'region'.")
    if not sign_in_url:
        sys.exit(
            "ERROR: manifest is missing 'sign_in_url'. Export it into the "
            "manifest (the sign-in URL is obtained from the Kiro console) before "
            "seeding so claimed credentials carry a usable URL."
        )
    return sign_in_url, region


# ---------------------------------------------------------------------------
# Seeding (AWS write path)
# ---------------------------------------------------------------------------

def seed(
    table,
    rows: Classification,
    sign_in_url: str,
    region: str,
    *,
    apply: bool,
) -> tuple[int, int]:
    """Write one conditional CRED# item per valid row; report invalid rows.

    Returns ``(written, skipped_existing)``. The PutItem is conditional on
    ``attribute_not_exists(PK)`` so an already-seeded credential (which may now
    be claimed) is never clobbered — a condition failure is reported and
    counted as skipped, not raised. Invalid rows were already filtered out by
    ``classify_rows``; they are reported here for the operator.
    """
    for bad in rows.invalid:
        print(
            f"SKIP (line {bad.line}): {bad.reason} -> {dict(bad.raw)}",
            file=sys.stderr,
        )

    if not apply:
        print(
            f"DRY RUN: would write {len(rows.valid)} credential(s); "
            f"skipped {len(rows.invalid)} invalid row(s). "
            f"Re-run with --apply to write.",
            file=sys.stderr,
        )
        return 0, 0

    written = 0
    skipped_existing = 0
    for row in rows.valid:
        item = credential_item(row, sign_in_url, region)
        try:
            table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK)",
            )
            written += 1
            print(f"PUT  CRED#{row.username} (available)")
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            # Already present (possibly already claimed) — leave it untouched.
            skipped_existing += 1
            print(
                f"KEEP CRED#{row.username} (already present; not overwritten)",
                file=sys.stderr,
            )
    return written, skipped_existing


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--otp-csv",
        required=True,
        type=pathlib.Path,
        help="Path to otps.csv (header: username,otp).",
    )
    p.add_argument(
        "--manifest",
        required=True,
        type=pathlib.Path,
        help="Path to manifest.json (source of sign_in_url and region).",
    )
    p.add_argument(
        "--table",
        required=True,
        help="DynamoDB table name (OpenTofu var.table_name).",
    )
    p.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", "us-east-1"),
        help=(
            "AWS region the table lives in. Defaults to AWS_REGION from the "
            "environment, or us-east-1 when unset."
        ),
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually write items. Without this flag the script is a dry run.",
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    sign_in_url, region = load_manifest(args.manifest)
    rows = classify_rows(load_rows(args.otp_csv))

    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)
    written, skipped_existing = seed(
        table, rows, sign_in_url, region, apply=args.apply
    )

    if args.apply:
        print(
            f"Done: wrote {written} credential(s), "
            f"kept {skipped_existing} existing, "
            f"skipped {len(rows.invalid)} invalid row(s)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
