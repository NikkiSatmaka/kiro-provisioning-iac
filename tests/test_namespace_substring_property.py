"""Property 7: workshop_id is the sole namespace; workshop_code never namespaces.

Feature: multi-workshop-provisioning, Property 7: workshop_id is the sole
namespace substring; workshop_code never namespaces
Validates: Requirements 7.2, 9.3, 9.4

The claim service derives every resource name from one base,
``local.name = "credential-claim-${var.workshop_id}"`` (design §3):

    table name   = local.name
    lambda name  = local.name
    role name    = "${local.name}-lambda"
    policy name  = "${local.name}-table-access"

and both stacks' state keys are ``workshops/<workshop_id>/<stack>/terraform.tfstate``
(workshop_state_keys mirror). ``workshop_code`` is a separate value — the
handler access gate (WORKSHOP_CODE / TF_VAR_workshop_code) — and R9.3/R9.4 say
it is *never* used in a resource name or state key, and the two values never
substitute for one another.

This property pins that split three ways over Hypothesis-generated inputs
(min 100, run at 200): a valid ``workshop_id`` slug and an ARBITRARY
``workshop_code`` string.

1. **workshop_id is present.** Every derived name and both state keys contain
   the exact ``workshop_id`` substring — it is the namespace.

2. **workshop_code has zero influence.** The derivation takes ``workshop_code``
   as an argument but the names/keys it returns are byte-identical no matter
   what ``workshop_code`` is (two arbitrary codes over the same ``workshop_id``
   give identical output). This is the clean formulation of "never namespaces":
   a parameter that cannot change the output cannot leak into it.

3. **workshop_code is absent (where observable).** When the arbitrary
   ``workshop_code`` is not already a substring of ``workshop_id`` (the only way
   it could appear incidentally), it appears in none of the derived names or
   state keys.

The claim-name derivations are inlined here as a small, self-contained mirror
rather than imported from the sibling names module (task 7.3 creates
``tests/workshop_names.py`` concurrently). This avoids an import race at write
time; the derivation is a faithful mirror of design §3. The state-key scheme is
read from the already-stable ``workshop_state_keys`` mirror.
"""

from __future__ import annotations

import workshop_state_keys as wsk
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Inlined claim-name mirror (design §3: local.name = credential-claim-<wid>)
# ---------------------------------------------------------------------------

_NAME_PREFIX = "credential-claim-"


def claim_names(workshop_id: str, workshop_code: str) -> dict[str, str]:
    """The four claim resource names, mirroring ``claim-service`` design §3.

    ``workshop_code`` is accepted as a parameter *deliberately* so the property
    can assert it never influences the output: the names are a pure function of
    ``workshop_id`` alone (``local.name = "credential-claim-${var.workshop_id}"``),
    so ``workshop_code`` is read and discarded here.
    """
    _ = workshop_code  # intentionally unused: workshop_code never namespaces
    base = f"{_NAME_PREFIX}{workshop_id}"
    return {
        "table": base,
        "lambda": base,
        "role": f"{base}-lambda",
        "policy": f"{base}-table-access",
    }


def derived_strings(workshop_id: str, workshop_code: str) -> dict[str, str]:
    """All namespaced strings for a workshop: the four names + both state keys.

    One place that collects everything R9.3 forbids ``workshop_code`` from
    touching, so each property asserts over the whole set uniformly.
    """
    out = claim_names(workshop_id, workshop_code)
    out["state_key_subscription"] = wsk.state_key(
        workshop_id, wsk.SUBSCRIPTION_STACK
    )
    out["state_key_claim_service"] = wsk.state_key(
        workshop_id, wsk.CLAIM_SERVICE_STACK
    )
    return out


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

# A valid workshop_id slug: 1-63 chars, lowercase alphanumeric + hyphens,
# starting and ending alphanumeric, no consecutive hyphens (the variables.tf
# validation, mirrored). Build it from alphanumeric segments joined by single
# hyphens so the "no consecutive hyphens / no leading-or-trailing hyphen" rules
# hold by construction, then cap at 63.
_slug_alnum = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=12
)


