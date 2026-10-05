"""Integration test: a claim copies the credential's account_id onto the lock.

Feature: idc-region-account-mapping, Task 7.3
Validates: Requirements 7.2, 8.2, 8.3

This test exercises the whole claim transaction end to end against a real
in-memory DynamoDB table (moto), rather than asserting on the transaction
*shape* like ``test_claim_transaction.py`` does. It seeds one ``available``
``CRED#`` item carrying an ``account_id``, runs ``claim_handler.claim``, then
pins the two facts task 7.1 promised:

1. The resulting ``EMAIL#<email>`` lock item carries that *same* ``account_id``
   — the operator audit can read it off the lock without re-reading the
   credential (Requirements 7.2, 8.2).
2. The participant success response is still exactly the four contract fields
   ``{username, otp, sign_in_url, region}`` — the operator-only ``account_id``
   never leaks to the participant (Requirement 8.3).

The moto fixture mirrors ``test_claim_transaction.py``: it resets
``claim_handler``'s memoized table state *inside* the moto context so the
handler resolves the moto-backed table, and the context tears everything down
on exit so no state leaks between tests.
"""

from __future__ import annotations

import os

import boto3
import pytest
from moto import mock_aws

TABLE_NAME = "claim-service-test"
# Region is derived only from the environment (AWS_REGION), defaulting to
# us-east-1; conftest.py pins it before import so moto resolves a region.
REGION = os.environ.get("AWS_REGION", "us-east-1")

ACCOUNT_ID = "123456789012"


def _make_table():
    """Create the single-table model moto-side: partition key ``PK`` (S)."""
    client = boto3.client("dynamodb", region_name=REGION)
    client.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=TABLE_NAME)


@pytest.fixture
def mocked_claim_handler():
    """Yield ``claim_handler`` wired to a fresh moto-backed table.

    Points its ``TABLE_NAME`` at the test table, pins ``REGION`` to where the
    moto table was created, and clears the memoized ``_table``/``_dynamodb``
    handles so ``_get_table`` resolves the moto-backed table. We pin the fields
    the claim path reads rather than ``importlib.reload``-ing the module, to
    avoid rebinding ``claim_handler.ClaimError`` and breaking ``except``
    identity in other test modules (same rationale as test_claim_transaction).
    """
    with mock_aws():
        _make_table()

        import claim_handler

        claim_handler.REGION = REGION
        claim_handler.TABLE_NAME = TABLE_NAME
        claim_handler._table = None
        claim_handler._dynamodb = None

        # Materialize the memoized table so the transaction runs through the
        # resource-attached client exactly as in production.
        claim_handler._get_table()

        yield claim_handler


def _seed_available(claim_handler, username="alice", otp="OTP-123", account_id=ACCOUNT_ID):
    """Put one ``available`` credential stamped with ``account_id``.

    Returns the expected four-field participant success body (no ``account_id``).
    """
    table = claim_handler._get_table()
    table.put_item(
        Item={
            "PK": f"CRED#{username}",
            "username": username,
            "otp": otp,
            "sign_in_url": "https://example.awsapps.com/start",
            "region": REGION,
            "status": "available",
            "account_id": account_id,
        }
    )
    return {
        "username": username,
        "otp": otp,
        "sign_in_url": "https://example.awsapps.com/start",
        "region": REGION,
    }


def test_claim_copies_account_id_onto_lock_and_hides_it_from_response(
    mocked_claim_handler,
):
    """A claim stamps the credential's account_id on the lock, not the response.

    Validates: Requirements 7.2, 8.2, 8.3.
    """
    email = "participant@example.com"
    expected_response = _seed_available(mocked_claim_handler)

    result = mocked_claim_handler.claim(email)

    # (2) Participant response is still exactly the four contract fields; the
    # operator-only account_id never leaks (Requirement 8.3).
    assert result == expected_response
    assert set(result) == {"username", "otp", "sign_in_url", "region"}
    assert "account_id" not in result

    # (1) The EMAIL# lock carries the picked CRED# item's account_id so the
    # audit can read it directly off the lock (Requirements 7.2, 8.2).
    table = mocked_claim_handler._get_table()
    lock = table.get_item(Key={"PK": f"EMAIL#{email}"}).get("Item")
    assert lock is not None, "the claim must create an EMAIL# lock"
    assert lock["account_id"] == ACCOUNT_ID
    assert lock["username"] == "alice"
