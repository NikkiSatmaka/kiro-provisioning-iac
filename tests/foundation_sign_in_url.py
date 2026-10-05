"""Pure Python mirror of the Foundation IdC sign_in_url derivation.

Feature: foundation-idc-service

The ``sign_in_url`` output in ``foundation/terraform/outputs.tf`` derives the
default AWS access portal URL directly from the identity store id with a single
HCL string interpolation::

    value = "https://${local.identity_store_id}.awsapps.com/start"

That is: a fixed ``"https://"`` prefix, the identity store id verbatim, and a
fixed ``".awsapps.com/start"`` suffix — the exact portal format
``https://<identity-store-id>.awsapps.com/start`` (R2.4). This is the same
derivation the subscription stack's ``outputs.tf`` uses.

``sign_in_url`` is a *faithful* mirror of that interpolation so the property
test can exercise the exact-format rule deterministically, offline, over many
Hypothesis-generated identity-store-id strings — no ``tofu`` process, no AWS.
Keep this a faithful mirror: when the interpolation in ``outputs.tf`` changes,
this mirror changes with it.

The fixed prefix/suffix are exposed as module constants so the sibling property
test can assert the id is recoverable by stripping them, rather than
re-hardcoding the literals.

This module lives under ``tests/`` in its own file so sibling test tasks writing
in the same wave never collide on it, and is importable via the shared conftest
``sys.path`` shim (``tests/`` is on the path).
"""

from __future__ import annotations

#: Fixed URL prefix in the HCL interpolation (the literal before the id).
PREFIX = "https://"

#: Fixed URL suffix in the HCL interpolation (the literal after the id).
SUFFIX = ".awsapps.com/start"


def sign_in_url(identity_store_id: str) -> str:
    """Mirror ``"https://${local.identity_store_id}.awsapps.com/start"``.

    Return the fixed ``"https://"`` prefix, the identity store id verbatim, and
    the fixed ``".awsapps.com/start"`` suffix, concatenated — the exact portal
    format. Faithful to the HCL string interpolation in ``outputs.tf``.
    """
    return f"{PREFIX}{identity_store_id}{SUFFIX}"
