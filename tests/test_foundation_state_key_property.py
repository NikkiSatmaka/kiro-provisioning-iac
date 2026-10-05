"""Property 5: foundation state key is the fixed, prefix-free constant.

Feature: foundation-idc-service, Property 5: The foundation state key is the
fixed, prefix-free constant
Validates: Requirements 4.3, 4.4, 6.4

Property 5: *For any* invocation of a foundation task, the init-time state key
(mirrored by ``foundation_state_key.foundation_state_key``) SHALL be exactly
``foundation/terraform.tfstate`` and SHALL NOT begin with a ``workshops/<id>/``
segment — distinguishing it from the workshop-scoped subscription and
claim-service keys ``workshops/<id>/<stack>/terraform.tfstate`` (R4.3, R4.4,
R6.4).

The key is a fixed constant, not a function of any input, so the property is the
invariant that *no matter what* workshop id one constructs a ``workshops/<id>/``
prefix from, the foundation key never equals it or begins with it. The test
draws arbitrary workshop ids and asserts, for every one:

- the key is byte-exact ``foundation/terraform.tfstate`` (R4.3);
- it does NOT begin with ``workshops/`` at all, so it carries no
  ``workshops/<id>/`` prefix for any id (R4.4);
- it is distinct from the workshop-scoped key form built from that id (R4.4);
- it has no leading key-path noise — its first path segment is ``foundation``,
  never ``workshops`` (R4.4, R6.4).

A regression that namespaced the foundation key under ``workshops/``, changed the
filename, or otherwise drifted from the literal fails here.

Harness note: ``foundation_state_key`` lives under ``tests/`` and is importable
via the shared conftest ``sys.path`` shim (``tests/`` is on the path), mirroring
the sibling property tests (e.g. ``test_state_key_scheme_property.py``).
"""

from __future__ import annotations

import foundation_state_key as fsk
from hypothesis import given, settings
from hypothesis import strategies as st

# Arbitrary workshop-id-shaped strings used only to construct candidate
# ``workshops/<id>/`` prefixes the foundation key must never match. Drawn
# broadly — including the empty string, slashes, dots, whitespace, and unicode —
# so the prefix-free invariant is exercised against adversarial ids, not just
# well-formed slugs.
_workshop_id = st.text(max_size=48)


@settings(max_examples=200, deadline=None)
@given(workshop_id=_workshop_id)
def test_foundation_state_key_is_fixed_and_prefix_free(workshop_id):
    """The foundation key is exactly the constant and never workshop-prefixed.

    Feature: foundation-idc-service, Property 5: The foundation state key is the
    fixed, prefix-free constant
    Validates: Requirements 4.3, 4.4, 6.4
    """
    key = fsk.foundation_state_key()

    # 1. Byte-exact against the independently-written literal (R4.3) — not the
    #    module constant, so a drift in the constant is caught too.
    assert key == "foundation/terraform.tfstate", (
        f"foundation state key is {key!r}, expected 'foundation/terraform.tfstate'"
    )

    # 2. It carries no workshops/<id>/ prefix for ANY id: it does not even begin
    #    with the fixed workshops/ segment (R4.4).
    assert not key.startswith(fsk.WORKSHOPS_PREFIX), (
        f"foundation key {key!r} unexpectedly begins with {fsk.WORKSHOPS_PREFIX!r}"
    )

    # 3. It is distinct from — and never begins with — the workshop-scoped
    #    prefix built from this arbitrary id (R4.4). This is the concrete form of
    #    the prefix-free invariant over the generated id.
    workshop_prefix = f"{fsk.WORKSHOPS_PREFIX}{workshop_id}/"
    assert not key.startswith(workshop_prefix), (
        f"foundation key {key!r} begins with workshop prefix {workshop_prefix!r}"
    )

    # 4. Its first path segment is 'foundation', never 'workshops' — no leading
    #    key-path noise distinguishes it from the workshop-scoped keys whose
    #    first segment is 'workshops' (R4.4, R6.4).
    first_segment = key.split("/")[0]
    assert first_segment == "foundation", (
        f"foundation key first segment is {first_segment!r}, expected 'foundation'"
    )
    assert first_segment != "workshops"
