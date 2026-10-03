"""Property test for the OPTIONS CORS-preflight route.

Feature: claim-handler-entrypoint, Property 3: OPTIONS yields the preflight
response without touching DynamoDB.

Property 3: For any event whose method equals ``OPTIONS`` case-insensitively,
and any ``ALLOWED_ORIGIN``, the handler returns ``statusCode`` 204, an
empty-string ``body``, exactly one ``Access-Control-Allow-Origin`` equal to
``resolve_origin()``, an ``Access-Control-Allow-Methods`` of exactly
``GET, POST``, and an ``Access-Control-Allow-Headers`` of exactly
``content-type`` — and makes no DynamoDB call.

Validates: Requirements 2.3, 9.4, 9.5.
Design: Testing Strategy; Properties list — Property 3.

Harness notes
-------------
The preflight path never reads a body or counts an IP, so no moto table is
created. "No DynamoDB access" is asserted structurally: every DynamoDB touch in
the module funnels through the single ``_get_table()`` memoization, so we
monkeypatch it with a spy that fails the test the moment it is called. Reaching
it on the OPTIONS path means the preflight route performed DynamoDB access it
must not.

``resolve_origin()`` semantics (R9.1/R9.2) are exercised by varying
``ALLOWED_ORIGIN`` via ``monkeypatch.setattr(claim_handler, "ALLOWED_ORIGIN",
...)``: the empty string must resolve to the ``"*"`` wildcard, and any non-empty
concrete origin must echo back verbatim. We read the expected origin from
``claim_handler.resolve_origin()`` under the same patched config so the test
tracks the handler's own resolution rather than hardcoding it.

The ACAO header is asserted "exactly one" (R9.5) by checking the resolved value
appears under the single ``Access-Control-Allow-Origin`` key and that no second,
differently-cased key carries a conflicting value.

NOTE: ``claim_handler.handler`` (task 9.1) may not exist yet. This test is
written against the handler contract so it passes once ``handler`` is
implemented; until then it fails only with ``AttributeError`` on the missing
``handler`` symbol — that is the expected pre-implementation state, not a
weakened assertion.
"""

from __future__ import annotations

import claim_handler
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ._handler_events import make_event


class _DynamoAccessError(AssertionError):
    """Raised by the spy if the OPTIONS path reaches DynamoDB at all."""


def _no_dynamo(*_args, **_kwargs):
    """Stand in for ``_get_table`` and fail the test on any DynamoDB access.

    Every DynamoDB touch in the module funnels through ``_get_table()``; an
    OPTIONS preflight must build its response from module config alone, so
    reaching this spy means the preflight route performed DynamoDB access it
    must not (Property 3 — "performs no DynamoDB access").
    """
    raise _DynamoAccessError(
        "OPTIONS preflight path reached _get_table(): "
        "the preflight route must perform NO DynamoDB access (Property 3)"
    )


# OPTIONS in every casing — routing compares case-insensitively (R2.3).
options_casings = st.sampled_from(
    ["OPTIONS", "options", "Options", "OpTiOnS", "oPtIoNs", "optionS"]
)

# ALLOWED_ORIGIN variants: the empty string (resolves to "*", R9.2) and a
# selection of non-empty concrete origins that must echo back verbatim (R9.1).
allowed_origins = st.one_of(
    st.just(""),
    st.sampled_from(
        [
            "https://workshop.example.com",
            "https://claim.berca.test",
            "http://localhost:5173",
            "*",
        ]
    ),
)

# Source IPs are opaque to the preflight path (it never counts them); vary them
# to confirm nothing on the OPTIONS route consults the per-IP counter.
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
@given(method=options_casings, allowed_origin=allowed_origins, src_ip=source_ips)
def test_options_yields_preflight_without_dynamodb(
    monkeypatch, method, allowed_origin, src_ip
):
    """OPTIONS (any casing) yields the 204 preflight response, no DynamoDB.

    Feature: claim-handler-entrypoint, Property 3
    Validates: Requirements 2.3, 9.4, 9.5
    """
    # Drive resolve_origin() through the configured ALLOWED_ORIGIN (R9.1/R9.2).
    monkeypatch.setattr(claim_handler, "ALLOWED_ORIGIN", allowed_origin)
    # Any DynamoDB access on this path is a failure: trip the spy if reached.
    monkeypatch.setattr(claim_handler, "_get_table", _no_dynamo)

    # Expected origin under the same patched config: empty -> "*", else verbatim.
    expected_origin = claim_handler.resolve_origin()
    assert expected_origin == (allowed_origin if allowed_origin else "*")

    event = make_event(method=method, source_ip=src_ip)
    response = claim_handler.handler(event, None)

    # 204 with an empty-string body (R2.3).
    assert response["statusCode"] == 204
    assert response["body"] == ""

    headers = response["headers"]

    # Exactly one Access-Control-Allow-Origin, equal to resolve_origin() (R9.5).
    assert headers["Access-Control-Allow-Origin"] == expected_origin
    acao_keys = [k for k in headers if k.lower() == "access-control-allow-origin"]
    assert acao_keys == ["Access-Control-Allow-Origin"]

    # Allowed methods list exactly GET and POST (R9.4) — order and set checked.
    assert headers["Access-Control-Allow-Methods"] == "GET, POST"
    methods = {m.strip() for m in headers["Access-Control-Allow-Methods"].split(",")}
    assert methods == {"GET", "POST"}

    # Allowed headers list exactly content-type (R9.4).
    assert headers["Access-Control-Allow-Headers"] == "content-type"
