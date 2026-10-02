"""Property test for the per-IP attempt cap.

Feature: credential-claim-service, Property 13
Property 13: The per-IP cap triggers 429
Validates: Requirements 12.2

``check_and_increment_ip(ip, cap)`` performs a single atomic ``UpdateItem``
``ADD`` on the ``RATE#<ip>`` item and raises ``ClaimError(429)`` once the
running count exceeds ``cap``. The property: for any source IP and cap, the
first ``cap`` calls succeed (the count never exceeds the cap) and every call
after that — the one that pushes the count over the cap and all subsequent
ones — raises ``ClaimError`` with status ``429``. A different IP touches a
distinct ``RATE#`` item, so its counter is independent and unaffected by the
first IP being capped.

The handler reads ``TABLE_NAME`` at import and memoizes the DynamoDB resource
and table in module globals (``_dynamodb`` / ``_table``). Each example overrides
``TABLE_NAME`` and resets the memoized globals so it runs against a fresh moto
table with its own ``RATE#`` counter space.
"""

from __future__ import annotations

import boto3
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

import claim_handler
from claim_handler import ClaimError

TABLE_NAME = "claim-service-per-ip-cap-test"

# A caps small enough to keep each example cheap while still exercising the
# boundary (the cap-th call still succeeds, the (cap+1)-th trips 429).
caps = st.integers(min_value=1, max_value=5)

# Extra attempts to make past the cap — each must raise 429.
extra_attempts = st.integers(min_value=1, max_value=5)

# Source IPs are opaque key material to the counter; any non-empty string works.
# Two distinct IPs are drawn to assert counter independence.
ips = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() != "")


def _create_table():
    """Create the fresh moto-backed table the handler expects.

    Partition key ``PK`` (S) with TTL on ``ttl`` (design: the ``RATE#`` item).
    """
    dynamodb = boto3.resource("dynamodb", region_name=claim_handler.REGION)
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


def _reset_handler_state(monkeypatch):
    """Point the handler at the test table and clear its memoized globals.

    ``check_and_increment_ip`` reads the module-level ``TABLE_NAME`` and the
    memoized ``_table`` via ``_get_table()``; resetting both guarantees each
    example gets a fresh ``RATE#`` counter space against the current moto table.
    """
    monkeypatch.setattr(claim_handler, "TABLE_NAME", TABLE_NAME)
    monkeypatch.setattr(claim_handler, "_dynamodb", None)
    monkeypatch.setattr(claim_handler, "_table", None)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(cap=caps, extra=extra_attempts, ip=ips, other_ip=ips)
def test_per_ip_cap_triggers_429(monkeypatch, cap, extra, ip, other_ip):
    """The first ``cap`` calls pass; every call beyond the cap raises 429.

    A second, distinct IP keeps its own independent counter.

    Feature: credential-claim-service, Property 13
    Validates: Requirements 12.2
    """
    with mock_aws():
        _create_table()
        _reset_handler_state(monkeypatch)

        # The first `cap` attempts are within the limit and must not raise.
        for _ in range(cap):
            claim_handler.check_and_increment_ip(ip, cap)

        # Every attempt from here on has pushed the count past the cap: the
        # one that trips the limit and all `extra` after it must raise 429.
        for _ in range(extra):
            try:
                claim_handler.check_and_increment_ip(ip, cap)
            except ClaimError as exc:
                assert exc.status == 429
            else:
                raise AssertionError(
                    "expected ClaimError(429) once the count exceeds the cap"
                )

        # A different IP owns a distinct RATE# item, so its counter is
        # untouched: its first `cap` attempts still succeed.
        if other_ip != ip:
            for _ in range(cap):
                claim_handler.check_and_increment_ip(other_ip, cap)