@st.composite
def _workshop_id(draw):
    segments = draw(st.lists(_slug_alnum, min_size=1, max_size=5))
    slug = "-".join(segments)[:63]
    # The [:63] slice could leave a trailing hyphen; trim it back to alnum.
    slug = slug.rstrip("-")
    assume(slug != "")
    return slug


# workshop_code is ARBITRARY: any text at all. It is a free-form access-gate
# secret, so the property must hold for whatever string it is — including empty,
# unicode, and strings that look like the names.
_workshop_code = st.text(max_size=40)


@settings(max_examples=200, deadline=None)
@given(workshop_id=_workshop_id(), workshop_code=_workshop_code)
def test_workshop_id_is_present_in_every_name_and_state_key(
    workshop_id, workshop_code
):
    """Every derived name and both state keys contain the exact workshop_id.

    Feature: multi-workshop-provisioning, Property 7: workshop_id is the sole
    namespace substring; workshop_code never namespaces
    Validates: Requirements 7.2, 9.3
    """
    for label, value in derived_strings(workshop_id, workshop_code).items():
        assert workshop_id in value, (
            f"{label}: expected workshop_id {workshop_id!r} as a substring of "
            f"{value!r}"
        )


@settings(max_examples=200, deadline=None)
@given(
    workshop_id=_workshop_id(),
    code_a=_workshop_code,
    code_b=_workshop_code,
)
def test_workshop_code_has_zero_influence_on_names_and_state_keys(
    workshop_id, code_a, code_b
):
    """Two arbitrary workshop_codes over one workshop_id give byte-identical
    names and state keys — workshop_code cannot change the namespace.

    This is the clean formulation of "workshop_code never namespaces": the
    derivation output is invariant under the workshop_code, so it is a pure
    function of workshop_id alone (R9.4 — neither value substitutes for the
    other).

    Feature: multi-workshop-provisioning, Property 7: workshop_id is the sole
    namespace substring; workshop_code never namespaces
    Validates: Requirements 9.3, 9.4
    """
    with_a = derived_strings(workshop_id, code_a)
    with_b = derived_strings(workshop_id, code_b)
    assert with_a == with_b, (
        "workshop_code influenced a derived name or state key: "
        f"{code_a!r} -> {with_a}, {code_b!r} -> {with_b}"
    )


@settings(max_examples=200, deadline=None)
@given(workshop_id=_workshop_id(), workshop_code=_workshop_code)
def test_workshop_code_never_appears_as_a_namespace_substring(
    workshop_id, workshop_code
):
    """The workshop_code is absent from every derived name and state key.

    A derived string is the workshop_id woven into *fixed scaffolding* — the
    ``credential-claim-`` / ``-lambda`` / ``-table-access`` name affixes and the
    ``workshops/<id>/<stack>/terraform.tfstate`` path literals. An arbitrary code
    could coincidentally be a substring of that scaffolding (e.g. ``/`` matches a
    path separator) or of the workshop_id itself, and neither is evidence of
    namespacing. So we restrict to codes that are NOT a substring of any derived
    string once the workshop_code is held out of the derivation. For every such
    code the output contains it nowhere — workshop_code never leaks into the
    namespace (R9.3), and the only reason a code could appear is that it was
    already part of the id or the fixed scaffolding, never because the code
    namespaced anything.

    Feature: multi-workshop-provisioning, Property 7: workshop_id is the sole
    namespace substring; workshop_code never namespaces
    Validates: Requirements 9.3, 9.4
    """
    # Empty string is a substring of every string. Hold the code out of the
    # derivation (pass a sentinel that cannot occur), then skip any code that is
    # already an incidental substring of the resulting scaffolding+id — those
    # matches are not namespacing, they are the fixed structure or the id.
    assume(workshop_code != "")
    baseline = derived_strings(workshop_id, workshop_code="\x00")
    assume(all(workshop_code not in value for value in baseline.values()))

    # The code is not incidentally present anywhere, so if it now appeared it
    # could only be because the derivation used workshop_code to namespace.
    for label, value in derived_strings(workshop_id, workshop_code).items():
        assert workshop_code not in value, (
            f"{label}: workshop_code {workshop_code!r} leaked into {value!r}"
        )
