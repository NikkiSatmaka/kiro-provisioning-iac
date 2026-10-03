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
  ``region == "ap-southeast-1"`` (Requirements 4.1, 4.2).
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

import boto3
import pytest
from moto import mock_aws

TABLE_NAME = "claim-service-test"
REGION = "ap-southeast-1"


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

        # Materialize the memoized table, then route ONLY
        # ``transact_write_items`` through a fresh standalone low-level client.
        # The handler reaches the transaction via
        # ``table.meta.client.transact_write_items`` exactly as in production.
        #
        # Mock-harness workaround (changes no handler behavior): under moto 5
        # the resource's *auto-attached* client mis-serializes
        # ``TransactWriteItems`` fed raw AttributeValue dicts — it cancels with
        # a spurious "unhashable type: 'dict'" — while a plain ``boto3.client``
        # executes the identical call correctly. We cannot swap the *whole*
        # resource client (the resource-level seed/scan/get ops need the
        # resource's marshalling client, which rejects their high-level items
        # with ParamValidationError), so we rebind only the one bound method
        # that the handler issues at the client level. moto shares a single
        # ``TransactionCanceledException`` class across clients, so the
        # handler's ``client.exceptions.TransactionCanceledException`` lookup
        # still resolves and cancellation handling is unaffected.
        table = claim_handler._get_table()
        standalone = boto3.client("dynamodb", region_name=REGION)
        table.meta.client.transact_write_items = standalone.transact_write_items

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
    assert put["Item"]["PK"]["S"].startswith("EMAIL#")
    assert put["ConditionExpression"] == "attribute_not_exists(PK)"

    # CRED# update: conditional on the credential still being available
    # (Req 2.1 / 8.1). The condition is written with a name placeholder for the
    # reserved word ``status``; resolve it before asserting.
    assert update["Key"]["PK"]["S"].startswith("CRED#")
    names = update.get("ExpressionAttributeNames", {})
    values = update.get("ExpressionAttributeValues", {})
    resolved = update["ConditionExpression"]
    for placeholder, actual in names.items():
        resolved = resolved.replace(placeholder, actual)
    assert "status" in resolved
    assert values[":available"] == {"S": "available"}


def test_claim_does_not_read_the_email_lock_before_writing(
    mocked_claim_handler, spied_client
):
    """No read-then-write uniqueness check on the claim path (Req 8.3).

    Correctness is in the transaction conditions alone, so a successful claim
    must not point-read the ``EMAIL#`` lock before committing — the only
    ``GetItem`` allowed is the post-commit readback of the ``CRED#`` item.
    """
    _seed_available(mocked_claim_handler)

    mocked_claim_handler.claim("participant@example.com")

    # No EMAIL# lock was point-read at any time on the success path.
    email_reads = [
        key for key in spied_client.get_item_keys
        if key and str(key.get("PK", "")).startswith("EMAIL#")
    ]
    assert email_reads == [], (
        "claim must not read the EMAIL# lock before writing; the uniqueness "
        "check belongs to the transaction condition, not a read-then-write"
    )

    # Any GetItem that did happen is the post-commit CRED# readback.
    for key in spied_client.get_item_keys:
        assert str(key.get("PK", "")).startswith("CRED#")


# --- Success body -----------------------------------------------------------

def test_claim_success_returns_the_four_contract_fields(
    mocked_claim_handler, spied_client
):
    """A successful claim returns exactly the 200 contract fields.

    Validates: Requirements 4.1, 4.2 — ``username``, ``otp``, ``sign_in_url``
    and ``region == "ap-southeast-1"``, and nothing else.
    """
    expected = _seed_available(mocked_claim_handler)

    result = mocked_claim_handler.claim("participant@example.com")

    assert result == expected
    assert set(result) == {"username", "otp", "sign_in_url", "region"}
    assert result["region"] == "ap-southeast-1"
    assert result["username"] == "alice"
    assert result["otp"] == "OTP-123"
    assert result["sign_in_url"].startswith("https://")
