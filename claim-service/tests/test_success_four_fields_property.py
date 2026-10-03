"""Property test for the four-field success contract through the handler.

Feature: claim-handler-entrypoint, Property 8: A successful claim returns
exactly the four credential fields
Validates: Requirements 8.1, 8.3

Property 8: For ANY successful claim driven end-to-end through
``claim_handler.handler`` as a ``POST`` (valid email + correct workshop code
against a seeded pool of available ``CRED#`` items), the HTTP 200 JSON body is
an object whose key set is EXACTLY ``{username, otp, sign_in_url, region}`` — no
more, no fewer — and whose values equal the *assigned* credential's seeded
values. No other credential attribute (``status``, ``claimed_by_email``,
``claimed_at``, ``PK``) leaks into the body (R8.1, R8.3).

This is the whole-handler counterpart to the core-path
``test_claim_success_contents_property.py`` (which exercises ``claim`` directly):
here the assertion runs against the serialized Function URL response — we parse
``response["body"]`` back from JSON and assert on *that* object, so we are
testing exactly what a participant's browser would receive.

Harness notes
-------------
The handler reads ``TABLE_NAME`` at import and memoizes a module-level
``_dynamodb``/``_table`` pair in ``_get_table()``; it also reads
``CONFIGURED_WORKSHOP_CODE`` and ``PER_IP_CAP`` as module globals. Each
generated example seeds a *fresh* moto-backed table, so we reset that module
state (``TABLE_NAME``, ``_dynamodb``, ``_table``) and point ``_table`` at the
new table every example, mirroring the sibling moto-backed property tests
(``test_claim_success_contents_property.py``, ``test_pipeline_ordering_property.py``).

* ``CONFIGURED_WORKSHOP_CODE`` is pinned via monkeypatch and submitted verbatim
  so the workshop-code gate passes and the pipeline reaches ``claim``.
* ``PER_IP_CAP`` is pinned high and every example uses a *fresh* source IP so
  the per-IP cap never trips before the claim succeeds.
* The seeded ``CRED#`` ``region`` is the env-derived ``REGION`` — the region
  ``conftest.py`` pins ``AWS_REGION`` to (default us-east-1) — so the returned
  ``region`` matches the seeded value under the test environment.
* The moto-5 ``transact_write_items`` standalone-client workaround (identical to
  the sibling tests) routes only that one call through a plain low-level client;
  it changes no handler behavior.

To prove non-leakage positively, every seeded credential also carries the
internal attributes a claimed credential would gain (``claimed_by_email``,
``claimed_at``) plus ``status`` and ``PK``; the body must contain none of them.
"""

from __future__ import annotations

import itertools
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
TABLE_NAME = "claim-service-success-four-fields-test"

# The configured code the gate compares against; submitted verbatim so the
# workshop-code gate passes and the pipeline reaches the claim step.
CORRECT_CODE = "WS-CODE-2025"

# The four fields the 200 contract promises — nothing more may appear.
EXPECTED_KEYS = {"username", "otp", "sign_in_url", "region"}

# A fresh source IP per example so the per-IP cap never trips before the claim
# succeeds (the pipeline increments the RATE# counter before claiming).
_ip_counter = itertools.count(1)

# A field value guaranteed non-empty after stripping surrounding whitespace.
# username/otp/sign_in_url are opaque strings to the claim path, so any such
# text models the seeded input space; blacklisting surrogate code points keeps
# the values round-trippable through DynamoDB/boto3 and JSON.
nonempty_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip() != "")

# A valid email per claim_handler.is_valid_email: non-empty local part, exactly
# one "@", non-empty domain. Any such address reaches the claim step.
valid_emails = st.builds(
    lambda local, domain: f"{local}@{domain}",
    st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=12),
    st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=12),
)

