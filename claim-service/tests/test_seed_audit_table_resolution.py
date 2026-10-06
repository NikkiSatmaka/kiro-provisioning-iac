"""Example tests for seed/audit table-name resolution and the not-found path.

Feature: multi-workshop-provisioning, Task 7.6
Validates: Requirements 7.6, 7.7

Task 7.2 made both operator scripts resolve their DynamoDB table from the
workshop id as ``credential-claim-<workshop_id>`` (the same ``local.name``
OpenTofu derives), with an explicit ``--table`` override, and added a
``ResourceNotFoundException`` path that fails closed. These example tests pin
two facts per script:

1. **Resolution** — ``resolve_table_name`` returns
   ``credential-claim-<workshop_id>`` for a sample id, and an explicit override
   wins over the derived name (Requirement 7.6).

2. **Not-found path** — running the script against a *missing* table exits
   non-zero, the error message names the ``workshop_id`` (and the derived table
   name), and no OTHER workshop's table is touched (Requirement 7.7).

The not-found path is simulated with ``moto`` (``mock_aws``) — the same way the
rest of the claim-service suite mocks AWS. We stand up exactly ONE table, for a
*different* workshop, seed it, then point the script at the current workshop's
(absent) table. The first request against the absent table surfaces as
``ResourceNotFoundException``; afterwards we re-read the other workshop's table
to prove it was left byte-for-byte intact.
"""

from __future__ import annotations

import pathlib

import boto3
import pytest
from export_audit import TABLE_NAME_PREFIX as AUDIT_PREFIX
from export_audit import main as audit_main
from export_audit import resolve_table_name as audit_resolve
from moto import mock_aws
from seed_claim_pool import TABLE_NAME_PREFIX as SEED_PREFIX
from seed_claim_pool import main as seed_main
from seed_claim_pool import resolve_table_name as seed_resolve

# Region derived only from the environment (AWS_REGION), defaulting to
# us-east-1; conftest.py pins it before import so moto resolves a region.
REGION = "us-east-1"

# A sample workshop id (a valid slug) and the table it should resolve to.
SAMPLE_WORKSHOP_ID = "kiro-2025-10-10"
# A DIFFERENT workshop whose table we stand up and must leave untouched.
OTHER_WORKSHOP_ID = "other-workshop-2025"


# ---------------------------------------------------------------------------
# 1. Table-name resolution: derived name and the --table override
# ---------------------------------------------------------------------------


def test_seed_resolves_credential_claim_table_from_workshop_id() -> None:
    """seed_claim_pool derives ``credential-claim-<workshop_id>`` (Req 7.6)."""
    assert (
        seed_resolve(SAMPLE_WORKSHOP_ID, None)
        == f"credential-claim-{SAMPLE_WORKSHOP_ID}"
    )
    # The prefix constant the derivation uses is the shared contract.
    assert SEED_PREFIX == "credential-claim-"


def test_audit_resolves_credential_claim_table_from_workshop_id() -> None:
    """export_audit derives ``credential-claim-<workshop_id>`` (Req 7.6)."""
    assert (
        audit_resolve(SAMPLE_WORKSHOP_ID, None)
        == f"credential-claim-{SAMPLE_WORKSHOP_ID}"
    )
    assert AUDIT_PREFIX == "credential-claim-"


def test_seed_table_override_wins_over_derived_name() -> None:
    """An explicit --table override beats the workshop-derived name (Req 7.6)."""
    override = "some-other-explicit-table"
    assert seed_resolve(SAMPLE_WORKSHOP_ID, override) == override
    # Surrounding whitespace on the override is trimmed, not fatal.
    assert seed_resolve(SAMPLE_WORKSHOP_ID, "  padded-table  ") == "padded-table"


def test_audit_table_override_wins_over_derived_name() -> None:
    """An explicit --table override beats the workshop-derived name (Req 7.6)."""
    override = "some-other-explicit-table"
    assert audit_resolve(SAMPLE_WORKSHOP_ID, override) == override
    assert audit_resolve(SAMPLE_WORKSHOP_ID, "  padded-table  ") == "padded-table"


def test_resolution_requires_a_workshop_id_or_override() -> None:
    """With neither a workshop id nor an override, resolution fails closed.

    This guards the "never guess a shared table name" rule: both scripts exit
    non-zero rather than fall back to a default name (Requirement 7.6).
    """
    with pytest.raises(SystemExit) as seed_exit:
        seed_resolve(None, None)
    assert seed_exit.value.code not in (0, None)

    with pytest.raises(SystemExit) as audit_exit:
        audit_resolve("   ", None)  # whitespace-only id is treated as unset
    assert audit_exit.value.code not in (0, None)


