"""Property 9: state keys follow the workshop-scoped scheme.

Feature: multi-workshop-provisioning, Property 9: state keys follow the
workshop-scoped scheme
Validates: Requirements 5.2, 5.3, 7.4

Property 9: *For any* valid ``workshop_id``, the subscription and claim-service
state keys SHALL be exactly::

    workshops/<workshop_id>/subscription/terraform.tfstate
    workshops/<workshop_id>/claim-service/terraform.tfstate

differing only in the stack segment and sharing the same ``<workshop_id>``
(R5.2, R5.3, R7.4). Both keys live under the one shared backend bucket, so the
``workshops/<id>/`` prefix is what isolates a workshop's state and the stack
segment is what separates its two stacks.

The checks run against the pure Python mirror of the mise-task derivation
(``workshop_state_keys.state_key``) over Hypothesis-generated valid workshop
ids. For each id the test asserts the two keys are byte-exact against an
independently-constructed expected string, that they are identical except for
the stack segment, that they share the ``workshops/<id>/`` prefix, and that both
end in ``/terraform.tfstate``.

Harness note: ``workshop_state_keys`` lives under ``tests/`` and is importable
via the shared conftest ``sys.path`` shim, mirroring the sibling property tests.
"""

from __future__ import annotations

import re

import workshop_state_keys as sk
from hypothesis import given, settings
from hypothesis import strategies as st

# A valid ``workshop_id`` slug (R5.2 / design slug grammar): 1-63 characters,
# lowercase alphanumeric and hyphens, must begin and end with an alphanumeric,
# and no two consecutive hyphens. The generator below produces only strings in
# this grammar; the slug *validator* itself is the subject of the sibling
# Property 8 test, so here we just need representative valid ids.
_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9]|-(?=[a-z0-9])){0,62}$")

_lower_alnum = st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789")


@st.composite
def _valid_workshop_ids(draw):
    """Generate a valid workshop_id slug matching the grammar.

    Built as alphanumeric segments joined by single hyphens: this guarantees
    begin/end alphanumeric and no consecutive hyphens by construction, then the
    length is clamped to the 1-63 window. A final regex guard keeps the
    generator honest if the construction is ever edited.
    """
    # 1-4 segments, each 1-15 lowercase-alphanumeric chars. The ceiling keeps
    # the joined slug (segments + single-hyphen separators) within the 63-char
    # window without needing to truncate — truncation could otherwise cut right
    # after a separator and leave an invalid trailing hyphen. 4 * 15 + 3 = 63.
    segments = draw(
        st.lists(
            st.text(alphabet=_lower_alnum, min_size=1, max_size=15),
            min_size=1,
            max_size=4,
        )
    )
    slug = "-".join(segments)
    assert _SLUG_RE.match(slug), f"generator produced invalid slug: {slug!r}"
    return slug


@settings(max_examples=200, deadline=None)
@given(workshop_id=_valid_workshop_ids())
def test_state_keys_match_the_workshop_scoped_scheme(workshop_id):
    """Both stack keys are byte-exact and differ only in the stack segment.

    Feature: multi-workshop-provisioning, Property 9: state keys follow the
    workshop-scoped scheme
    Validates: Requirements 5.2, 5.3, 7.4
    """
    sub = sk.state_key(workshop_id, sk.SUBSCRIPTION_STACK)
    claim = sk.state_key(workshop_id, sk.CLAIM_SERVICE_STACK)

    # 1. Byte-exact against independently-constructed expected strings (R5.2,
    #    R5.3) — not re-using the function under test to build the expectation.
    expected_sub = f"workshops/{workshop_id}/subscription/terraform.tfstate"
    expected_claim = f"workshops/{workshop_id}/claim-service/terraform.tfstate"
    assert sub == expected_sub, f"subscription key mismatch: {sub!r}"
    assert claim == expected_claim, f"claim-service key mismatch: {claim!r}"

    # 2. Both end in /terraform.tfstate (R5.2, R5.3).
    assert sub.endswith("/terraform.tfstate")
    assert claim.endswith("/terraform.tfstate")

    # 3. Shared workshop prefix: both keys live under workshops/<id>/ (R7.4).
    prefix = f"workshops/{workshop_id}/"
    assert sub.startswith(prefix)
    assert claim.startswith(prefix)

    # 4. They differ ONLY in the stack segment. Both keys split into exactly
    #    four path components; components 0, 1, and 3 are identical and only
    #    component 2 (the stack) differs (R5.3, R7.4).
    sub_parts = sub.split("/")
    claim_parts = claim.split("/")
    assert len(sub_parts) == 4
    assert len(claim_parts) == 4
    assert sub_parts[0] == claim_parts[0] == "workshops"
    assert sub_parts[1] == claim_parts[1] == workshop_id
    assert sub_parts[3] == claim_parts[3] == "terraform.tfstate"
    assert sub_parts[2] == "subscription"
    assert claim_parts[2] == "claim-service"
    assert sub_parts[2] != claim_parts[2]

    # The two keys as a whole are distinct and share every segment but the
    # stack one — i.e. exactly one differing path component.
    differing = [i for i in range(4) if sub_parts[i] != claim_parts[i]]
    assert differing == [2], (
        f"keys differ in segments {differing}, expected only the stack segment"
    )
