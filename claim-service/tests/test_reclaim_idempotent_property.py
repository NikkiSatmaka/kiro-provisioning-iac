"""Property test for idempotent re-claim through the handler.

Feature: claim-handler-entrypoint, Property 9: Re-claim is idempotent
Validates: Requirements 10.2

Property 9: for any email that successfully claims a credential via a POST
through ``claim_handler.handler``, submitting the *same* email again — any
number of times, possibly with different case/whitespace that normalizes to the
same key — returns HTTP 200 with the *same* credential (the same four-field
body) and never assigns a second credential, never creates a second ``EMAIL#``
lock, and never increases the pool's claimed count on the repeat submissions.

The re-claim path lives entirely in the fixed correctness core: a repeat POST
re-runs the pipeline, ``claim(email)`` loses the ``EMAIL#`` ``Put`` condition
(the lock already exists), and the handler hands back the first credential via
``reclaim`` — a 200, not a 409 and not a second credential (design: "The claim
transaction"; "Idempotent re-scan"; Properties list — Property 9).

Hypothesis drives a first claim and then N re-submissions, varying the case and
surrounding whitespace of the email between submissions so each resubmission
normalizes to the *same* key (``normalize_email`` lowercases + strips). The
test asserts byte-identical four-field 200 bodies across every submission and
that the table holds exactly one ``EMAIL#`` lock and exactly one ``CRED#`` item
flipped to ``claimed`` afterwards.

Isolation note mirrors the sibling moto-backed property tests
(``test_claim_success_contents_property.py``, ``test_pipeline_ordering_property.py``):
each example runs inside its own ``mock_aws()`` context against a fresh moto
table, resets the handler's memoized module state (``TABLE_NAME`` / ``_dynamodb``
/ ``_table``), overrides ``CONFIGURED_WORKSHOP_CODE`` via monkeypatch, and routes
``transact_write_items`` through a standalone low-level client (the moto-5
workaround). ``PER_IP_CAP`` is pinned high and every submission uses a *fresh*
source IP so repeated submissions reach the claim/re-claim path instead of
tripping the per-IP 429.
"""

from __future__ import annotations

import json
import os

import boto3
import claim_handler
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from ._handler_events import make_event

# Region is derived only from the environment (AWS_REGION), defaulting to
# us-east-1; conftest.py pins it before import so moto resolves a region.
REGION = os.environ.get("AWS_REGION", "us-east-1")
TABLE_NAME = "claim-service-reclaim-idempotent-test"

# The configured code the gate compares against; every submission presents it.
CORRECT_CODE = "WS-CODE-2025"

# Kept well above the submission count so the per-IP cap never fires. Each
# submission also uses a fresh source IP, so the counter is a non-factor and the
# idempotency check actually reaches the claim/re-claim path.
PER_IP_CAP = 1000

# The four-field success contract the handler returns on a claim.
CRED_FIELDS = {"username", "otp", "sign_in_url", "region"}

# A base email with a non-empty local part, exactly one "@" and a non-empty
# domain (claim_handler.is_valid_email). The case/whitespace variants below all
# normalize to this same lowercased, stripped key.
BASE_EMAIL = "Participant@Example.com"

# Case/whitespace decorations that all normalize to the same key: leading /
# trailing whitespace is stripped and the address is lowercased, so each variant
# is the SAME email to ``normalize_email``.
email_variant = st.builds(
    lambda lead, trail, upper: (
        lead + (BASE_EMAIL.upper() if upper else BASE_EMAIL) + trail
    ),
    lead=st.sampled_from(["", " ", "\t", "  ", "\n"]),
    trail=st.sampled_from(["", " ", "\t", "  ", "\n"]),
    upper=st.booleans(),
)


def _create_table(dynamodb) -> None:
    """Create the fresh moto-backed single-table schema with TTL on ``ttl``."""
    dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    dynamodb.meta.client.update_time_to_live(
        TableName=TABLE_NAME,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
    )


def _reset_handler_state(monkeypatch, table) -> None:
    """Point the handler at the fresh moto table and clear memoized globals.

    Also pins ``CONFIGURED_WORKSHOP_CODE`` and a high ``PER_IP_CAP`` for this
    example so the gate accepts the submitted code and the per-IP cap stays out
    of the way of the idempotency check.
    """
    monkeypatch.setattr(claim_handler, "TABLE_NAME", TABLE_NAME)
    monkeypatch.setattr(claim_handler, "_dynamodb", None)
    monkeypatch.setattr(claim_handler, "_table", table)
    monkeypatch.setattr(claim_handler, "CONFIGURED_WORKSHOP_CODE", CORRECT_CODE)
    monkeypatch.setattr(claim_handler, "PER_IP_CAP", PER_IP_CAP)


def _seed_pool(table, size: int) -> None:
    """Seed ``size`` available CRED# items with distinct usernames."""
    for index in range(size):
        username = f"seed-user-{index}"
        table.put_item(
            Item={
                "PK": f"CRED#{username}",
                "username": username,
                "otp": f"otp-{index}",
                "sign_in_url": f"https://example.com/signin/{index}",
                "region": REGION,
                "status": "available",
            }
        )


