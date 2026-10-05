"""Property 2: Kiro sign-in region surfaces as KIRO_REGION in the credentials doc.

Feature: idc-region-account-mapping, Property 2: _render sign-in region
Validates: Requirements 1.6, 2.1, 2.2

Property 2: *For any* manifest ``kiro_region`` value, the Markdown that
``_render`` produces presents that value in BOTH places a participant looks for
the region they must enter at Kiro sign-in:

  * the document-level **"Kiro sign-in region"** header field (R2.1), and
  * the **"How to sign in"** instruction step that tells the participant which
    region to type (R1.6, R2.2).

So whatever Kiro sign-in region an operator targets, the generated credentials
document never leaves a participant guessing or showing them the resources
(deployment) region by mistake.

The property drives the *shipped* code path end to end: each example writes a
minimal-but-valid manifest to disk, loads it through the real ``_load_manifest``
(exercising its ``kiro_region`` normalization), and renders it through the real
``_render``. A regression that drops the header field, drops the sign-in-step
mention, or swaps in the deployment ``region`` fails here.

Generator: realistic ``<group>-<direction>-<n>`` AWS-style region codes mixed
with arbitrary opaque tokens — ``_render`` must surface whatever ``kiro_region``
is, verbatim, without interpreting it. The ``region`` (deployment) value is
generated independently and constrained to differ from ``kiro_region`` so an
assertion that finds the value in the document cannot be satisfied by the
deployment region leaking through.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

# Import the renderer module from subscription/scripts/ without installing it as
# a package. Mirrors the additive sys.path shim pattern the repo-root conftest
# uses for tests/ helpers; here we point at the scripts dir that holds the
# module under test.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_RENDERER_PATH = (
    _REPO_ROOT / "subscription" / "scripts" / "provision_passwords_and_output.py"
)
_spec = importlib.util.spec_from_file_location(
    "provision_passwords_and_output", _RENDERER_PATH
)
assert _spec is not None and _spec.loader is not None
_renderer = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("provision_passwords_and_output", _renderer)
_spec.loader.exec_module(_renderer)


# Realistic AWS-style region codes: e.g. "ap-southeast-1", "us-east-1".
_realistic_regions = st.builds(
    lambda group, direction, num: f"{group}-{direction}-{num}",
    st.sampled_from(["us", "eu", "ap", "sa", "ca", "me", "af", "cn"]),
    st.sampled_from(
        ["east", "west", "north", "south", "central", "southeast", "northeast"]
    ),
    st.integers(min_value=1, max_value=9),
)

# Arbitrary opaque tokens: _render must surface kiro_region verbatim without
# interpreting it. Restrict to a printable, non-whitespace alphabet so the value
# round-trips cleanly through JSON (the manifest file) and is a single token we
# can locate unambiguously in the rendered Markdown. Exclude backtick so the
# value cannot be confused with the Markdown code-span delimiters _render adds.
_token_alphabet = st.characters(
    min_codepoint=0x21,
    max_codepoint=0x7E,
    blacklist_characters="`",
)
_opaque_tokens = st.text(alphabet=_token_alphabet, min_size=1, max_size=32)

region_strings = st.one_of(_realistic_regions, _opaque_tokens)


def _write_manifest(tmp_path: Path, *, kiro_region: str, region: str) -> Path:
    """Write a minimal-but-valid manifest and return its path.

    Only the keys ``_load_manifest`` requires are populated, plus ``kiro_region``
    (the value under test). ``users`` is empty so the per-user table is irrelevant
    to this property — we are asserting the document-level header field and the
    sign-in instruction, not the rows.
    """
    import json

    manifest = {
        "region": region,
        "kiro_region": kiro_region,
        "identity_store_id": "d-1234567890",
        "sign_in_url": "https://d-1234567890.awsapps.com/start",
        "users": {},
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


@settings(max_examples=100, deadline=None)
@given(kiro_region=region_strings, region=region_strings)
def test_kiro_region_surfaces_in_header_and_sign_in_step(
    kiro_region, region, tmp_path_factory
):
    """For any kiro_region, _render shows it as the header field AND sign-in step.

    Feature: idc-region-account-mapping, Property 2: _render sign-in region
    Validates: Requirements 1.6, 2.1, 2.2
    """
    # Keep the deployment region distinct from the sign-in region so that finding
    # kiro_region in the document cannot be an accident of the two coinciding.
    if region == kiro_region:
        region = kiro_region + "-x"

    tmp_path = tmp_path_factory.mktemp("manifest")
    manifest_path = _write_manifest(
        tmp_path, kiro_region=kiro_region, region=region
    )
    manifest = _renderer._load_manifest(manifest_path)
    # _load_manifest normalizes/keeps kiro_region; confirm the value we set is the
    # one carried forward (not silently overwritten by the region fallback).
    assert manifest["kiro_region"] == kiro_region

    doc = _renderer._render(manifest, otps={}, note="")

    # (R2.1) The document-level "Kiro sign-in region" header field presents it.
    header_field = f"- **Kiro sign-in region:** `{kiro_region}`"
    assert header_field in doc

    # (R1.6, R2.2) The "How to sign in" instruction step presents it as the region
    # the participant enters — located within the sign-in section specifically.
    assert "## How to sign in" in doc
    sign_in_section = doc.split("## How to sign in", 1)[1].split("## Users", 1)[0]
    sign_in_step = f"the Kiro sign-in region `{kiro_region}`"
    assert sign_in_step in sign_in_section
