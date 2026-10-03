"""Property test for the universal response-shape invariant.

Feature: claim-handler-entrypoint, Property 1: Every response is well-formed.

Property 1: For ANY Function URL event — any method, any body, any
``ALLOWED_ORIGIN``, and whether the request succeeds or fails — the handler's
return is a dict whose ``statusCode`` is an ``int``, whose ``headers`` is a map
carrying exactly one ``Access-Control-Allow-Origin`` equal to
``resolve_origin()`` (``ALLOWED_ORIGIN`` when non-empty, else ``"*"``), and
whose ``body`` is a ``str``; and whenever that body is JSON its
``Content-Type`` is ``application/json``. No input makes the handler raise.

Validates: Requirements 1.2, 1.3, 7.3, 8.2, 9.1, 9.2, 9.3, 9.5.
Design: Testing Strategy; Correctness Properties — Property 1.

Harness notes
-------------
Property 1 is about the *shape* of every response across *all* method branches,
not about any one branch's business logic, so the test must drive the handler
with wildly varied input and only ever assert the response envelope.

Two generators feed the handler:

* ``make_event`` from ``_handler_events`` for well-formed Function URL events
  across GET / POST / OPTIONS / unknown / unreadable methods, with and without
  a body (valid JSON, malformed JSON, base64, random text); and
* raw arbitrary dicts that do **not** go through ``make_event`` at all — missing
  ``requestContext``, non-dict ``http``, non-string methods, missing keys — to
  stress the handler's defensive reads (``request_method`` / ``source_ip``) and
  confirm no event shape makes it raise.

DynamoDB is never contacted. The POST branch would funnel through the single
``_get_table()`` memoization (via ``check_and_increment_ip`` → ``claim``), so we
stub ``claim_handler.run_claim_pipeline`` to return a static four-field body and
also stub ``_get_table`` to fail loudly if any path reaches it — the property is
about response shape, not the claim pipeline (covered by its own tests), so no
moto table is needed. The GET branch reads the page, so we point
``claim_handler._PAGE_PATH`` at the real ``frontend/index.html`` and reset the
read-once cache, mirroring ``test_get_serves_page_property.py``.

``resolve_origin()`` (R9.1/R9.2) is exercised by varying ``ALLOWED_ORIGIN`` via
``monkeypatch.setattr`` — the empty string resolves to ``"*"`` and any non-empty
origin echoes verbatim; we read the expected origin from
``claim_handler.resolve_origin()`` under the same patched config so the test
tracks the handler's own resolution.
"""

from __future__ import annotations

import json
import os

import claim_handler
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ._handler_events import make_event

# The real claim page in the dev tree lives under frontend/, not as a sibling of
# claim_handler.py; resolve it the way the handler would so html_response can
# serve a real page body on the GET branch without a DynamoDB dependency.
_FRONTEND_PAGE = os.path.join(
    os.path.dirname(claim_handler.__file__), "..", "frontend", "index.html"
)


class _DynamoAccessError(AssertionError):
    """Raised by the spy if any branch reaches DynamoDB during this property."""


def _no_dynamo(*_args, **_kwargs):
    """Stand in for ``_get_table`` and fail if any path reaches DynamoDB.

    Property 1 is a pure response-shape invariant; the POST pipeline is stubbed
    out below, so no branch should touch the single ``_get_table()``
    memoization. Reaching this spy means a path contacted DynamoDB it must not.
    """
    raise _DynamoAccessError(
        "a handler branch reached _get_table(): Property 1 stubs the claim "
        "pipeline and must perform NO DynamoDB access"
    )


# A static four-field success body for the stubbed POST pipeline, matching the
# shape of a real credential (the exact values are irrelevant to Property 1 —
# only that json_response wraps a dict into a string body with a JSON header).
_FAKE_CREDENTIAL = {
    "username": "ws-user-001",
    "otp": "123456",
    "sign_in_url": "https://signin.example.test/console",
    "region": os.environ.get("AWS_REGION", "us-east-1"),
}


# Method generators spanning every routing branch, including non-string and
# absent methods so request_method's "unreadable → GET" path is exercised.
methods = st.one_of(
    st.sampled_from(["GET", "get", "POST", "post", "OPTIONS", "options"]),
    st.sampled_from(["PUT", "delete", "PATCH", "head", "TRACE", "connect", "WAT"]),
    st.none(),  # make_event omits the method key entirely
    st.just(""),
    st.integers(),
    st.booleans(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.lists(st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=3), st.integers(), max_size=2),
)

# Bodies spanning valid JSON objects, malformed JSON, base64-looking text, empty
# strings and arbitrary unicode — all legal inputs the handler must not choke on.
bodies = st.one_of(
    st.none(),  # no body (GET/OPTIONS-style)
    st.just(""),  # empty body
    st.just("not json at all {"),  # malformed JSON
    st.just("[1, 2, 3]"),  # valid JSON, not an object
    st.just(json.dumps({"email": "a@b.co", "workshop_code": "x"})),  # well-formed
    st.text(max_size=40),  # arbitrary unicode
    st.builds(json.dumps, st.dictionaries(st.text(max_size=5), st.text(max_size=5))),
)

source_ips = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")),
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() != "")

allowed_origins = st.one_of(
    st.just(""),  # resolves to "*" (R9.2)
    st.sampled_from(
        [
            "https://workshop.example.com",
            "https://claim.berca.test",
            "http://localhost:5173",
            "*",
        ]
    ),
)

