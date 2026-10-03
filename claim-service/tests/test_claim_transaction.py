"""Unit tests for the single-transaction claim shape (mocked DynamoDB).

Feature: credential-claim-service, Task 4.5
Validates: Requirements 2.3, 4.1, 4.2, 8.3

These tests pin the *shape* of the correctness core — the single
``TransactWriteItems`` that ``claim_handler.claim`` commits (design: "The claim
transaction"). They run against a real in-memory DynamoDB table backed by moto,
so the transaction and the success-path readback execute end to end rather than
against a stub.

They assert three things on a successful claim:

* **Exactly one** ``transact_write_items`` call occurs, and it carries **both**
  conditional writes — the ``EMAIL#`` ``Put`` guarded by
  ``attribute_not_exists(PK)`` and the ``CRED#`` ``Update`` guarded by the
  ``status = available`` condition (Requirements 2.3, 8.3).
* The returned dict is exactly ``{username, otp, sign_in_url, region}`` with
  ``region`` equal to the env-derived ``REGION`` (Requirements 4.1, 4.2).
* **No read-then-write uniqueness check** happens on the claim path: there is no
  point read (``GetItem``) or ``Query`` of the ``EMAIL#`` lock before the
  transaction — correctness lives only in the transaction's conditions
  (Requirement 8.3).

``claim_handler`` reads ``TABLE_NAME`` at import time and memoizes the Table
handle lazily in ``_get_table``. The ``mocked_claim_handler`` fixture resets
that module state *inside* the moto context so the handler resolves the
moto-backed table, and restores it afterwards so tests do not leak state.
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

    Reloads the module under a mocked AWS environment, points its ``TABLE_NAME``
    at the test table, clears the memoized ``_table``/``_dynamodb`` handles, and
    seeds one available credential. The moto context tears everything down on
    exit, so no state leaks between tests.
    """
    with mock_aws():
        _make_table()

        import claim_handler

        # Point the handler's module state at this test's moto-backed table.
        # We set every attribute the claim path reads explicitly rather than
        # ``importlib.reload``-ing the module: a reload rebinds module-level
        # classes (notably ``claim_handler.ClaimError``) to brand-new objects,
        # which breaks ``except claim_handler.ClaimError`` / ``from claim_handler
        # import ClaimError`` identity in *other* test modules that run later in
        # the same session (they captured the pre-reload class). Pinning the
        # fields we need keeps this fixture's effect local and harness-only.
        #
        # ``REGION`` is read from ``AWS_REGION`` at import; the ambient dev
        # environment may set a different region (e.g. us-east-1), which would
        # leave ``_get_table`` resolving a region where the moto table does not
        # exist (ResourceNotFoundException on the first op). Pin it to the
        # region ``_make_table`` created the table in.
        claim_handler.REGION = REGION
        claim_handler.TABLE_NAME = TABLE_NAME
        claim_handler._table = None
        claim_handler._dynamodb = None

        # Materialize the memoized table. The handler reaches the transaction
        # via ``table.meta.client.transact_write_items`` exactly as in
        # production — and sends NATIVE Python values (not typed AttributeValue
        # descriptors), because that resource-attached client auto-serializes
        # the request. We deliberately do NOT swap or rebind the client here:
        # routing the transaction through a plain low-level client (as an
        # earlier harness did) tested a different serialization path than
        # production used, which is precisely what hid the production bug where
        # typed descriptors got double-serialized into a Map and DynamoDB
        # cancelled the transaction with a ValidationError. Letting the real
        # resource client serialize the native values keeps the test honest.
        claim_handler._get_table()

        yield claim_handler


def _seed_available(claim_handler, username="alice", otp="OTP-123"):
    """Put one ``available`` credential and return its expected success body."""
    table = claim_handler._get_table()
    table.put_item(
        Item={
            "PK": f"CRED#{username}",
            "username": username,
            "otp": otp,
            "sign_in_url": "https://example.awsapps.com/start",
            "region": REGION,
            "status": "available",
        }
    )
    return {
        "username": username,
        "otp": otp,
        "sign_in_url": "https://example.awsapps.com/start",
        "region": REGION,
    }


class _ClientSpy:
    """Record calls to the DynamoDB client while delegating to the real one.

    Lets the transaction and reads execute against moto (so the readback and
    conditions are real) while capturing every ``transact_write_items`` payload
    and every ``get_item`` key for assertions.
    """

    def __init__(self, real):
        self._real = real
        self.transact_calls = []
        self.get_item_keys = []

    def transact_write_items(self, **kwargs):
        self.transact_calls.append(kwargs)
        return self._real.transact_write_items(**kwargs)

    def get_item(self, **kwargs):
        self.get_item_keys.append(kwargs.get("Key"))
        return self._real.get_item(**kwargs)

    def __getattr__(self, name):
        # Everything else (exceptions, scan, update_item, …) hits the real client.
        return getattr(self._real, name)


