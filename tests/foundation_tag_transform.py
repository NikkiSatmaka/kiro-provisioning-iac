"""Pure Python mirror of the Foundation IdC AWSCC tag transform.

Feature: foundation-idc-service

The ``awscc_sso_instance.this`` resource in
``foundation/terraform/identity_center.tf`` sets its tags with the AWS Cloud
Control list-of-objects shape::

    tags = [for k, v in var.default_tags : { key = k, value = v }]

AWSCC (unlike the ``aws`` provider's ``default_tags`` map shape) wants tags as a
*list of objects*, each ``{ key = ..., value = ... }``. This module is a *pure*
Python re-implementation of exactly that HCL ``for`` expression so the property
test can exercise the transform deterministically, offline, over many
Hypothesis-generated ``map(string)`` inputs — no ``tofu`` process, no AWS.

Keep this a faithful mirror of the HCL ``for`` expression: when the tag shape in
``identity_center.tf`` changes, this mirror changes with it. The sibling
property test reads from here rather than re-deriving the transform.

HCL semantics mirrored:

- A ``for k, v in <map>`` comprehension iterates the map's entries once each, so
  the output list has exactly one object per map entry (length == map size).
- Each emitted object is exactly ``{ key = k, value = v }`` — no extra fields.
- ``map(string)`` keys are unique by construction, so the output objects are a
  faithful, lossless (bijective) re-encoding of the map entries.
"""

from __future__ import annotations


def tag_transform(default_tags: dict[str, str]) -> list[dict[str, str]]:
    """Mirror ``[for k, v in var.default_tags : { key = k, value = v }]``.

    Takes the ``default_tags`` ``map(string)`` and returns the AWSCC
    list-of-objects tag shape: one ``{"key": k, "value": v}`` object per map
    entry, in iteration order, with no extra objects and no extra fields.
    """
    return [{"key": k, "value": v} for k, v in default_tags.items()]
