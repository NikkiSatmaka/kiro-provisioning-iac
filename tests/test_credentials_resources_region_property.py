"""Property 3: Resource region surfaces as the deployment region in the doc.

Feature: idc-region-account-mapping, Property 3: _render resources region
Validates: Requirements 2.3

Property 3: *For any* manifest ``region`` value, the Markdown that ``_render``
produces presents that value as the resource-provisioning region field — the
document-level **"Region code (resources)"** header — and keeps it distinct from
the **"Kiro sign-in region"** field. So whatever region an operator deploys AWS
resources into, the credentials document reports *that* region as the resources
region, and never conflates it with the (possibly different) region a
participant types at Kiro sign-in.

The property drives the *shipped* code path end to end: each example writes a
minimal-but-valid manifest to disk, loads it through the real ``_load_manifest``,
and renders it through the real ``_render``. A regression that drops the
resources-region header, mislabels it, or swaps in ``kiro_region`` fails here.

Generator: realistic ``<group>-<direction>-<n>`` AWS-style region codes mixed
with arbitrary opaque tokens — ``_render`` must surface whatever ``region`` is,
verbatim, without interpreting it. ``kiro_region`` is generated independently
and constrained to differ from ``region`` so that (a) "distinct from the Kiro
sign-in region" is genuinely exercised and (b) an assertion that finds ``region``
in the resources field cannot be satisfied by the sign-in region coinciding.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

# Import the renderer module from subscription/scripts/ without installing it as
# a package. Mirrors the additive sys.path shim pattern the repo-root conftest
# uses for tests/ helpers; here we load the module file directly so the test is
# self-contained even if run as a bare file.
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

# Arbitrary opaque tokens: _render must surface region verbatim without
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


def _write_manifest(tmp_path: Path, *, region: str, kiro_region: str) -> Path:
    """Write a minimal-but-valid manifest and return its path.

    Only the keys ``_load_manifest`` requires are populated, plus ``kiro_region``
    (so the sign-in region is independent of the deployment ``region`` under
    test). ``users`` is empty: this property asserts the document-level
    resources-region header, not the per-user rows.
    """
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
@given(region=region_strings, kiro_region=region_strings)
def test_resource_region_surfaces_as_deployment_region(
    region, kiro_region, tmp_path_factory
):
    """For any region, _render shows it as the resources field, distinct from sign-in.

    Feature: idc-region-account-mapping, Property 3: _render resources region
    Validates: Requirements 2.3
    """
    # Keep the sign-in region distinct from the deployment region so that finding
    # `region` in the resources field cannot be an accident of the two coinciding,
    # and so the "distinct from the Kiro sign-in region" clause is exercised.
    if kiro_region == region:
        kiro_region = region + "-x"

    tmp_path = tmp_path_factory.mktemp("manifest")
    manifest_path = _write_manifest(
        tmp_path, region=region, kiro_region=kiro_region
    )
    manifest = _renderer._load_manifest(manifest_path)
    # _load_manifest keeps the deployment region verbatim (it only *fills in*
    # kiro_region when absent); confirm the value we set is carried forward.
    assert manifest["region"] == region

    doc = _renderer._render(manifest, otps={}, note="")

    # (R2.3) The document-level "Region code (resources)" header presents `region`.
    resources_field = f"- **Region code (resources):** `{region}`"
    assert resources_field in doc

    # The resources region is distinct from the Kiro sign-in region: the sign-in
    # field carries kiro_region (the independently generated, differing value),
    # not the deployment region.
    sign_in_field = f"- **Kiro sign-in region:** `{kiro_region}`"
    assert sign_in_field in doc
    assert resources_field != sign_in_field
