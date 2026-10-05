"""Property 3: the rendered backend.hcl body is keyless and identical across stacks.

Feature: foundation-idc-service, Property 3: The rendered backend.hcl body is
keyless and identical across stacks
Validates: Requirements 4.2, 4.5, 4.7

Property 3: *For any* ``(bucket, region, dynamodb_table)`` triple, the backend
bootstrap's rendered ``backend.hcl`` body for the foundation stack (mirrored by
``foundation_backend_body``):

- carries exactly those three values plus ``encrypt = true`` — no more, no less
  (R4.2: the keyless body holds only the shared, non-secret backend values);
- contains no ``key`` line — the per-stack state ``key`` is supplied at
  ``tofu init`` time, never pinned in the file (R4.2, R4.7);
- is byte-identical to the rendered subscription and claim-service bodies — the
  foundation joins ``_backend_hcl_for`` with the SAME ``_backend_hcl_body``, so
  isolation comes from the init-time key, not the file (R4.5).

A regression that added a ``key`` line to the body, dropped ``encrypt``,
introduced a stray setting, or gave the foundation a different body than the
other stacks fails here.

Harness note: ``foundation_backend_body`` lives under ``tests/`` and is
importable via the shared conftest ``sys.path`` shim (``tests/`` is on the
path), mirroring the sibling property tests (e.g.
``test_foundation_tag_transform_property.py``).
"""

from __future__ import annotations

import re

import foundation_backend_body as fbb
from hypothesis import given, settings
from hypothesis import strategies as st

# Matches a ``key = ...`` setting at the start of a line (ignoring leading
# whitespace) — the exact shape the mise residual-key guard greps for
# (``^[[:space:]]*key[[:space:]]*=``). A commented or prose mention of "key" is
# not a setting; the rendered body has no comments, so a plain line match is
# faithful here.
KEY_LINE = re.compile(r"^\s*key\s*=", re.MULTILINE)

# The settings that may appear in the keyless body — nothing else (R4.2).
ALLOWED_SETTINGS = {"bucket", "region", "dynamodb_table", "encrypt"}

# The backend values are AWS identifiers (bucket name, region, lock-table name).
# Draw non-empty printable strings excluding the double-quote and newline so the
# rendered HCL string literals stay well-formed, while still exercising a wide
# range of inputs (unicode, spaces, "=" / "#" characters a naive renderer might
# mishandle). The property is about the render/dispatch shape, not AWS naming
# rules, so the generator stays broad rather than over-constraining to valid
# bucket names.
_backend_value = st.text(
    alphabet=st.characters(blacklist_characters='"\n', min_codepoint=32),
    min_size=1,
    max_size=48,
)


@settings(max_examples=200, deadline=None)
@given(bucket=_backend_value, region=_backend_value, dynamodb_table=_backend_value)
def test_backend_body_is_keyless_and_identical_across_stacks(bucket, region, dynamodb_table):
    """The rendered backend.hcl body is keyless and identical across stacks.

    Feature: foundation-idc-service, Property 3: The rendered backend.hcl body
    is keyless and identical across stacks
    Validates: Requirements 4.2, 4.5, 4.7
    """
    bodies = fbb.backend_hcl_for(bucket, region, dynamodb_table)
    foundation = bodies["foundation"]

    # 1. The foundation body carries no ``key`` line — the state key is supplied
    #    at init time, never in the file (R4.2, R4.7).
    assert KEY_LINE.search(foundation) is None, (
        f"foundation backend body unexpectedly declares a `key =` line:\n{foundation!r}"
    )

    # 2. The body carries exactly the four shared settings — bucket, region,
    #    dynamodb_table, encrypt — and nothing else (R4.2).
    settings_present = {m.group(1) for m in re.finditer(r"(?m)^\s*([A-Za-z_]+)\s*=", foundation)}
    assert settings_present == ALLOWED_SETTINGS, (
        f"foundation body carries settings {settings_present}, expected {ALLOWED_SETTINGS}"
    )

    # 3. The three generated values are spliced in verbatim, plus the literal
    #    ``encrypt = true`` — exactly those three values and no other.
    assert f'bucket         = "{bucket}"' in foundation
    assert f'region         = "{region}"' in foundation
    assert f'dynamodb_table = "{dynamodb_table}"' in foundation
    assert "encrypt        = true" in foundation

    # 4. The foundation body is byte-identical to the subscription and
    #    claim-service bodies — isolation comes from the init-time key, not the
    #    file, so all three stacks share one body (R4.5).
    assert foundation == bodies["subscription"], (
        "foundation backend body differs from the subscription body"
    )
    assert foundation == bodies["claim_service"], (
        "foundation backend body differs from the claim-service body"
    )

    # 5. Explicitly: every stack's body is the same object/value — a single
    #    shared render, not three independent ones.
    distinct_bodies = set(bodies.values())
    assert len(distinct_bodies) == 1, (
        f"expected one shared backend body across stacks, got {len(distinct_bodies)} distinct"
    )