# ---------------------------------------------------------------------------
# moto helpers for the not-found path
# ---------------------------------------------------------------------------


def _create_claim_table(table_name: str):
    """Create a single-table-model claim table moto-side: PK (S)."""
    client = boto3.client("dynamodb", region_name=REGION)
    client.create_table(
        TableName=table_name,
        AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return boto3.resource("dynamodb", region_name=REGION).Table(table_name)


def _snapshot_items(table_name: str) -> list[dict]:
    """Return every item in a table, sorted by PK, for an untouched comparison."""
    table = boto3.resource("dynamodb", region_name=REGION).Table(table_name)
    items = table.scan().get("Items", [])
    return sorted(items, key=lambda item: item.get("PK", ""))


def _write_otps_and_manifest(tmp_path: pathlib.Path) -> tuple[str, str]:
    """Write a minimal valid otps.csv + manifest.json; return their paths."""
    otp_csv = tmp_path / "otps.csv"
    otp_csv.write_text("username,otp\nalice,otp-aaa\n")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"region": "us-east-1", "sign_in_url": "https://signin.example", '
        '"account_id": "123456789012", "users": {}}'
    )
    return str(otp_csv), str(manifest)


# ---------------------------------------------------------------------------
# 2. Not-found path: missing table -> non-zero exit, names workshop, other
#    workshop's table untouched
# ---------------------------------------------------------------------------


def test_seed_missing_table_exits_nonzero_and_leaves_other_table_untouched(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """seed_claim_pool against a missing table fails closed (Req 7.7).

    Only the OTHER workshop's table exists (and is seeded). Pointing the seed at
    the current workshop's absent table must exit non-zero, name the
    workshop_id, and leave the other workshop's table byte-for-byte intact.
    """
    other_table = f"credential-claim-{OTHER_WORKSHOP_ID}"
    missing_table = f"credential-claim-{SAMPLE_WORKSHOP_ID}"

    with mock_aws():
        # Stand up and seed ONLY the other workshop's table.
        other = _create_claim_table(other_table)
        other.put_item(
            Item={
                "PK": "CRED#other-user",
                "username": "other-user",
                "otp": "keep-me",
                "status": "available",
            }
        )
        before = _snapshot_items(other_table)
        assert before, "precondition: the other workshop's table is seeded"

        # The current workshop's table was never created -> ResourceNotFound.
        otp_csv, manifest = _write_otps_and_manifest(tmp_path)
        argv = [
            "--otp-csv", otp_csv,
            "--manifest", manifest,
            "--workshop-id", SAMPLE_WORKSHOP_ID,
            "--region", REGION,
            "--apply",
        ]

        with pytest.raises(SystemExit) as exc:
            seed_main(argv)

        # Non-zero exit (SystemExit with a string message is a failure code).
        code = exc.value.code
        assert code not in (0, None)
        message = str(code)
        # The message names the workshop id and the derived (missing) table.
        assert SAMPLE_WORKSHOP_ID in message
        assert missing_table in message

        # No other workshop's table was touched: contents are unchanged.
        assert _snapshot_items(other_table) == before


def test_audit_missing_table_exits_nonzero_and_leaves_other_table_untouched(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """export_audit against a missing table fails closed (Req 7.7).

    Only the OTHER workshop's table exists (and is seeded). Pointing the audit
    at the current workshop's absent table must return a non-zero exit code,
    name the workshop_id, and leave the other workshop's table intact.
    """
    other_table = f"credential-claim-{OTHER_WORKSHOP_ID}"
    missing_table = f"credential-claim-{SAMPLE_WORKSHOP_ID}"

    with mock_aws():
        other = _create_claim_table(other_table)
        other.put_item(
            Item={
                "PK": "EMAIL#participant@example.com",
                "username": "other-user",
                "account_id": "123456789012",
                "claimed_at": "2024-01-01T00:00:00Z",
            }
        )
        before = _snapshot_items(other_table)
        assert before, "precondition: the other workshop's table is seeded"

        # The audit entry point returns an exit code (does not raise SystemExit).
        rc = audit_main(["--workshop-id", SAMPLE_WORKSHOP_ID])
        assert rc != 0

        err = capsys.readouterr().err
        # The error names the workshop id and the derived (missing) table.
        assert SAMPLE_WORKSHOP_ID in err
        assert missing_table in err

        # No other workshop's table was touched: contents are unchanged.
        assert _snapshot_items(other_table) == before