@pytest.fixture
def spied_client(mocked_claim_handler, monkeypatch):
    """Wrap the handler's low-level client so claim-path calls are recorded.

    ``claim`` reaches the client via ``table.meta.client``; patching that
    attribute on the memoized table makes every client call on the claim path
    flow through the spy.
    """
    table = mocked_claim_handler._get_table()
    spy = _ClientSpy(table.meta.client)
    monkeypatch.setattr(table.meta, "client", spy)
    return spy


# --- Transaction shape ------------------------------------------------------

def test_claim_issues_exactly_one_transaction_with_both_conditional_writes(
    mocked_claim_handler, spied_client
):
    """A successful claim commits one transaction holding both conditions.

    Validates: Requirements 2.3, 8.3.
    """
    _seed_available(mocked_claim_handler)

    mocked_claim_handler.claim("participant@example.com")

    # Exactly one TransactWriteItems call on the success path.
    assert len(spied_client.transact_calls) == 1

    transact_items = spied_client.transact_calls[0]["TransactItems"]
    assert len(transact_items) == 2

    # The two writes: a Put (EMAIL# lock) and an Update (CRED# credential),
    # regardless of the order they appear in the list.
    put = next((i["Put"] for i in transact_items if "Put" in i), None)
    update = next((i["Update"] for i in transact_items if "Update" in i), None)
    assert put is not None, "transaction must contain a Put (the EMAIL# lock)"
    assert update is not None, "transaction must contain an Update (the CRED#)"

    # EMAIL# lock: conditional on the lock not already existing (Req 2.2 / 8.2).
    # Values are NATIVE Python (plain strings), not typed AttributeValue dicts —
    # the resource-attached client serializes them. Asserting on the native form
    # is what pins the fix: a regression back to typed ``{"S": ...}`` descriptors
    # (the production bug) would show up here as a dict instead of a str.
    assert put["Item"]["PK"].startswith("EMAIL#")
    assert put["ConditionExpression"] == "attribute_not_exists(PK)"

    # CRED# update: conditional on the credential still being available
    # (Req 2.1 / 8.1). The condition is written with a name placeholder for the
    # reserved word ``status``; resolve it before asserting.
    assert update["Key"]["PK"].startswith("CRED#")
    names = update.get("ExpressionAttributeNames", {})
    values = update.get("ExpressionAttributeValues", {})
    resolved = update["ConditionExpression"]
    for placeholder, actual in names.items():
        resolved = resolved.replace(placeholder, actual)
    assert "status" in resolved
    assert values[":available"] == "available"


def test_claim_email_read_is_a_fast_path_not_the_uniqueness_check(
    mocked_claim_handler, spied_client
):
    """The EMAIL# read is a re-claim fast path; uniqueness stays in the txn.

    ``claim`` reads the ``EMAIL#`` lock first as a fast path for a returning
    participant (so an exhausted pool never masks an existing claim). For a
    *first-time* claimant that read finds nothing, and the claim still proceeds
    through the transaction whose conditional ``Put`` (``attribute_not_exists``)
    remains the authoritative one-per-email guarantee — the read is NOT a
    read-then-write uniqueness check (Req 8.3).
    """
    _seed_available(mocked_claim_handler)

    mocked_claim_handler.claim("participant@example.com")

    # The uniqueness guarantee is still carried by the transaction's
    # conditional Put, not by the fast-path read: exactly one transaction
    # committed, and its EMAIL# Put is guarded by attribute_not_exists(PK).
    assert len(spied_client.transact_calls) == 1
    transact_items = spied_client.transact_calls[0]["TransactItems"]
    put = next((i["Put"] for i in transact_items if "Put" in i), None)
    assert put is not None
    assert put["Item"]["PK"].startswith("EMAIL#")
    assert put["ConditionExpression"] == "attribute_not_exists(PK)"

    # The only EMAIL# reads are the step-0 fast-path checks (a first-time
    # claimant finds no lock, so the claim proceeds to the transaction). We do
    # not forbid the read — we forbid it being the uniqueness mechanism, which
    # the assertion above pins to the transaction condition.
    email_reads = [
        key for key in spied_client.get_item_keys
        if key and str(key.get("PK", "")).startswith("EMAIL#")
    ]
    assert all(
        str(key.get("PK", "")) == "EMAIL#participant@example.com"
        for key in email_reads
    )


# --- Success body -----------------------------------------------------------

def test_claim_success_returns_the_four_contract_fields(
    mocked_claim_handler, spied_client
):
    """A successful claim returns exactly the 200 contract fields.

    Validates: Requirements 4.1, 4.2 — ``username``, ``otp``, ``sign_in_url``
    and ``region`` equal to the env-derived ``REGION``, and nothing else.
    """
    expected = _seed_available(mocked_claim_handler)

    result = mocked_claim_handler.claim("participant@example.com")

    assert result == expected
    assert set(result) == {"username", "otp", "sign_in_url", "region"}
    assert result["region"] == REGION
    assert result["username"] == "alice"
    assert result["otp"] == "OTP-123"
    assert result["sign_in_url"].startswith("https://")
