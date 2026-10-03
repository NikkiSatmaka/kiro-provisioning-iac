"""Function URL event builder shared by the handler tests.

The claim_handler entrypoint reads an AWS Lambda Function URL event shaped as
``{"requestContext": {"http": {...}}}`` and delegates ``sourceIp`` / ``body`` /
``isBase64Encoded`` handling to the existing ``source_ip`` / ``parse_post``
building blocks. ``make_event`` builds exactly that shape so the handler tests
can drive GET / POST / OPTIONS and the "unreadable method" edge cases without
hand-rolling the dict in every test.

Design: Testing Strategy > "Simulating Function URL events".

The module is additive and importable under the existing ``conftest.py``
``sys.path`` shim; it does not require any change to ``conftest.py``.
"""

from __future__ import annotations

from typing import Any


def make_event(
    method: Any = None,
    body: str | None = None,
    source_ip: str = "203.0.113.1",
    is_base64: bool = False,
) -> dict:
    """Build a Function URL event the handler can route.

    - ``method`` is written to ``requestContext.http.method`` only when it is
      not ``None`` — so absent / non-string method cases are expressible for
      R2.5 (an absent key, or a non-string value, both exercise the
      "treat as GET" path). It may be a non-string on purpose.
    - ``source_ip`` is always written to ``requestContext.http.sourceIp``.
    - ``body`` and ``isBase64Encoded`` are added only when a ``body`` is
      supplied, mirroring a browser request that omits a body on GET/OPTIONS.
    """
    http: dict[str, Any] = {}
    if method is not None:
        http["method"] = method  # may be a non-string for R2.5 cases
    http["sourceIp"] = source_ip
    event: dict[str, Any] = {"requestContext": {"http": http}}
    if body is not None:
        event["body"] = body
        event["isBase64Encoded"] = is_base64
    return event
