"""Unit/example tests for the workshop-code gate ``verify_workshop_code``.

Validates: Requirements 5.1, 5.2, 5.3
Design: Testing Strategy > "Dual approach" (structural check that the gate uses
``hmac.compare_digest`` for a constant-time compare, R5.2).

``verify_workshop_code(submitted)`` trims the submitted code and compares it
against the module-level ``CONFIGURED_WORKSHOP_CODE`` with
``hmac.compare_digest`` — the stdlib constant-time comparison — raising
``ClaimError(403, "invalid workshop code")`` on an empty-after-trim or
mismatched code (R5.3).

Two things are asserted here:

* **Structural (R5.2):** the gate actually routes its comparison through
  ``hmac.compare_digest``. Wall-clock timing cannot be asserted reliably, so
  per the design we check this structurally two ways — a spy that confirms
  ``hmac.compare_digest`` is invoked during a call on a present code, and a
  source inspection confirming the call appears in the function body.
* **Behavioral (R5.1, R5.3):** a correct code (including a whitespace-padded
  one) passes; an empty-after-trim or mismatched code raises
  ``ClaimError(403)``.

``CONFIGURED_WORKSHOP_CODE`` is read from the environment at import, so each
test pins it with ``monkeypatch.setattr(claim_handler, "CONFIGURED_WORKSHOP_CODE",
...)`` rather than reloading the module (which would rebind ``ClaimError`` and
break sibling tests — the documented harness trap).
"""

from __future__ import annotations

import hmac
import inspect

import claim_handler
import pytest
from claim_handler import ClaimError

WORKSHOP_CODE = "swordfish-2024"


# --- Structural check: the gate uses hmac.compare_digest (R5.2) ------------

def test_verify_uses_compare_digest_spy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A call on a present code routes its compare through ``hmac.compare_digest``.

    Spies on ``claim_handler.hmac.compare_digest`` and asserts the gate invoked
    it with the trimmed candidate and the configured code (R5.2). Timing is not
    asserted — only that the constant-time primitive is the comparison used.
    """
    monkeypatch.setattr(claim_handler, "CONFIGURED_WORKSHOP_CODE", WORKSHOP_CODE)

    calls: list[tuple[str, str]] = []
    real_compare_digest = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real_compare_digest(a, b)

    monkeypatch.setattr(claim_handler.hmac, "compare_digest", spy)

    claim_handler.verify_workshop_code(WORKSHOP_CODE)

    assert calls == [(WORKSHOP_CODE, WORKSHOP_CODE)], (
        "verify_workshop_code must compare the trimmed candidate against "
        "CONFIGURED_WORKSHOP_CODE via hmac.compare_digest"
    )


def test_verify_source_calls_compare_digest() -> None:
    """The gate's source body calls ``hmac.compare_digest`` (R5.2).

    A source-level structural check: a refactor that swapped the constant-time
    compare for ``==`` would silently reintroduce a timing side channel, so we
    pin the primitive in the function body itself.
    """
    source = inspect.getsource(claim_handler.verify_workshop_code)
    assert "hmac.compare_digest" in source


# --- Behavioral contract: correct passes, empty/mismatch raises 403 --------

def test_correct_code_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """An exact match returns ``None`` so the pipeline proceeds (R5.3)."""
    monkeypatch.setattr(claim_handler, "CONFIGURED_WORKSHOP_CODE", WORKSHOP_CODE)
    assert claim_handler.verify_workshop_code(WORKSHOP_CODE) is None


@pytest.mark.parametrize("padded", [
    f"  {WORKSHOP_CODE}",
    f"{WORKSHOP_CODE}  ",
    f"\t{WORKSHOP_CODE}\n",
    f"   {WORKSHOP_CODE}   ",
])
def test_whitespace_padded_correct_code_passes(
    padded: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A correct code with surrounding whitespace trims and passes (R5.1, R5.3)."""
    monkeypatch.setattr(claim_handler, "CONFIGURED_WORKSHOP_CODE", WORKSHOP_CODE)
    assert claim_handler.verify_workshop_code(padded) is None


@pytest.mark.parametrize("empty", ["", "   ", "\t", "\n", " \t \n "])
def test_empty_after_trim_raises_403(
    empty: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty-after-trim code raises ``ClaimError(403)`` (R5.3)."""
    monkeypatch.setattr(claim_handler, "CONFIGURED_WORKSHOP_CODE", WORKSHOP_CODE)
    with pytest.raises(ClaimError) as exc_info:
        claim_handler.verify_workshop_code(empty)
    assert exc_info.value.status == 403
    assert exc_info.value.message == "invalid workshop code"


@pytest.mark.parametrize("wrong", [
    "wrong-code",
    "swordfish-2023",
    "SWORDFISH-2024",  # case-sensitive: not a match
    "swordfish-2024-extra",
    "x",
])
def test_mismatched_code_raises_403(
    wrong: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A present-but-wrong code raises ``ClaimError(403)`` (R5.3)."""
    monkeypatch.setattr(claim_handler, "CONFIGURED_WORKSHOP_CODE", WORKSHOP_CODE)
    with pytest.raises(ClaimError) as exc_info:
        claim_handler.verify_workshop_code(wrong)
    assert exc_info.value.status == 403
    assert exc_info.value.message == "invalid workshop code"


def test_empty_configured_code_rejects_every_submission(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``CONFIGURED_WORKSHOP_CODE`` is ``""`` the gate fails closed (R5.3).

    A non-empty candidate never equals ``""`` under ``compare_digest``, and an
    empty candidate is caught by the explicit empty-after-trim check — so a
    misconfigured deployment denies access rather than letting anyone claim.
    """
    monkeypatch.setattr(claim_handler, "CONFIGURED_WORKSHOP_CODE", "")
    with pytest.raises(ClaimError) as exc_info:
        claim_handler.verify_workshop_code("anything")
    assert exc_info.value.status == 403
