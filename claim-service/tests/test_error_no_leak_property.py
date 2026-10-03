"""Property test — errors never leak exception detail, email, or OTP.

Feature: claim-handler-entrypoint, Property 11: Errors never leak exception
detail, email, or OTP.

Property 11: For any non-``ClaimError`` exception raised during a POST — even
one whose own message embeds the submitted email and an OTP — the handler
returns ``statusCode`` 500 with a fixed ``Error_Envelope`` whose body contains
NONE of: the raised exception's type name, its detail/message/stack text, the
submitted email, or any OTP value. The response still carries
``Content-Type: application/json`` and exactly one CORS header. The fixed body
is exactly ``{"error": "internal error"}``.

Validates: Requirements 7.2, 7.4.
Design: Testing Strategy; Properties list — Property 11; PII discipline.

Harness notes
-------------
The 500 path is forced by monkeypatching ``claim_handler.run_claim_pipeline`` to
raise a non-``ClaimError`` (a ``RuntimeError``) whose message deliberately
embeds the Hypothesis-generated submitted email and an OTP-like string. The
handler's ``except Exception`` branch must swallow all of that and return the
fixed envelope, so no DynamoDB table is needed on this path.

Because the pipeline is stubbed to raise before touching DynamoDB, the test
reaches the handler's generic 500 branch directly — the thing Property 11 is
about — without seeding a moto pool.

R7.4 (no PII in logs): the handler's generic 500 branch emits no log records.
We assert that via ``caplog`` — no emitted log record (message or arguments)
contains the submitted email or OTP. If a future change starts logging on this
path, this assertion catches any PII that rides along.
"""

from __future__ import annotations

import json
import logging

import claim_handler
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ._handler_events import make_event

# The exact fixed 500 body the design mandates — no exception type, detail,
# stack text, email, or OTP (R7.2; design: Status taxonomy, 500 row).
FIXED_ERROR_BODY = {"error": "internal error"}

# Submitted emails: a non-empty local part + domain so the value is a plausible
# address, and long/odd enough to be a distinctive substring we can search for
# in the response body. The format need not pass is_valid_email — the pipeline
# is stubbed to raise before validation runs; what matters is that the exact
# string is embedded in the raised exception's message.
emails = st.builds(
    lambda local, domain: f"{local}@{domain}.example",
    local=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        min_size=1,
        max_size=20,
    ),
    domain=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")),
        min_size=1,
        max_size=20,
    ),
)

# OTP-like secrets: short mixed-case alphanumeric strings standing in for the
# credential OTP that must never surface in an error body or log line.
otps = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Nd")),
    min_size=4,
    max_size=16,
).filter(lambda s: s != "")


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(email=emails, otp=otps)
def test_internal_error_leaks_no_detail_email_or_otp(monkeypatch, caplog, email, otp):
    """A non-ClaimError during POST yields a fixed 500 that leaks nothing.

    Feature: claim-handler-entrypoint, Property 11
    Validates: Requirements 7.2, 7.4
    """
    # The pipeline blows up with a non-ClaimError whose message embeds BOTH the
    # submitted email and the OTP — the worst case for leakage. The handler's
    # generic 500 branch must reveal none of it.
    exc_message = f"boom email={email} otp={otp}"

    def _raise_runtime_error(_event):
        raise RuntimeError(exc_message)

    monkeypatch.setattr(claim_handler, "run_claim_pipeline", _raise_runtime_error)

    # A POST body that also carries the email/OTP, so we exercise a realistic
    # request shape — though the stub raises before the body is parsed.
    body = json.dumps({"email": email, "workshop_code": otp})
    event = make_event(method="POST", body=body)

    with caplog.at_level(logging.DEBUG, logger=claim_handler.__name__):
        caplog.clear()
        response = claim_handler.handler(event, None)

    # --- Fixed 500 envelope, byte-for-byte (R7.2; design: 500 row) ---------
    assert response["statusCode"] == 500
    body_text = response["body"]
    assert isinstance(body_text, str)
    assert json.loads(body_text) == FIXED_ERROR_BODY

    # --- Uniform headers: application/json + exactly one CORS header -------
    headers = response["headers"]
    assert headers["Content-Type"] == "application/json"
    expected_origin = claim_handler.resolve_origin()
    assert headers["Access-Control-Allow-Origin"] == expected_origin
    acao_keys = [k for k in headers if k.lower() == "access-control-allow-origin"]
    assert acao_keys == ["Access-Control-Allow-Origin"]

    # --- Nothing sensitive appears anywhere in the body (R7.2, R7.4) -------
    # The body must contain NONE of: the submitted email, the OTP, the raised
    # exception's type name, its message text, or any traceback-ish token.
    forbidden = [
        email,
        otp,
        exc_message,
        "RuntimeError",
        "boom",
        "Traceback",
        "File \"",
        ", line ",
    ]
    for needle in forbidden:
        assert needle not in body_text, (
            f"response body leaked {needle!r}: {body_text!r}"
        )

    # --- R7.4: no log line emitted for this request carries the PII --------
    # The generic 500 branch emits no logs; assert defensively that if any
    # record WAS emitted, none of it (message or args) contains the email/OTP.
    for record in caplog.records:
        rendered = record.getMessage()
        assert email not in rendered, f"log record leaked email: {rendered!r}"
        assert otp not in rendered, f"log record leaked otp: {rendered!r}"
        for arg in record.args or ():
            text = str(arg)
            assert email not in text, f"log arg leaked email: {text!r}"
            assert otp not in text, f"log arg leaked otp: {text!r}"
