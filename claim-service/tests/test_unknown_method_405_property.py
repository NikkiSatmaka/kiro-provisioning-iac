"""Property test for the unknown-method 405 route.

Feature: claim-handler-entrypoint, Property 4: Unknown methods are rejected
with 405.

Property 4: For any non-empty method string that is NOT ``GET``, ``POST``, or
``OPTIONS`` (compared case-insensitively), ``claim_handler.handler`` returns
``statusCode`` 405 with an ``Error_Envelope`` body (``{"error": ...}``), a
``Content-Type`` of ``application/json``, exactly one
``Access-Control-Allow-Origin`` equal to ``resolve_origin()``, and makes no
DynamoDB call.

Validates: Requirements 2.4.
Design: Testing Strategy; Properties list — Property 4.

Harness notes
-------------
The 405 path is pure wiring: it routes on ``request_method`` and funnels through
``json_response``, never consulting a body or counting an IP, so no moto table
is created. "No DynamoDB access" is asserted structurally — every DynamoDB touch
in the module funnels through the single ``_get_table()`` memoization
(``check_and_increment_ip`` / ``pick_available`` / ``claim`` / ``reclaim`` all
call it), so we monkeypatch it with a spy that fails the test the moment it is
called. Reaching the spy on an unknown-method request means the 405 route
performed DynamoDB access it must not (Property 4 — "makes no DynamoDB call").

The generated method strings are the whole point of this property: they must be
non-empty and, uppercased, never equal ``GET`` / ``POST`` / ``OPTIONS`` — those
three are the known verbs the handler routes elsewhere, and the empty string is
the "unreadable method" sentinel that ``request_method`` maps to a GET
(Property 2), not a 405. The ``unknown_methods`` strategy below enforces both
constraints so every example genuinely exercises the 405 branch.
"""

from __future__ import annotations

import json

import claim_handler
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ._handler_events import make_event

# The three verbs the handler routes to a non-405 branch (case-insensitively),
# plus the empty-string sentinel request_method emits for an unreadable method
# (routed to GET, not 405). Any method whose uppercase form is one of these must
# be excluded so every generated example hits the 405 path.
_KNOWN_UPPER = {"GET", "POST", "OPTIONS", ""}


class _DynamoAccessError(AssertionError):
    """Raised by the spy if the 405 path reaches DynamoDB at all."""


def _no_dynamo(*_args, **_kwargs):
    """Stand in for ``_get_table`` and fail the test on any DynamoDB access.

    Every DynamoDB touch in the module funnels through ``_get_table()``; an
    unknown-method request must be rejected with a 405 built from module config
    alone, so reaching this spy means the 405 route performed DynamoDB access it
    must not (Property 4 — "makes no DynamoDB call").
    """
    raise _DynamoAccessError(
        "unknown-method path reached _get_table(): "
        "the 405 route must perform NO DynamoDB access (Property 4)"
    )


# Arbitrary method strings that, uppercased, are never GET/POST/OPTIONS and are
# never empty. ``st.text`` draws arbitrary unicode tokens; the filter drops any
# whose uppercase form collides with a known verb (any casing) or is empty, so
# every surviving example is a genuine "unknown method" for Property 4.
unknown_methods = st.text(min_size=1, max_size=12).filter(
    lambda m: m.upper() not in _KNOWN_UPPER
)

# A handful of plausible real-world verbs that must also 405, mixed in so the
# property is not driven solely by random noise tokens.
named_unknown_methods = st.sampled_from(
    [
        "PUT",
        "put",
        "Delete",
        "PATCH",
        "head",
        "TRACE",
        "CONNECT",
        "propfind",
        "FOO",
        "gets",  # not GET
        "post ",  # trailing space → not POST once uppercased
    ]
)

all_unknown_methods = st.one_of(unknown_methods, named_unknown_methods)

# ALLOWED_ORIGIN variants: the empty string (resolves to "*", R9.2) and a few
# concrete origins that must echo back verbatim (R9.1), so the single-ACAO
# assertion tracks resolve_origin() rather than a hardcoded value.
allowed_origins = st.one_of(
    st.just(""),
    st.sampled_from(
        [
            "https://workshop.example.com",
            "http://localhost:5173",
            "*",
        ]
    ),
)

# Source IPs are opaque to the 405 path (it never counts them); vary them to
# confirm nothing on the unknown-method route consults the per-IP counter.
source_ips = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() != "")


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(method=all_unknown_methods, allowed_origin=allowed_origins, src_ip=source_ips)
def test_unknown_method_yields_405_without_dynamodb(
    monkeypatch, method, allowed_origin, src_ip
):
    """An unknown method yields a 405 Error_Envelope, no DynamoDB.

    Feature: claim-handler-entrypoint, Property 4
    Validates: Requirements 2.4
    """
    # Guard the generator's own contract: uppercased, the method is never a
    # known verb and never empty — otherwise it would not exercise the 405 path.
    assert method != ""
    assert method.upper() not in _KNOWN_UPPER

    # Drive resolve_origin() through the configured ALLOWED_ORIGIN (R9.1/R9.2).
    monkeypatch.setattr(claim_handler, "ALLOWED_ORIGIN", allowed_origin)
    # Any DynamoDB access on this path is a failure: trip the spy if reached.
    monkeypatch.setattr(claim_handler, "_get_table", _no_dynamo)

    expected_origin = claim_handler.resolve_origin()

    event = make_event(method=method, source_ip=src_ip)
    response = claim_handler.handler(event, None)

    # 405 Method Not Allowed (R2.4).
    assert response["statusCode"] == 405

    headers = response["headers"]

    # JSON Error_Envelope: application/json content type and a string body that
    # parses to an object carrying an "error" key (R2.4, R7.3).
    assert headers["Content-Type"] == "application/json"
    assert isinstance(response["body"], str)
    envelope = json.loads(response["body"])
    assert isinstance(envelope, dict)
    assert "error" in envelope

    # Exactly one Access-Control-Allow-Origin, equal to resolve_origin() (R9.5).
    assert headers["Access-Control-Allow-Origin"] == expected_origin
    acao_keys = [k for k in headers if k.lower() == "access-control-allow-origin"]
    assert acao_keys == ["Access-Control-Allow-Origin"]

    # "No DynamoDB call" — the spy above would already have raised; this is a
    # belt-and-braces assert the response is the JSON 405, not a page/preflight.
    assert "Access-Control-Allow-Methods" not in headers
