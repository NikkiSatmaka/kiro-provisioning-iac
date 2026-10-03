"""Property test for the workshop-code gate's no-write / accept behavior.

Feature: claim-handler-entrypoint, Property 6: A wrong or empty workshop code
never writes
Validates: Requirements 5.1, 5.3

Property 6 has two halves (design: "Correctness Properties > Property 6"):

* **Reject + no write.** For any valid email and any submitted workshop code
  that is empty after trimming or not byte-for-byte equal to
  ``CONFIGURED_WORKSHOP_CODE``, a POST returns ``statusCode`` 403 with an
  ``Error_Envelope`` and the DynamoDB table is left byte-for-byte unchanged — no
  ``EMAIL#`` lock is created, no ``CRED#`` item flips to ``claimed``, and
  ``claim`` is never invoked. We assert this with a scan-before / scan-after
  snapshot (design: "no write" assertions) *and* a spy on
  ``claim_handler.claim`` that must record zero calls.
* **Accept padded-correct.** For any amount of surrounding whitespace around the
  otherwise-correct code, the gate trims and the pipeline proceeds to the claim
  step. We assert "reaches claim" via the same spy — it must be called exactly
  once with the normalized email — without depending on the claim's result.

Workshop codes are drawn from printable ASCII. The gate compares with
``hmac.compare_digest``, whose string form only accepts ASCII operands (it
raises ``TypeError`` on non-ASCII text); an env-injected workshop token is ASCII
in practice, so ASCII is the realistic input space and keeps the property on the
gate's accept/reject logic rather than a compare-digest stdlib limitation.

The POST path needs a table, so each example reuses the moto fixture + memoized
state reset + ``transact_write_items`` standalone-client workaround that the
sibling property tests document (``test_claim_success_contents_property.py`` /
``test_per_ip_cap_property.py``). ``CONFIGURED_WORKSHOP_CODE`` is set per example
via monkeypatch, and one available ``CRED#`` is seeded so the accept case can
reach claim.
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
TABLE_NAME = "claim-service-prop6"

# Workshop codes are drawn from printable ASCII. The gate compares with
# ``hmac.compare_digest``, whose string form only accepts ASCII operands (it
# raises ``TypeError`` on non-ASCII text — a known stdlib constraint). A
# workshop code injected by OpenTofu as an env var is an ASCII token, so ASCII
# is the realistic input space here; drawing non-ASCII would exercise a
# compare-digest limitation outside this property's scope rather than the gate's
# accept/reject logic. ``!``..``~`` is printable ASCII minus the space, so a
# single-char draw is already non-whitespace.
_ascii_token = st.text(
    alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
    min_size=1,
    max_size=24,
)

# The correct code the gate is configured with: a non-empty ASCII token with no
# surrounding whitespace (the ``!``..``~`` alphabet already excludes spaces).
correct_codes = _ascii_token

# A non-whitespace ASCII suffix appended to the correct code so the submitted
# code is a genuine mismatch *after trimming* (not merely padded-correct).
wrong_suffixes = st.text(
    alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
    min_size=1,
    max_size=4,
)

# A valid email the format check (one ``@``, non-empty local + domain) accepts.
emails = st.builds(
    lambda local, domain: f"{local}@{domain}",
    st.text(alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")), min_size=1, max_size=12),
    st.text(alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")), min_size=1, max_size=12),
)

# Surrounding whitespace to pad the correct code with (may be empty on a side,
# but the test only asserts the *trim-to-correct* behavior, so padding that
# strips back to the correct code is what matters).
whitespace = st.text(alphabet=" \t\n\r\f\v", min_size=0, max_size=4)


def _make_table(resource) -> None:
    """Create the single-table schema: ``PK`` (S) hash key, on-demand, TTL."""
    resource.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    resource.meta.client.update_time_to_live(
        TableName=TABLE_NAME,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
    )


def _seed_available(table, username="alice") -> None:
    """Seed one available credential so the accept case can reach claim."""
    table.put_item(
        Item={
            "PK": f"CRED#{username}",
            "username": username,
            "otp": "OTP-123",
            "sign_in_url": "https://example.awsapps.com/start",
            "region": REGION,
            "status": "available",
        }
    )


def _claim_state_snapshot(table) -> list:
    """Snapshot the credential/lock state the gate must not touch.

    Property 6 is about the *claim* side effects — no ``EMAIL#`` lock created and
    no ``CRED#`` item mutated. It deliberately excludes ``RATE#`` items: the
    per-IP cap step runs *before* the workshop-code gate (design: pipeline
    ordering / Property 5), so it legitimately increments the ``RATE#`` counter
    even on a rejected submission. Including it would conflate the cap's expected
    write with the gate's no-write guarantee.
    """
    items = [
        item
        for item in table.scan().get("Items", [])
        if not str(item["PK"]).startswith("RATE#")
    ]
    return sorted(items, key=lambda item: item["PK"])


class _ClaimSpy:
    """Record every ``claim`` call while delegating to the real function."""

    def __init__(self, real):
        self._real = real
        self.calls: list[str] = []

    def __call__(self, email):
        self.calls.append(email)
        return self._real(email)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(
    code=correct_codes,
    email=emails,
    wrong_suffix=wrong_suffixes,
    left_pad=whitespace,
    right_pad=whitespace,
    use_empty=st.booleans(),
)
def test_wrong_or_empty_code_never_writes_padded_correct_accepted(
    monkeypatch, code, email, wrong_suffix, left_pad, right_pad, use_empty
):
    """Wrong/empty codes 403 with no write; padded-correct reaches claim.

    Feature: claim-handler-entrypoint, Property 6: A wrong or empty workshop
    code never writes
    Validates: Requirements 5.1, 5.3
    """
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name=REGION)
        _make_table(resource)
        table = resource.Table(TABLE_NAME)
        _seed_available(table)

        # Point the handler at this example's fresh moto table and set the gate's
        # configured code; the per-IP counter space is also fresh each example.
        monkeypatch.setattr(claim_handler, "REGION", REGION)
        monkeypatch.setattr(claim_handler, "TABLE_NAME", TABLE_NAME)
        monkeypatch.setattr(claim_handler, "_dynamodb", resource)
        monkeypatch.setattr(claim_handler, "_table", table)
        monkeypatch.setattr(claim_handler, "CONFIGURED_WORKSHOP_CODE", code)

        # moto-5 transact_write_items standalone-client workaround (changes no
        # handler behavior) so the accept case can execute the claim transaction.
        standalone = boto3.client("dynamodb", region_name=REGION)
        table.meta.client.transact_write_items = standalone.transact_write_items

        # Spy on claim so we can assert it is never invoked (reject half) and
        # invoked exactly once with the normalized email (accept half).
        spy = _ClaimSpy(claim_handler.claim)
        monkeypatch.setattr(claim_handler, "claim", spy)

        # --- Reject half: a wrong or empty-after-trim code --------------------
        # Build a submitted code that is either empty-after-trim (whitespace
        # only) or a byte-for-byte mismatch (correct code + a non-empty suffix).
        if use_empty:
            wrong_submitted = left_pad + right_pad  # trims to "" (may be "")
        else:
            wrong_submitted = code + wrong_suffix  # trimmed != configured code

        before = _claim_state_snapshot(table)
        reject_event = claim_handler.handler(
            _make_event_json(email, wrong_submitted), None
        )

        assert reject_event["statusCode"] == 403
        body = json.loads(reject_event["body"])
        assert set(body.keys()) == {"error"}  # Error_Envelope shape

        # No write to the claim state: the EMAIL#/CRED# items are unchanged and
        # claim never ran. (The RATE# counter from the earlier cap step is
        # excluded by _claim_state_snapshot — that write precedes the gate.)
        assert _claim_state_snapshot(table) == before
        assert spy.calls == [], "a wrong/empty code must never reach claim"

        # No EMAIL# lock was created and no CRED# flipped to claimed.
        after_items = table.scan().get("Items", [])
        assert not any(str(i["PK"]).startswith("EMAIL#") for i in after_items)
        assert all(
            i.get("status") == "available"
            for i in after_items
            if str(i["PK"]).startswith("CRED#")
        )

        # --- Accept half: a whitespace-padded but correct code ----------------
        padded_correct = left_pad + code + right_pad
        accept_event = claim_handler.handler(
            _make_event_json(email, padded_correct), None
        )

        # The gate trimmed and the pipeline proceeded to the claim step: claim
        # was invoked exactly once with the normalized email. (We assert
        # "reaches claim", not the claim's HTTP outcome.)
        assert spy.calls == [claim_handler.normalize_email(email)]
        # And the padded-correct POST did not itself 403 at the gate.
        assert accept_event["statusCode"] != 403


def _make_event_json(email: str, workshop_code) -> dict:
    """Build a POST Function URL event carrying a JSON claim body.

    A single POST per phase stays well under ``PER_IP_CAP``, so the shared
    helper's default source IP is fine.
    """
    return make_event(
        method="POST",
        body=json.dumps({"email": email, "workshop_code": workshop_code}),
    )