def _post(email: str, source_ip: str) -> dict:
    """Invoke the handler with a POST carrying ``email`` + the correct code."""
    body = json.dumps({"email": email, "workshop_code": CORRECT_CODE})
    event = make_event(method="POST", body=body, source_ip=source_ip)
    return claim_handler.handler(event, None)


def _count_prefix(table, prefix: str) -> int:
    """Count table items whose PK starts with ``prefix`` (scan + paginate)."""
    count = 0
    response = table.scan(ProjectionExpression="PK")
    while True:
        for item in response.get("Items", []):
            if item["PK"].startswith(prefix):
                count += 1
        if "LastEvaluatedKey" not in response:
            return count
        response = table.scan(
            ProjectionExpression="PK",
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )


def _count_claimed(table) -> int:
    """Count CRED# items currently flipped to ``status == "claimed"``."""
    count = 0
    response = table.scan(
        ProjectionExpression="PK, #s",
        ExpressionAttributeNames={"#s": "status"},
    )
    while True:
        for item in response.get("Items", []):
            if item["PK"].startswith("CRED#") and item.get("status") == "claimed":
                count += 1
        if "LastEvaluatedKey" not in response:
            return count
        response = table.scan(
            ProjectionExpression="PK, #s",
            ExpressionAttributeNames={"#s": "status"},
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )


# Spare available credentials kept in the pool on top of the one the first
# claim consumes. This keeps the pool non-empty across every re-submission, so
# the re-claim path is actually exercised.
#
# Scope note (edge documented, not asserted here): the fixed ``claim`` core
# calls ``pick_available()`` *before* it attempts the ``EMAIL#`` lock, so when
# the pool is *fully exhausted* a re-submission raises ``ClaimError(409)`` at
# the pick step and never reaches the idempotent re-claim path. That
# empty-pool interaction is a property of the frozen correctness core
# (owned by the ``credential-claim-service`` spec), not of this wiring
# feature, and is intentionally outside Property 9's scope here — Property 9
# exercises the re-claim path, which requires the pool to still hold an
# available credential. A buffer of spare credentials guarantees that.
POOL_BUFFER = 2


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
)
@given(
    resubmissions=st.lists(email_variant, min_size=1, max_size=4),
)
def test_reclaim_is_idempotent(monkeypatch, resubmissions):
    """Re-submitting the same email returns the same credential, claiming once.

    Feature: claim-handler-entrypoint, Property 9: Re-claim is idempotent
    Validates: Requirements 10.2
    """
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name=REGION)
        _create_table(resource)
        table = resource.Table(TABLE_NAME)
        _reset_handler_state(monkeypatch, table)

        # Seed more available credentials than there are submissions so the pool
        # never fully empties: the first claim consumes one and every spare
        # keeps ``pick_available()`` non-empty, so each re-submission reaches the
        # ``EMAIL#``-lock / ``reclaim`` path rather than short-circuiting to a
        # pool-exhaustion 409 (see the scope note above). A larger pool also
        # makes a (buggy) *second* assignment detectable rather than masked by
        # exhaustion.
        _seed_pool(table, len(resubmissions) + POOL_BUFFER)

        # moto-5 transact_write_items workaround (changes no handler behavior):
        # route the transaction through a standalone low-level client, matching
        # the sibling success/ordering property tests.
        standalone = boto3.client("dynamodb", region_name=REGION)
        table.meta.client.transact_write_items = standalone.transact_write_items

        # First claim — a fresh IP so the per-IP counter starts clean.
        first = _post(BASE_EMAIL, source_ip="203.0.113.1")
        assert first["statusCode"] == 200, (
            f"first claim should succeed, got {first['statusCode']}: {first['body']}"
        )
        assert first["headers"]["Content-Type"] == "application/json"
        first_body = json.loads(first["body"])
        assert set(first_body.keys()) == CRED_FIELDS, (
            f"first body must be exactly the four fields, got {set(first_body.keys())}"
        )

        # Re-submissions — each with a DISTINCT fresh IP and a case/whitespace
        # variant of the same email, so each normalizes to the same key and
        # reaches the re-claim path (never the per-IP 429).
        for index, variant in enumerate(resubmissions):
            repeat = _post(variant, source_ip=f"198.51.100.{index + 1}")
            assert repeat["statusCode"] == 200, (
                f"re-claim #{index} should return 200, got {repeat['statusCode']}: "
                f"{repeat['body']}"
            )
            assert repeat["headers"]["Content-Type"] == "application/json"
            # Byte-identical four-field body: the SAME credential comes back.
            assert repeat["body"] == first["body"], (
                f"re-claim #{index} returned a different body than the first claim: "
                f"{repeat['body']!r} != {first['body']!r}"
            )

        # Exactly one EMAIL# lock exists — no second lock was ever created.
        assert _count_prefix(table, "EMAIL#") == 1, (
            "expected exactly one EMAIL# lock after re-submissions"
        )

        # Exactly one CRED# item is flipped to claimed — the claimed count did
        # not increase on the repeat submissions.
        assert _count_claimed(table) == 1, (
            "expected exactly one CRED# credential flipped to claimed"
        )
