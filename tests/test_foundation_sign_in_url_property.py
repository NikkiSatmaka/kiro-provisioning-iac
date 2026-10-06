"""Property 2: sign_in_url is the exact portal format of the identity store id.

Feature: foundation-idc-service, Property 2: sign_in_url is the exact portal
format of the identity store id
Validates: Requirements 2.4

Property 2: *For any* identity-store-id string, the HCL interpolation
``"https://${local.identity_store_id}.awsapps.com/start"`` (mirrored by
``foundation_sign_in_url.sign_in_url``) produces the exact AWS access portal
format (R2.4):

- the output equals exactly ``"https://" + id + ".awsapps.com/start"`` — the
  fixed prefix, the id verbatim, and the fixed suffix, with nothing added,
  dropped, or reordered;
- the id is recoverable by stripping the fixed prefix and suffix, so the
  derivation is lossless and the id round-trips.

A regression that changed the scheme, the ``awsapps.com`` host, the ``/start``
path, dropped or mangled the id, or added stray characters fails here.

Harness note: ``foundation_sign_in_url`` lives under ``tests/`` and is
importable via the shared conftest ``sys.path`` shim (``tests/`` is on the
path), mirroring the sibling property tests (e.g.
``test_foundation_provider_selector_property.py``).
"""

from __future__ import annotations

import foundation_sign_in_url as fsiu
from hypothesis import given, settings
from hypothesis import strategies as st

# The identity store id is a Terraform string surfaced from
# ``tolist(data.aws_ssoadmin_instances.this.identity_store_ids)[0]`` (format
# d-xxxxxxxxxx in practice). The interpolation makes no assumption about its
# shape, so draw
# arbitrary strings — including the empty string, whitespace, unicode, and
# strings carrying "https://", ".awsapps.com", "/start", "/", and "." — to prove
# the derivation treats the id as an opaque, verbatim substring.
_identity_store_id = st.text(max_size=48)


@settings(max_examples=200, deadline=None)
@given(identity_store_id=_identity_store_id)
def test_sign_in_url_is_the_exact_portal_format(identity_store_id):
    """sign_in_url is exactly the portal format and the id round-trips.

    Feature: foundation-idc-service, Property 2: sign_in_url is the exact portal
    format of the identity store id
    Validates: Requirements 2.4
    """
    result = fsiu.sign_in_url(identity_store_id)

    # 1. The output is exactly "https://" + id + ".awsapps.com/start" — the
    #    fixed prefix, the id verbatim, and the fixed suffix, nothing else.
    expected = "https://" + identity_store_id + ".awsapps.com/start"
    assert result == expected, (
        f"sign_in_url({identity_store_id!r}) = {result!r}, expected {expected!r}"
    )

    # 2. The fixed prefix and suffix bracket the id exactly as the format
    #    requires.
    assert result.startswith(fsiu.PREFIX)
    assert result.endswith(fsiu.SUFFIX)

    # 3. The id is recoverable by stripping the fixed prefix and suffix — the
    #    derivation is lossless and the id round-trips with no loss or addition.
    recovered = result[len(fsiu.PREFIX) : len(result) - len(fsiu.SUFFIX)]
    assert recovered == identity_store_id, (
        f"id not recoverable from {result!r}: stripped to {recovered!r}, "
        f"expected {identity_store_id!r}"
    )
