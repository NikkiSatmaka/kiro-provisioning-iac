"""Property test for first-failing-step ordering in the claim pipeline.

Feature: claim-handler-entrypoint, Property 5: The pipeline fails at the first
failing step, in fixed order
Validates: Requirements 6.1, 6.2

``run_claim_pipeline(event)`` composes the POST steps in one fixed order
(design: "run_claim_pipeline"; Requirement 6.1):

    1. per-IP cap check      -> ClaimError(429)
    2. body parse            -> ClaimError(400)
    3. email format          -> ClaimError(400)
    4. workshop-code gate     -> ClaimError(403)
    5. normalize + claim     -> 200 / ClaimError(409)

The property: when several of these steps would *simultaneously* fail, the
pipeline reports the status of the EARLIEST failing step and no later step runs
(Requirement 6.2 — an over-cap IP never parses the body, verifies the code, or
claims). Concretely:

    - an over-cap IP yields 429 even if the body is malformed and the code is
      wrong;
    - a malformed body yields 400 even if the code is wrong (the gate is never
      consulted);
    - an invalid email yields 400 before the gate is consulted;
    - a wrong workshop code yields 403.

For each example Hypothesis independently decides whether each earlier stage
would fail, computes the expected first-failing status, builds a matching
Function URL event, and asserts the raised ``ClaimError.status``.

Isolation note: the handler reads ``TABLE_NAME`` at import and memoizes the
DynamoDB resource/table in module globals (``_dynamodb`` / ``_table``). Each
example runs inside its own ``mock_aws()`` context against a fresh moto table
and resets that module state, mirroring the sibling property tests
(``test_per_ip_cap_property.py``, ``test_claim_success_contents_property.py``).
``CONFIGURED_WORKSHOP_CODE`` and ``PER_IP_CAP`` are overridden via monkeypatch;
the per-IP 429 is forced by priming the moto ``RATE#`` counter over a low cap.
"""

from __future__ import annotations

import json
import os

import boto3
import claim_handler
from claim_handler import ClaimError
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from moto import mock_aws

from ._handler_events import make_event

# Region is derived only from the environment (AWS_REGION), defaulting to
# us-east-1; conftest.py pins it before import so moto resolves a region.
REGION = os.environ.get("AWS_REGION", "us-east-1")
TABLE_NAME = "claim-service-pipeline-ordering-test"

# The configured code the gate compares against. A matching submission is
# "correct"; anything else trips the 403 gate. The sentinel is opaque — the
# gate only does a constant-time byte compare.
CORRECT_CODE = "WS-CODE-2025"
PER_IP_CAP = 3

# A valid email: non-empty local part, exactly one "@", non-empty domain
# (claim_handler.is_valid_email). Kept as a constant so the "email format"
# stage only fails when we deliberately choose a malformed address below.
VALID_EMAIL = "participant@example.com"
# A malformed email that fails is_valid_email (no "@").
INVALID_EMAIL = "not-an-email"

