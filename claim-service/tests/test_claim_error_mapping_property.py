"""Property test for the handler's ClaimError-to-response mapping.

Feature: claim-handler-entrypoint, Property 10: ClaimError maps to its status
and verbatim message
Validates: Requirements 7.1

Property 10: For any ``ClaimError(status, message)`` the pipeline raises (with
``status`` in ``{400, 403, 409, 429}`` and an arbitrary ``message``), a POST to
``claim_handler.handler`` returns a response whose ``statusCode`` equals that
``status`` and whose ``body`` is an ``Error_Envelope`` ``{"error": message}``
with the message carried **verbatim** — plus ``Content-Type:
application/json`` and exactly one CORS ``Access-Control-Allow-Origin`` header.

Design: Testing Strategy; Properties list — Property 10.

Harness notes
-------------
The handler's single ``try/except`` maps a ``ClaimError`` to
``json_response(exc.status, {"error": exc.message}, origin)`` (design:
"handler(event, context)"). To exercise *that mapping* rather than any pipeline
internals, we monkeypatch ``claim_handler.run_claim_pipeline`` to raise a
``ClaimError(status, message)`` directly on the POST path. No moto table is
needed: the raised error short-circuits before any DynamoDB touch, so the
mapping is tested in isolation.

Messages are drawn as arbitrary text — including unicode, quotes, braces, and
newlines — to prove the envelope round-trips the message byte-for-byte through
``json.dumps``/``json.loads`` and never reformats, truncates, or escapes it
into a different string. The ``json.loads(body) == {"error": message}`` equality
is the verbatim check: a JSON-decoded body that equals ``{"error": message}``
means the original ``message`` string survived unchanged.
"""

from __future__ import annotations

import json

import claim_handler
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ._handler_events import make_event

# The four client-error statuses the pipeline raises via ClaimError (R7.1):
# 400 (bad body / invalid email), 403 (workshop-code gate), 409 (pool
# exhausted), 429 (per-IP cap). 500 is excluded — it is the handler's own
# fallback for a non-ClaimError, covered by Property 11, not Property 10.
claim_error_statuses = st.sampled_from([400, 403, 409, 429])

# Arbitrary messages: full unicode text (quotes, braces, newlines, emoji, etc.)
# so the test proves the envelope carries the message verbatim rather than only
# for tame ASCII. Control surrogate/other categories are left in to stress the
# JSON round-trip; the empty string is allowed too.
claim_error_messages = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=0,
    max_size=120,
)

# ALLOWED_ORIGIN variants so the single-ACAO assertion holds for both the
# wildcard fallback ("" -> "*") and a concrete echoed origin (R9.5).
allowed_origins = st.one_of(
    st.just(""),
    st.sampled_from(
        [
            "https://workshop.example.com",
            "https://claim.berca.test",
            "http://localhost:5173",
        ]
    ),
)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    status=claim_error_statuses,
    message=claim_error_messages,
    allowed_origin=allowed_origins,
)
def test_claim_error_maps_to_status_and_verbatim_message(
    monkeypatch, status, message, allowed_origin
):
    """A ClaimError maps to its status and a verbatim {"error": message} body.

    Feature: claim-handler-entrypoint, Property 10: ClaimError maps to its
    status and verbatim message
    Validates: Requirements 7.1
    """
    # Drive resolve_origin() so the single-ACAO assertion covers both the
    # wildcard fallback and a concrete echoed origin.
    monkeypatch.setattr(claim_handler, "ALLOWED_ORIGIN", allowed_origin)
    expected_origin = claim_handler.resolve_origin()

    # Exercise the handler's ClaimError mapping, not the pipeline internals:
    # the POST path calls run_claim_pipeline, so make it raise the error
    # directly. No DynamoDB is touched because the error short-circuits.
    def _raise_claim_error(_event):
        raise claim_handler.ClaimError(status, message)

    monkeypatch.setattr(claim_handler, "run_claim_pipeline", _raise_claim_error)

    event = make_event(method="POST", body=json.dumps({"ignored": "body"}))
    response = claim_handler.handler(event, None)

    # Status equals the ClaimError's carried status (R7.1).
    assert response["statusCode"] == status

    # Body is an Error_Envelope carrying the message verbatim: a JSON round-trip
    # that equals {"error": message} proves the original string was preserved
    # unchanged (no reformat, truncation, or re-escaping).
    body = json.loads(response["body"])
    assert body == {"error": message}

    headers = response["headers"]

    # JSON bodies carry Content-Type: application/json (R7.3).
    assert headers["Content-Type"] == "application/json"

    # Exactly one Access-Control-Allow-Origin, equal to resolve_origin() (R9.5).
    assert headers["Access-Control-Allow-Origin"] == expected_origin
    acao_keys = [k for k in headers if k.lower() == "access-control-allow-origin"]
    assert acao_keys == ["Access-Control-Allow-Origin"]
