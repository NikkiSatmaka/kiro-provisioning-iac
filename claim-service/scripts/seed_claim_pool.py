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
      --workshop-id kiro-2025-10-10

  # Actually write the pool:
  python seed_claim_pool.py \
      --otp-csv ../../subscription/output/otps.csv \
      --manifest ../../subscription/output/manifest.json \
      --workshop-id kiro-2025-10-10 \
      --apply

The table name is derived from the workshop id as
``credential-claim-<workshop_id>`` — the same ``local.name`` OpenTofu uses — so
the seed targets exactly the table that workshop's claim service created
(Requirements 6.5, 7.6). ``--workshop-id`` defaults to the ``WORKSHOP_ID``
environment variable; pass ``--table`` only to override the derived name.
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
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Workshop-scoped table-name resolution
# ---------------------------------------------------------------------------
# Each workshop deploys its own claim table whose name OpenTofu derives as
# ``credential-claim-<workshop_id>`` (design: "One claim service per workshop";
# claim-service/terraform local.name). The seed/audit scripts resolve the same
# name from the workshop id so they target exactly the table that workshop's
# Claim_Service_Terraform created, and no other workshop's table (Requirements
# 6.5, 7.6).

TABLE_NAME_PREFIX = "credential-claim-"


def resolve_table_name(workshop_id: str | None, table_override: str | None) -> str:
    """Resolve the claim table name for a workshop.

    Precedence (design: "seed/audit derive the table name from workshop_id"):

    1. An explicit ``--table`` override wins when given — an operator escape
       hatch for a non-standard table name.
    2. Otherwise the name is derived from ``workshop_id`` as
       ``credential-claim-<workshop_id>`` (the same ``local.name`` OpenTofu
       uses), so the seed targets exactly the workshop's own table and no
       other's (Requirements 6.5, 7.6).

    Exits non-zero when neither a ``--table`` override nor a (non-empty,
    whitespace-trimmed) ``workshop_id`` is supplied, so the script never falls
    back to a guessed or shared table name.
    """
    if table_override and table_override.strip():
        return table_override.strip()
    wid = (workshop_id or "").strip()
    if not wid:
        sys.exit(
            "ERROR: no table to seed. Supply --workshop-id (or set WORKSHOP_ID), "
            "or pass an explicit --table name."
        )
    return f"{TABLE_NAME_PREFIX}{wid}"


def _is_resource_not_found(exc: ClientError) -> bool:
    """True when a botocore ClientError is DynamoDB's ResourceNotFoundException.

    The claim table is addressed by name, so a missing table surfaces on the
    first request as ``ResourceNotFoundException``. We match on the error code
    rather than an exception class so the check holds whether the error is
    raised by a live client or a stubbed one in tests.
    """
    return (
        exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException"
    )

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