# A pool of credentials with DISTINCT usernames (PK is CRED#<username>, so
# duplicate usernames would collide to one item). Draw a list of unique
# usernames, then attach an (otp, sign_in_url) pair to each.
pool_strategy = st.lists(nonempty_text, min_size=1, max_size=12, unique=True).flatmap(
    lambda usernames: st.fixed_dictionaries(
        {username: st.tuples(nonempty_text, nonempty_text) for username in usernames}
    )
)


def _create_table(dynamodb) -> None:
    """Create the single-table schema (PK string hash key, on-demand)."""
    dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )


def _reset_handler_state(monkeypatch, table) -> None:
    """Point the handler at the fresh moto table and clear memoized globals.

    Also pins ``CONFIGURED_WORKSHOP_CODE`` and a high ``PER_IP_CAP`` so the
    workshop-code gate passes and the per-IP cap never trips mid-example.
    """
    monkeypatch.setattr(claim_handler, "TABLE_NAME", TABLE_NAME)
    monkeypatch.setattr(claim_handler, "_dynamodb", None)
    monkeypatch.setattr(claim_handler, "_table", table)
    monkeypatch.setattr(claim_handler, "CONFIGURED_WORKSHOP_CODE", CORRECT_CODE)
    monkeypatch.setattr(claim_handler, "PER_IP_CAP", 10_000)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
)
@given(pool=pool_strategy, email=valid_emails)
def test_success_returns_exactly_four_fields(monkeypatch, pool, email):
    """A 200 POST body carries exactly the four assigned-credential fields.

    Feature: claim-handler-entrypoint, Property 8: A successful claim returns
    exactly the four credential fields
    Validates: Requirements 8.1, 8.3
    """
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name=REGION)
        _create_table(resource)
        table = resource.Table(TABLE_NAME)
        _reset_handler_state(monkeypatch, table)

        # Seed the drawn pool: one available CRED# item per unique username.
        # Each item also carries the internal attributes a claimed credential
        # would gain (claimed_by_email, claimed_at) plus status + PK, so the
        # 200 body must demonstrably omit all of them (R8.3 — no leak).
        seeded: dict[str, dict] = {}
        for username, (otp, sign_in_url) in pool.items():
            item = {
                "PK": f"CRED#{username}",
                "username": username,
                "otp": otp,
                "sign_in_url": sign_in_url,
                "region": REGION,
                "status": "available",
                "claimed_by_email": "SHOULD-NOT-LEAK@example.com",
                "claimed_at": "2024-01-01T00:00:00+00:00",
            }
            table.put_item(Item=item)
            seeded[username] = item

        # moto-5 transact_write_items workaround (changes no handler behavior):
        # route the transaction through a standalone low-level client, matching
        # the sibling success property test.
        standalone = boto3.client("dynamodb", region_name=REGION)
        table.meta.client.transact_write_items = standalone.transact_write_items

        # Drive the whole handler as a browser would: a POST with a valid email
        # and the correct workshop code, from a fresh source IP.
        body = json.dumps({"email": email, "workshop_code": CORRECT_CODE})
        source_ip = f"203.0.113.{next(_ip_counter)}"
        event = make_event(method="POST", body=body, source_ip=source_ip)

        response = claim_handler.handler(event, None)

    # The handler returns a serialized Function URL success response.
    assert response["statusCode"] == 200, response
    assert response["headers"]["Content-Type"] == "application/json"

    parsed = json.loads(response["body"])
    assert isinstance(parsed, dict)

    # EXACTLY the four fields — no more, no fewer (R8.1). This also proves PK,
    # status, claimed_by_email and claimed_at did not leak (R8.3).
    assert set(parsed.keys()) == EXPECTED_KEYS, parsed

    # The assigned username must be one of the seeded credentials, and the
    # returned values must equal THAT credential's seeded values (R8.1).
    assigned = parsed["username"]
    assert assigned in seeded, "handler returned a username that was never seeded"
    source = seeded[assigned]
    assert parsed["username"] == source["username"]
    assert parsed["otp"] == source["otp"]
    assert parsed["sign_in_url"] == source["sign_in_url"]
    assert parsed["region"] == source["region"] == REGION
