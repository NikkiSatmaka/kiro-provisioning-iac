"""Property test — only a normalized email reaches ``claim``.

Feature: claim-handler-entrypoint, Property 7: Only a normalized email reaches claim
Validates: Requirements 6.5, 10.3

``run_claim_pipeline`` composes the fixed-order POST steps and, by design,
normalizes the submitted email *after* the workshop-code gate and *before* the
claim step (R6.5). The property: for any valid raw email submitted through the
pipeline — with mixed case and surrounding whitespace — the value handed to
``claim`` is exactly ``normalize_email(raw)`` (lowercased + stripped), never the
raw email. ``normalize_email`` is the sole key-derivation (R10.3), so ``claim``
only ever receives a canonical key.

Isolation / harness notes:
- We spy on ``claim_handler.claim`` to capture the single email argument it is
  called with and return a dummy four-field credential dict so the pipeline
  completes without touching DynamoDB.
- ``run_claim_pipeline`` runs the per-IP cap step (``check_and_increment_ip``)
  before the claim step; that step talks to DynamoDB. Because this property is
  only about what reaches ``claim``, we stub the cap step to a no-op so the test
  needs no moto table and the cap can never trip, keeping each example cheap and
  focused on the normalize-before-claim guarantee.
- ``CONFIGURED_WORKSHOP_CODE`` is set via monkeypatch and the correct code is
  submitted so the pipeline reaches the claim step (a wrong code would raise 403
  before ``claim`` and the property would be vacuous).
"""

from __future__ import annotations

import os

import claim_handler
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ._handler_events import make_event

# The workshop code the pipeline is configured to accept; the event submits the
# same value so ``verify_workshop_code`` passes and the pipeline reaches claim.
WORKSHOP_CODE = "WORKSHOP-2025"

# A dummy credential dict with exactly the four 200-contract fields, returned by
# the spy so ``run_claim_pipeline`` completes without a real claim.
DUMMY_CREDENTIAL = {
    "username": "dummy-user",
    "otp": "dummy-otp",
    "sign_in_url": "https://example.invalid/signin",
    "region": os.environ.get("AWS_REGION", "us-east-1"),
}

# Email local/domain parts: non-empty strings with no "@" and no surrounding
# whitespace of their own, so the assembled address is valid under
# ``is_valid_email`` (non-empty local, single "@", non-empty domain) and the
# only case/whitespace variation comes from the parts' letter case plus the
# ``lead``/``trail`` padding drawn separately. Surrogates are blacklisted so the
# values round-trip cleanly.
_email_part = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs", "Cc", "Zs"),
        blacklist_characters="@",
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: s == s.strip() and s != "")

# Surrounding whitespace to pad the raw email with, exercising the strip() half
# of normalization. May be empty so the "no padding" case is covered too.
_whitespace = st.text(alphabet=" \t\n\r", max_size=4)


# ``monkeypatch`` is a function-scoped fixture; Hypothesis warns it is not reset
# between generated inputs. Here every example re-applies the same three
# idempotent patches (spy claim, no-op cap, configured code) at the top of the
# test body, so a non-reset fixture cannot leak state across inputs — suppress
# the health check, matching the sibling POST-path property tests.
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(local=_email_part, domain=_email_part, lead=_whitespace, trail=_whitespace)
def test_only_normalized_email_reaches_claim(
    monkeypatch, local: str, domain: str, lead: str, trail: str
) -> None:
    """The value passed to ``claim`` is exactly ``normalize_email(raw)``.

    Feature: claim-handler-entrypoint, Property 7: Only a normalized email reaches claim
    Validates: Requirements 6.5, 10.3
    """
    raw_email = f"{lead}{local}@{domain}{trail}"

    # Guard the generator: the assembled address must be valid under the
    # pipeline's own format check, otherwise it would raise 400 before claim.
    assume_valid = claim_handler.is_valid_email(raw_email)
    assert assume_valid, "generator produced an email invalid under is_valid_email"

    captured: dict[str, str] = {}

    def spy_claim(email: str) -> dict:
        captured["email"] = email
        return dict(DUMMY_CREDENTIAL)

    # Spy on claim to capture its email argument and short-circuit the real DB
    # claim; stub the per-IP cap so the pipeline needs no moto table and never
    # trips the cap; configure the workshop code so the submitted code matches.
    monkeypatch.setattr(claim_handler, "claim", spy_claim)
    monkeypatch.setattr(claim_handler, "check_and_increment_ip", lambda ip, cap: None)
    monkeypatch.setattr(claim_handler, "CONFIGURED_WORKSHOP_CODE", WORKSHOP_CODE)

    body = claim_handler.json.dumps(
        {"email": raw_email, "workshop_code": WORKSHOP_CODE}
    )
    # A fresh source IP keeps the (stubbed) cap step unambiguous and models a
    # distinct caller per example.
    event = make_event("POST", body=body, source_ip="203.0.113.7")

    result = claim_handler.run_claim_pipeline(event)

    # The pipeline reached the claim step exactly once with a captured email.
    assert "email" in captured, "pipeline never reached the claim step"

    expected = claim_handler.normalize_email(raw_email)
    # claim received the canonical key — lowercased + stripped — never the raw.
    assert captured["email"] == expected
    assert captured["email"] == captured["email"].strip()
    assert captured["email"] == captured["email"].lower()

    # The pipeline returns exactly what the (spied) claim handed back.
    assert result == DUMMY_CREDENTIAL