def credential_item(
    row: SeedRow, sign_in_url: str, region: str, account_id: str = ""
) -> dict[str, str]:
    """Build the DynamoDB item for one valid credential row.

    Pure: given a valid row plus the manifest-derived sign-in URL, region, and
    the account ID the user maps to, returns the exact attribute map the seed
    PutItem writes. ``status`` is always ``"available"`` for a freshly seeded
    credential (Requirement 6.2).

    ``account_id`` is operator-facing only: it is stamped onto the ``CRED#``
    item (Requirements 5.3, 8.1) but is never projected into the participant
    claim response. It defaults to ``""`` so an OTP-only row (or a manifest that
    predates the field) still produces a well-formed item.
    """
    return {
        "PK": f"CRED#{row.username}",
        "username": row.username,
        "otp": row.otp,
        "sign_in_url": sign_in_url,
        "region": region,
        "account_id": account_id,
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


def load_manifest(path: pathlib.Path) -> tuple[str, str, str, dict[str, str]]:
    """Read sign-in URL, region, and account info from the manifest.

    Returns ``(sign_in_url, region, account_id, user_account_map)``:

    * ``sign_in_url`` / ``region`` — as before (Requirement 6.1). ``region``
      stays the deployment region stamped on each credential; it is NOT
      repurposed for the Kiro sign-in region.
    * ``account_id`` — the document-level member AWS account ID for billing
      attribution (default ``""``
      for pre-change manifests that predate the field) (Requirement 5.1).
    * ``user_account_map`` — a ``username -> account_id`` lookup built from the
      manifest ``users`` map. Because the OTP CSV is keyed by ``username`` (not
      by the manifest's padded-sequence key), the seed resolves each user's
      account via this lookup (Requirement 5.3). Users whose manifest entry
      lacks an ``account_id`` are omitted so the seed can fall back to the
      document-level default.

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
    # Document-level account ID: default "" for manifests predating the field.
    account_id = (data.get("account_id") or "").strip()
    if not region:
        sys.exit("ERROR: manifest is missing 'region'.")
    if not sign_in_url:
        sys.exit(
            "ERROR: manifest is missing 'sign_in_url'. Export it into the "
            "manifest (the sign-in URL is obtained from the Kiro console) before "
            "seeding so claimed credentials carry a usable URL."
        )

    # Build a username -> account_id lookup from the manifest users map. Each
    # users[k] entry carries { username, account_id, ... }; we key by username
    # (what the OTP CSV uses). Entries without a username or a non-empty
    # account_id are skipped so OTP-only rows fall back to the document-level id.
    user_account_map: dict[str, str] = {}
    users = data.get("users") or {}
    if isinstance(users, dict):
        for entry in users.values():
            if not isinstance(entry, dict):
                continue
            username = (entry.get("username") or "").strip()
            user_account_id = (entry.get("account_id") or "").strip()
            if username and user_account_id:
                user_account_map[username] = user_account_id

    return sign_in_url, region, account_id, user_account_map


# ---------------------------------------------------------------------------
# Seeding (AWS write path)
# ---------------------------------------------------------------------------

def seed(
    table,
    rows: Classification,
    sign_in_url: str,
    region: str,
    account_id: str = "",
    user_account_map: dict[str, str] | None = None,
    *,
    apply: bool,
) -> tuple[int, int]:
    """Write one conditional CRED# item per valid row; report invalid rows.

    Returns ``(written, skipped_existing)``. The PutItem is conditional on
    ``attribute_not_exists(PK)`` so an already-seeded credential (which may now
    be claimed) is never clobbered — a condition failure is reported and
    counted as skipped, not raised. Invalid rows were already filtered out by
    ``classify_rows``; they are reported here for the operator.

    Each item's ``account_id`` is resolved per user: the manifest-derived
    ``user_account_map`` is consulted first (keyed by username), falling back to
    the document-level ``account_id``, then to ``""`` for an OTP-only row with
    no manifest entry and no document default (Requirements 5.3, 8.1).
    """
    lookup = user_account_map or {}
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
        row_account_id = lookup.get(row.username, account_id)
        item = credential_item(row, sign_in_url, region, row_account_id)
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
        "--workshop-id",
        default=os.environ.get("WORKSHOP_ID"),
        help=(
            "Workshop slug used to derive the claim table name "
            "credential-claim-<workshop_id>. Defaults to the WORKSHOP_ID "
            "environment variable. Required unless --table is given."
        ),
    )
    p.add_argument(
        "--table",
        default=None,
        help=(
            "Explicit DynamoDB table name, overriding the name derived from "
            "--workshop-id. Normally omitted so the name is derived from the "
            "workshop id."
        ),
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
    # account_id is the document-level default; user_account_map resolves each
    # user's account by username. Both are stamped onto the CRED# items by
    # seed() -> credential_item (Requirements 5.3, 8.1).
    sign_in_url, region, account_id, user_account_map = load_manifest(
        args.manifest
    )
    rows = classify_rows(load_rows(args.otp_csv))

    # Resolve the workshop's own table name (credential-claim-<workshop_id>)
    # before touching AWS, so a missing/invalid id fails before any request and
    # the seed can only ever address this workshop's table (Requirements 6.5,
    # 7.6).
    table_name = resolve_table_name(args.workshop_id, args.table)
    table = boto3.resource("dynamodb", region_name=args.region).Table(table_name)
    try:
        written, skipped_existing = seed(
            table,
            rows,
            sign_in_url,
            region,
            account_id,
            user_account_map,
            apply=args.apply,
        )
    except ClientError as exc:
        # The workshop's table does not exist: name the workshop_id and stop
        # without touching any other workshop's table (Requirement 7.7).
        if _is_resource_not_found(exc):
            wid = (args.workshop_id or "").strip()
            sys.exit(
                f"ERROR: claim table {table_name!r} for workshop "
                f"{wid or '(unknown)'!r} does not exist. Deploy the claim "
                "service for this workshop before seeding."
            )
        raise

    if args.apply:
        print(
            f"Done: wrote {written} credential(s), "
            f"kept {skipped_existing} existing, "
            f"skipped {len(rows.invalid)} invalid row(s)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