# A well-formed JSON object body carrying both required fields and a valid
# email + correct code — the input that passes every earlier stage so the
# pipeline reaches the claim step.
GOOD_BODY = json.dumps({"email": VALID_EMAIL, "workshop_code": CORRECT_CODE})


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

    Also pins ``CONFIGURED_WORKSHOP_CODE`` and ``PER_IP_CAP`` for this example.
    """
    monkeypatch.setattr(claim_handler, "TABLE_NAME", TABLE_NAME)
    monkeypatch.setattr(claim_handler, "_dynamodb", None)
    monkeypatch.setattr(claim_handler, "_table", table)
    monkeypatch.setattr(claim_handler, "CONFIGURED_WORKSHOP_CODE", CORRECT_CODE)
    monkeypatch.setattr(claim_handler, "PER_IP_CAP", PER_IP_CAP)


def _body_for(fail_body: bool, fail_email: bool, fail_code: bool) -> str:
    """Build the POST body for the chosen earlier-stage failures.

    - ``fail_body``: emit a non-JSON string so ``parse_post`` raises 400 at the
      body-parse stage (this makes the email/code choices moot, which is the
      point of the ordering property).
    - ``fail_email``: use a malformed address so ``is_valid_email`` fails.
    - ``fail_code``: use a wrong workshop code so the gate raises 403.
    """
    if fail_body:
        return "this-is-not-json"
    email = INVALID_EMAIL if fail_email else VALID_EMAIL
    code = "WRONG-CODE" if fail_code else CORRECT_CODE
    return json.dumps({"email": email, "workshop_code": code})


def _expected_status(
    fail_cap: bool, fail_body: bool, fail_email: bool, fail_code: bool
) -> int | None:
    """The status of the earliest failing stage, or ``None`` if all pass.

    Mirrors the fixed pipeline order: cap (429) -> parse (400) -> email (400)
    -> gate (403). ``None`` means every earlier stage passes and the pipeline
    reaches the claim step (handled separately against a seeded pool).
    """
    if fail_cap:
        return 429
    if fail_body:
        return 400
    if fail_email:
        return 400
    if fail_code:
        return 403
    return None


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
)
@given(
    fail_cap=st.booleans(),
    fail_body=st.booleans(),
    fail_email=st.booleans(),
    fail_code=st.booleans(),
)
def test_pipeline_reports_first_failing_step(
    monkeypatch, fail_cap, fail_body, fail_email, fail_code
):
    """The pipeline raises the earliest failing step's status, in fixed order.

    Feature: claim-handler-entrypoint, Property 5: The pipeline fails at the
    first failing step, in fixed order
    Validates: Requirements 6.1, 6.2
    """
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name=REGION)
        _create_table(resource)
        table = resource.Table(TABLE_NAME)
        _reset_handler_state(monkeypatch, table)

        ip = "198.51.100.7"

        # Force the per-IP 429 by priming the RATE# counter past the cap, so the
        # pipeline's own check_and_increment_ip trips immediately. When we do
        # NOT want the cap to fire, leave the counter at zero.
        if fail_cap:
            table.update_item(
                Key={"PK": f"RATE#{ip}"},
                UpdateExpression="SET #count = :over, #ttl = :ttl",
                ExpressionAttributeNames={"#count": "count", "#ttl": "ttl"},
                ExpressionAttributeValues={
                    ":over": PER_IP_CAP + 5,
                    ":ttl": 9999999999,
                },
            )

        # Seed one available credential so the "all pass" case can reach a
        # successful claim rather than a spurious 409 from an empty pool.
        table.put_item(
            Item={
                "PK": "CRED#seed-user",
                "username": "seed-user",
                "otp": "otp-xyz",
                "sign_in_url": "https://example.com/signin",
                "region": REGION,
                "status": "available",
            }
        )

        # moto-5 transact_write_items workaround (changes no handler behavior):
        # route the transaction through a standalone low-level client, matching
        # the sibling success property test. Only exercised when every earlier
        # stage passes and the pipeline reaches claim().
        standalone = boto3.client("dynamodb", region_name=REGION)
        table.meta.client.transact_write_items = standalone.transact_write_items

        body = _body_for(fail_body, fail_email, fail_code)
        event = make_event(method="POST", body=body, source_ip=ip)

        expected = _expected_status(fail_cap, fail_body, fail_email, fail_code)

        if expected is None:
            # Every earlier stage passes: the pipeline reaches the claim step
            # and, with a seeded available credential, returns the four-field
            # success body — no ClaimError is raised.
            result = claim_handler.run_claim_pipeline(event)
            assert set(result.keys()) == {
                "username",
                "otp",
                "sign_in_url",
                "region",
            }
        else:
            try:
                claim_handler.run_claim_pipeline(event)
            except ClaimError as exc:
                assert exc.status == expected, (
                    f"expected first-failing status {expected} for "
                    f"cap={fail_cap} body={fail_body} email={fail_email} "
                    f"code={fail_code}, got {exc.status}"
                )
            else:
                raise AssertionError(
                    f"expected ClaimError({expected}) for cap={fail_cap} "
                    f"body={fail_body} email={fail_email} code={fail_code}"
                )
