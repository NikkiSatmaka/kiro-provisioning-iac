"""Property test for the GET / unreadable-method page route.

Feature: claim-handler-entrypoint, Property 2: GET (and any unreadable method)
serves the page without touching DynamoDB.

Property 2: For any event whose method equals ``GET`` case-insensitively, or
whose method is absent, empty, or not a string, the handler returns
``statusCode`` 200, a ``Content-Type`` of ``text/html; charset=utf-8``, a
``body`` equal to the packaged ``index.html`` contents, and makes no DynamoDB
call.

Validates: Requirements 2.1, 2.5 (and 3.2 for the body-equals-page contract).
Design: Testing Strategy; Properties list — Property 2.

Harness notes
-------------
The handler reads its method from ``requestContext.http.method`` and treats an
absent / empty / non-string method as a ``GET`` (``request_method`` returns the
``""`` sentinel). ``make_event`` from ``_handler_events`` expresses all of those
variants: a mixed-case ``GET`` string, an absent ``method`` key (``method=None``
omits it), an empty string, and non-string values.

"No DynamoDB access" is asserted structurally rather than by scanning a table:
the GET path must never reach the single ``_get_table()`` memoization that every
DynamoDB touch funnels through (``check_and_increment_ip`` / ``pick_available``
/ ``claim`` / ``reclaim`` all call it). We monkeypatch ``_get_table`` with a spy
that fails the test the moment it is called, so any stray DynamoDB access on the
GET path is caught. No moto table is created — the page route must not need one.

The dev tree ships ``index.html`` under ``frontend/`` rather than as a sibling
of ``claim_handler.py`` (the deployment package zips them together, but the repo
layout keeps them apart). So we point ``claim_handler._PAGE_PATH`` at the real
``frontend/index.html`` and reset the ``_PAGE_HTML`` read-once cache before each
example, mirroring how the handler resolves the page at the package root.
"""

from __future__ import annotations

import os

import claim_handler
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ._handler_events import make_event

# The real claim page in the dev tree. In the deployment package index.html is a
# sibling of claim_handler.py; here it lives under frontend/, so resolve it
# relative to the handler module and read it as the expected GET body.
_FRONTEND_PAGE = os.path.join(
    os.path.dirname(claim_handler.__file__), "..", "frontend", "index.html"
)
_EXPECTED_PAGE = open(_FRONTEND_PAGE, encoding="utf-8").read()  # noqa: SIM115


class _DynamoAccessError(AssertionError):
    """Raised by the spy if the GET path reaches DynamoDB at all."""


def _no_dynamo(*_args, **_kwargs):
    """Stand in for ``_get_table`` and fail the test on any DynamoDB access.

    Every DynamoDB touch in the module funnels through ``_get_table()``; a GET
    (or unreadable-method) request must serve the static page without one, so
    reaching this spy means the page route performed DynamoDB access it must not
    (Property 2 — "makes no DynamoDB call").
    """
    raise _DynamoAccessError(
        "GET/unreadable-method path reached _get_table(): "
        "the page route must perform NO DynamoDB access (Property 2)"
    )


def _point_page_at_frontend(monkeypatch) -> None:
    """Resolve the handler's page at the real frontend/index.html.

    Reset the read-once ``_PAGE_HTML`` cache and repoint ``_PAGE_PATH`` so
    ``_load_page`` reads the actual dev-tree page rather than the (absent)
    sibling path, without mutating module state across examples.
    """
    monkeypatch.setattr(claim_handler, "_PAGE_PATH", _FRONTEND_PAGE)
    monkeypatch.setattr(claim_handler, "_PAGE_HTML", None)


# Method variants that must all be routed to the page:
#   - "GET" in any casing (R2.1, compared case-insensitively);
#   - absent key / empty string / non-string values (R2.5, "unreadable method").
# ``make_event(method=None)`` omits the method key entirely (absent case);
# other non-string values exercise the "not a string" branch of request_method.
get_casings = st.sampled_from(["GET", "get", "Get", "gEt", "GeT", "gET"])

unreadable_methods = st.one_of(
    st.none(),  # absent method key (make_event omits it)
    st.just(""),  # empty string
    st.integers(),  # non-string: int
    st.booleans(),  # non-string: bool
    st.floats(allow_nan=False, allow_infinity=False),  # non-string: float
    st.lists(st.integers(), max_size=3),  # non-string: list
    st.dictionaries(st.text(max_size=3), st.integers(), max_size=2),  # non-string: dict
)

page_methods = st.one_of(get_casings, unreadable_methods)

# Source IPs are opaque to the GET path (it never counts them), but vary them to
# confirm nothing on the page route consults the per-IP counter.
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
@given(method=page_methods, src_ip=source_ips)
def test_get_or_unreadable_method_serves_page_without_dynamodb(
    monkeypatch, method, src_ip
):
    """GET (any casing) or an unreadable method serves the page, no DynamoDB.

    Feature: claim-handler-entrypoint, Property 2
    Validates: Requirements 2.1, 2.5
    """
    _point_page_at_frontend(monkeypatch)
    # Any DynamoDB access on this path is a failure: trip the spy if reached.
    monkeypatch.setattr(claim_handler, "_get_table", _no_dynamo)

    event = make_event(method=method, source_ip=src_ip)
    response = claim_handler.handler(event, None)

    # 200 OK with the HTML content type (R2.1 / R2.5).
    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "text/html; charset=utf-8"

    # Body is the packaged page contents, verbatim (R3.2), and a string (R1.3).
    assert isinstance(response["body"], str)
    assert response["body"] == _EXPECTED_PAGE

    # "No DynamoDB call" — the spy above would already have raised; this is a
    # belt-and-braces assert that the response did not route through the claim
    # pipeline (which would have carried an application/json content type).
    assert response["headers"]["Content-Type"] != "application/json"
