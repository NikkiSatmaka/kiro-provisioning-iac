"""Unit/example tests for the handler entrypoint's existence and arity.

Validates: Requirements 1.1
Design: Testing Strategy > "Dual approach" (handler existence + arity).

Requirement 1.1 is a structural contract between the Lambda packaging and the
Terraform ``handler = "claim_handler.handler"`` reference: the ``claim_handler``
module MUST expose a module-level attribute named ``handler`` that is callable
and accepts exactly the two positional parameters the Lambda runtime passes —
``(event, context)``.

This is a poor fit for a property test (there is nothing to range over), so per
the design it is covered by a unit/example test that:

* resolves ``handler`` as a module attribute (mirroring how the runtime loads
  ``claim_handler.handler``), and asserts it is callable;
* inspects the signature with :func:`inspect.signature` and asserts exactly two
  positional parameters named ``event`` and ``context``; and
* smoke-invokes it with ``make_event()`` and a ``None`` context to confirm the
  two-argument call shape actually binds (a GET event serves the page without
  touching DynamoDB, so no moto fixture is needed).

``CONFIGURED_WORKSHOP_CODE`` / ``ALLOWED_ORIGIN`` are read from the environment
at import; this test does not reload the module (which would rebind
``ClaimError`` and break sibling tests — the documented harness trap).
"""

from __future__ import annotations

import inspect

import claim_handler

from ._handler_events import make_event

# The exact name Terraform references as ``handler = "claim_handler.handler"``.
_HANDLER_ATTR = "handler"


def test_handler_is_resolvable_as_module_attribute() -> None:
    """``claim_handler.handler`` resolves the way the runtime loads it (R1.1)."""
    assert hasattr(claim_handler, _HANDLER_ATTR)
    handler = getattr(claim_handler, _HANDLER_ATTR)
    assert handler is claim_handler.handler


def test_handler_is_callable() -> None:
    """The resolved ``handler`` attribute is callable (R1.1)."""
    assert callable(claim_handler.handler)


def test_handler_accepts_event_and_context_arity() -> None:
    """``handler`` accepts exactly two positional params: event, context (R1.1).

    The Lambda runtime invokes the entrypoint as ``handler(event, context)``,
    so the signature must have exactly those two positional parameters, in that
    order, with no extra required parameters.
    """
    signature = inspect.signature(claim_handler.handler)
    parameters = list(signature.parameters.values())

    assert [p.name for p in parameters] == ["event", "context"]

    positional_kinds = {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }
    assert all(p.kind in positional_kinds for p in parameters)
    # No defaults — the runtime always passes both arguments.
    assert all(p.default is inspect.Parameter.empty for p in parameters)


def test_handler_binds_two_argument_call() -> None:
    """A two-argument call binds and returns a response (R1.1).

    A GET ``make_event()`` with a ``None`` context exercises the real
    ``handler(event, context)`` call shape. The GET path serves the page and
    never touches DynamoDB, so no moto fixture is required; this only confirms
    the two-argument invocation binds and yields a well-formed response dict.
    """
    response = claim_handler.handler(make_event(), None)
    assert isinstance(response, dict)
    assert isinstance(response["statusCode"], int)
