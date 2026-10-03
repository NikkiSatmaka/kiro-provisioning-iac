"""Test — the generic 500 branch logs a traceback for operators.

Feature: claim-handler-entrypoint — operational diagnosability of 500s.

Regression guard for the "silent 500" that masked a real production failure:
the handler used to swallow a non-``ClaimError`` exception and return
``{"error": "internal error"}`` without logging anything, so CloudWatch showed
no traceback and the root cause (a ``TransactionCanceledException`` from a
mis-serialized DynamoDB transaction) was invisible. The handler now logs the
traceback via ``logger.exception`` on that path.

This test asserts the handler emits exactly one log record on the generic 500
branch, at ERROR level, with exception info attached (``exc_info``) so the
stack is captured. A companion property test
(``test_error_no_leak_property.py``, Property 11) proves the record the handler
emits carries no email/OTP; here we only assert that a traceback IS logged.

Validates: Requirements 7.2 (fixed 500 envelope) plus the diagnosability
follow-up — a 500 must never again be silent.
"""

from __future__ import annotations

import json
import logging

import claim_handler

from ._handler_events import make_event


def test_generic_500_logs_traceback(monkeypatch, caplog):
    """A non-ClaimError during POST logs a traceback and returns a fixed 500.

    The log record must be at ERROR level and carry ``exc_info`` so the stack
    reaches CloudWatch; the response is still the detail-free envelope.
    """
    # Force the generic 500 branch: the pipeline raises a non-ClaimError before
    # touching DynamoDB, so no moto table is needed.
    def _raise_runtime_error(_event):
        raise RuntimeError("simulated downstream failure")

    monkeypatch.setattr(claim_handler, "run_claim_pipeline", _raise_runtime_error)

    event = make_event(method="POST", body=json.dumps({"email": "a@b.example", "workshop_code": "x"}))

    with caplog.at_level(logging.ERROR, logger=claim_handler.__name__):
        caplog.clear()
        response = claim_handler.handler(event, None)

    # The response is still the fixed, detail-free 500 envelope.
    assert response["statusCode"] == 500
    assert json.loads(response["body"]) == {"error": "internal error"}

    # Exactly one record was logged, from this module, at ERROR level.
    records = [r for r in caplog.records if r.name == claim_handler.__name__]
    assert len(records) == 1, f"expected one log record, got {records!r}"
    record = records[0]
    assert record.levelno == logging.ERROR

    # A traceback is attached via exc_info so the stack reaches CloudWatch.
    assert record.exc_info is not None, "500 branch logged without exc_info (no traceback)"
    exc_type, _exc_value, exc_tb = record.exc_info
    assert exc_type is RuntimeError
    assert exc_tb is not None


def test_claim_error_path_logs_nothing(monkeypatch, caplog):
    """A ClaimError (an expected 4xx) is NOT logged as an error.

    Only the unexpected generic 500 branch logs. A ClaimError maps to its 4xx
    envelope quietly, so operators are not paged for routine rejections (wrong
    workshop code, pool exhausted, per-IP cap, bad body).
    """
    def _raise_claim_error(_event):
        raise claim_handler.ClaimError(403, "invalid workshop code")

    monkeypatch.setattr(claim_handler, "run_claim_pipeline", _raise_claim_error)

    event = make_event(method="POST", body=json.dumps({"email": "a@b.example", "workshop_code": "nope"}))

    with caplog.at_level(logging.DEBUG, logger=claim_handler.__name__):
        caplog.clear()
        response = claim_handler.handler(event, None)

    assert response["statusCode"] == 403
    records = [r for r in caplog.records if r.name == claim_handler.__name__]
    assert records == [], f"ClaimError path should not log, but logged {records!r}"