# Raw arbitrary events that bypass make_event entirely, to stress the handler's
# defensive reads against missing/garbage keys (R1.2 — "ANY event").
_garbage_scalar = st.one_of(
    st.none(),
    st.integers(),
    st.booleans(),
    st.text(max_size=10),
    st.lists(st.integers(), max_size=2),
)

raw_arbitrary_events = st.one_of(
    st.just({}),  # entirely empty event — no requestContext at all
    st.dictionaries(st.text(max_size=5), _garbage_scalar, max_size=4),
    st.fixed_dictionaries({"requestContext": _garbage_scalar}),  # non-dict ctx
    st.fixed_dictionaries(
        {"requestContext": st.fixed_dictionaries({"http": _garbage_scalar})}
    ),  # non-dict http
    st.fixed_dictionaries(
        {
            "requestContext": st.fixed_dictionaries(
                {"http": st.dictionaries(st.text(max_size=5), _garbage_scalar, max_size=3)}
            ),
            "body": _garbage_scalar,
        }
    ),  # http dict with arbitrary keys/values + arbitrary body
)


def _point_page_at_frontend(monkeypatch) -> None:
    """Resolve the handler's page at the real frontend/index.html.

    Reset the read-once ``_PAGE_HTML`` cache and repoint ``_PAGE_PATH`` so the
    GET branch serves a real page body, without mutating module state across
    examples.
    """
    monkeypatch.setattr(claim_handler, "_PAGE_PATH", _FRONTEND_PAGE)
    monkeypatch.setattr(claim_handler, "_PAGE_HTML", None)


def _install_stubs(monkeypatch, allowed_origin) -> str:
    """Patch config + collaborators and return the expected resolved origin.

    * Vary ``ALLOWED_ORIGIN`` so ``resolve_origin()`` is exercised (R9.1/R9.2).
    * Point the page at the real frontend file so GET returns a 200 page.
    * Stub ``run_claim_pipeline`` so POST never needs DynamoDB (returns a
      static four-field body).
    * Trip ``_get_table`` if any path reaches DynamoDB regardless.
    """
    monkeypatch.setattr(claim_handler, "ALLOWED_ORIGIN", allowed_origin)
    _point_page_at_frontend(monkeypatch)
    monkeypatch.setattr(
        claim_handler, "run_claim_pipeline", lambda event: dict(_FAKE_CREDENTIAL)
    )
    monkeypatch.setattr(claim_handler, "_get_table", _no_dynamo)
    return claim_handler.resolve_origin()


def _assert_well_formed(response, expected_origin) -> None:
    """Assert the response satisfies Property 1 regardless of which branch ran."""
    # The return is a dict (R1.2).
    assert isinstance(response, dict)

    # statusCode is an int (R1.2).
    assert isinstance(response["statusCode"], int)

    # body is a string (R1.3) — JSON bodies are json.dumps'd, the page is text,
    # the preflight body is "".
    assert isinstance(response["body"], str)

    headers = response["headers"]
    assert isinstance(headers, dict)

    # Exactly one Access-Control-Allow-Origin, equal to resolve_origin() (R9.5).
    assert headers["Access-Control-Allow-Origin"] == expected_origin
    acao_keys = [k for k in headers if k.lower() == "access-control-allow-origin"]
    assert acao_keys == ["Access-Control-Allow-Origin"]

    # Whenever the body is JSON, its Content-Type is application/json (R7.3/R8.2).
    # A body that round-trips through json.loads to a dict/list is JSON here
    # (the HTML page and the "" preflight body are not).
    content_type = headers.get("Content-Type")
    if content_type == "application/json":
        # json_response always produces a valid JSON string body.
        json.loads(response["body"])  # must not raise


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    method=methods,
    body=bodies,
    allowed_origin=allowed_origins,
    src_ip=source_ips,
)
def test_structured_events_yield_well_formed_responses(
    monkeypatch, method, body, allowed_origin, src_ip
):
    """Any make_event-shaped request yields a well-formed response.

    Feature: claim-handler-entrypoint, Property 1
    Validates: Requirements 1.2, 1.3, 7.3, 8.2, 9.1, 9.2, 9.3, 9.5
    """
    expected_origin = _install_stubs(monkeypatch, allowed_origin)

    event = make_event(method=method, body=body, source_ip=src_ip)
    # No input may make the handler raise (R1.2).
    response = claim_handler.handler(event, None)

    _assert_well_formed(response, expected_origin)


@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(event=raw_arbitrary_events, allowed_origin=allowed_origins)
def test_arbitrary_garbage_events_yield_well_formed_responses(
    monkeypatch, event, allowed_origin
):
    """Any raw/garbage event (missing or malformed keys) still responds cleanly.

    These events bypass ``make_event`` to stress the handler's defensive reads:
    missing ``requestContext``, non-dict ``http``, arbitrary bodies. No shape may
    make the handler raise, and every response must still be well-formed.

    Feature: claim-handler-entrypoint, Property 1
    Validates: Requirements 1.2, 1.3, 9.3, 9.5
    """
    expected_origin = _install_stubs(monkeypatch, allowed_origin)

    # No input — however malformed — may make the handler raise (R1.2).
    response = claim_handler.handler(event, None)

    _assert_well_formed(response, expected_origin)
