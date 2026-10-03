"""Property test for successful-claim contents.

Feature: credential-claim-service, Property 7
Property 7: Successful claims return the assigned credential's fields
Validates: Requirements 4.1, 4.2

For any randomly seeded pool of ``CRED#`` items — each carrying a username,
otp, sign_in_url, ``region`` equal to the env-derived ``REGION`` and
``status == "available"``
— a successful ``claim(email)`` returns the HTTP-200-equivalent credential dict
whose ``username``/``otp``/``sign_in_url`` match the *assigned* credential's
seeded values and whose ``region`` is the env-derived ``REGION`` (Requirements 4.1,
4.2). The handler itself selects *which* credential to hand out (pick_available
+ the claim transaction), so the test does not assume a particular pick; it
looks the assigned username back up in the seeded pool and asserts the returned
fields are exactly that credential's seeded fields.

Isolation note: ``claim_handler`` reads ``TABLE_NAME`` at import and memoizes a
module-level ``_dynamodb``/``_table`` pair in ``_get_table()``. Each generated
example seeds a *fresh* moto-backed table, so we must reset that module state
(``TABLE_NAME``, ``_dynamodb``, ``_table``) and point ``_table`` at the new
moto table every example, otherwise a stale handle from a prior example would
leak across inputs. We drive moto with an explicit ``mock_aws()`` context per
example (rather than a function-scoped fixture) so each drawn pool runs against
its own isolated AWS mock — avoiding the Hypothesis function-scoped-fixture
health check entirely.
"""

from __future__ import annotations

import os

import boto3
import claim_handler
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

# Region is derived only from the environment (AWS_REGION), defaulting to
# us-east-1; conftest.py pins it before import so moto resolves a region.
REGION = os.environ.get("AWS_REGION", "us-east-1")
TABLE_NAME = "claim-service-prop7"

# A field value guaranteed non-empty after stripping surrounding whitespace —
# usernames/otps/urls are opaque strings to the claim path, so any such text
# models the seeded input space. Blacklisting surrogate code points keeps the
# values round-trippable through DynamoDB/boto3.
nonempty_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=40,
).filter(lambda s: s.strip() != "")


def _credential(draw_id: int, username: str, otp: str, sign_in_url: str) -> dict:
    """Build one seeded CRED# item (status available, fixed region)."""
    return {
        "PK": f"CRED#{username}",
        "username": username,
        "otp": otp,
        "sign_in_url": sign_in_url,
        "region": REGION,
        "status": "available",
    }


# A pool of credentials with DISTINCT usernames (the PK is CRED#<username>, so
# duplicate usernames would collide to one item). We draw a list of unique
# usernames, then attach otp/sign_in_url to each.
pool_strategy = st.lists(nonempty_text, min_size=1, max_size=20, unique=True).flatmap(
    lambda usernames: st.fixed_dictionaries(
        {
            username: st.tuples(nonempty_text, nonempty_text)
            for username in usernames
        }
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


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(pool=pool_strategy, email=nonempty_text)
def test_successful_claim_returns_assigned_credentials_fields(pool, email):
    """A successful claim returns the assigned credential's seeded fields.

    Feature: credential-claim-service, Property 7
    Validates: Requirements 4.1, 4.2
    """
    # Reset the handler's import-time / memoized module state so this example's
    # fresh moto table is the one the claim path talks to (see module docstring).
    claim_handler.TABLE_NAME = TABLE_NAME
    claim_handler._dynamodb = None
    claim_handler._table = None

    with mock_aws():
        resource = boto3.resource("dynamodb", region_name=REGION)
        _create_table(resource)

        # Seed the drawn pool: one available CRED# item per unique username.
        table = resource.Table(TABLE_NAME)
        seeded: dict[str, dict] = {}
        for index, (username, (otp, sign_in_url)) in enumerate(pool.items()):
            item = _credential(index, username, otp, sign_in_url)
            table.put_item(Item=item)
            seeded[username] = item

        # Point the handler's memoized table at this example's moto table.
        claim_handler._dynamodb = resource
        claim_handler._table = table

        # Mock-harness workaround (changes no handler behavior): route only
        # ``transact_write_items`` through a standalone low-level client. Under
        # moto 5 the resource's auto-attached client mis-serializes
        # ``TransactWriteItems`` fed raw AttributeValue dicts (spurious
        # "unhashable type: 'dict'" cancellation), while a plain
        # ``boto3.client`` runs the identical call correctly. The resource
        # client is left intact for the handler's resource-level scan/get, and
        # moto shares one ``TransactionCanceledException`` class across clients
        # so cancellation handling is unaffected.
        standalone = boto3.client("dynamodb", region_name=REGION)
        table.meta.client.transact_write_items = standalone.transact_write_items

        normalized = claim_handler.normalize_email(email)
        result = claim_handler.claim(normalized)

    # The claim must have returned exactly the four 200-contract fields.
    assert set(result.keys()) == {"username", "otp", "sign_in_url", "region"}

    # The assigned username must be one of the seeded credentials, and the
    # returned fields must match THAT credential's seeded values (Req 4.1).
    assigned = result["username"]
    assert assigned in seeded, "claim returned a username that was never seeded"
    source = seeded[assigned]
    assert result["username"] == source["username"]
    assert result["otp"] == source["otp"]
    assert result["sign_in_url"] == source["sign_in_url"]

    # Region is the fixed service region regardless of which credential won
    # (Requirement 4.2).
    assert result["region"] == REGION
