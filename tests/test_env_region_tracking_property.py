"""Property 1: AWS_REGION tracks IDC_REGION (region-split env assembly).

Feature: idc-region-account-mapping, Property 1: AWS_REGION tracks IDC_REGION
Validates: Requirements 1.3

Property 1: *For any* region string supplied as ``IDC_REGION``, the environment
the task layer assembles resolves ``AWS_REGION`` to that same value, and
``AWS_DEFAULT_REGION`` mirrors ``AWS_REGION``. So whatever region an operator
targets for provisioning, every AWS CLI / SDK / OpenTofu call driven by a
``mise run`` task points at it, and the two region variables never diverge.

The property drives the *real* assembler: each example writes the supplied
``IDC_REGION`` into the child-process environment and resolves it through the
repo's actual ``mise.toml`` ``[env]`` region templates (see
``_env_assembler.resolve_env``). It therefore tests the shipped tracking
relationship, not a re-implementation — a regression that pins ``AWS_REGION`` to
a literal, or drops the ``AWS_DEFAULT_REGION`` mirror, fails here.

Generator: realistic ``<group>-<direction>-<n>`` AWS-style region codes mixed
with arbitrary non-empty tokens, so the property holds for the regions an
operator would actually use *and* for opaque strings (``AWS_REGION`` tracks
whatever ``IDC_REGION`` is, without interpreting it). Values are constrained to
survive the TOML/env/subprocess round-trip: no whitespace, control characters,
surrogates, quotes, ``$``, or template braces.
"""

from __future__ import annotations

import pytest
from _env_assembler import mise_available, resolve_env
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.skipif(
    not mise_available(), reason="mise binary not on PATH"
)

# Realistic AWS-style region codes: e.g. "ap-southeast-1", "eu-central-2".
_realistic_regions = st.builds(
    lambda group, direction, num: f"{group}-{direction}-{num}",
    st.sampled_from(["us", "eu", "ap", "sa", "ca", "me", "af", "cn"]),
    st.sampled_from(
        ["east", "west", "north", "south", "central", "southeast", "northeast"]
    ),
    st.integers(min_value=1, max_value=9),
)

# Arbitrary opaque tokens: AWS_REGION must track IDC_REGION verbatim without
# interpreting it. Restrict the alphabet to characters that round-trip cleanly
# through the inline-TOML env block, the process environment, and JSON:
#   - no whitespace (env values here are single unquoted tokens),
#   - no control chars / surrogates (not valid in a process env / JSON),
#   - no '"' (would need TOML escaping), no '$' or '{'/'}' (template sigils).
_token_alphabet = st.characters(
    min_codepoint=0x21,
    max_codepoint=0x7E,
    blacklist_characters='"$`{}\\',
)
_opaque_tokens = st.text(alphabet=_token_alphabet, min_size=1, max_size=32)

region_strings = st.one_of(_realistic_regions, _opaque_tokens)


@settings(
    max_examples=100,
    deadline=None,  # each example shells out to `mise`; wall-clock varies
    suppress_health_check=[HealthCheck.too_slow],
)
@given(idc_region=region_strings)
def test_aws_region_tracks_idc_region(idc_region):
    """For any IDC_REGION, AWS_REGION equals it and AWS_DEFAULT_REGION mirrors.

    Feature: idc-region-account-mapping, Property 1: AWS_REGION tracks IDC_REGION
    Validates: Requirements 1.3
    """
    env = resolve_env(overrides={"IDC_REGION": idc_region})

    # IDC_REGION is carried through unchanged...
    assert env["IDC_REGION"] == idc_region
    # ...AWS_REGION tracks it exactly...
    assert env["AWS_REGION"] == idc_region
    # ...and AWS_DEFAULT_REGION mirrors AWS_REGION (so the two never diverge).
    assert env["AWS_DEFAULT_REGION"] == env["AWS_REGION"]
