"""Property 1: the AWSCC tag transform is a faithful bijection with default_tags.

Feature: foundation-idc-service, Property 1: AWSCC tag transform is a faithful
bijection with default_tags
Validates: Requirements 1.9

Property 1: *For any* ``default_tags`` ``map(string)``, the HCL transform
``[for k, v in var.default_tags : { key = k, value = v }]`` (mirrored by
``foundation_tag_transform.tag_transform``) produces the AWSCC list-of-objects
tag shape that is a *faithful bijection* with the input map (R1.9):

- the output list length equals the map size — exactly one object per entry, no
  entry dropped and no object duplicated or invented;
- every object is exactly ``{ key, value }`` — no stray fields;
- the set of ``(key, value)`` pairs in the output equals the map's entries
  exactly, so the map is recoverable from the list with no loss and no addition.

A regression that dropped an entry, emitted a duplicate, added an extra object,
mangled a key or value, or added a stray field to an object fails here.

Harness note: ``foundation_tag_transform`` lives under ``tests/`` and is
importable via the shared conftest ``sys.path`` shim (``tests/`` is on the
path), mirroring the sibling property tests (e.g.
``test_flatten_shapes_property.py``).
"""

from __future__ import annotations

import foundation_tag_transform as ftt
from hypothesis import given, settings
from hypothesis import strategies as st

# ``default_tags`` is a Terraform ``map(string)``: string keys to string values.
# Draw arbitrary (possibly empty) maps of unicode strings so the property
# exercises the empty map, single-entry maps, and larger maps, with keys/values
# spanning empty strings, whitespace, unicode, and the "=" / ":" characters a
# naive transform might choke on. Map keys are unique by dict construction,
# mirroring HCL map semantics.
_tag_text = st.text(max_size=24)
_default_tags = st.dictionaries(keys=_tag_text, values=_tag_text, max_size=12)


@settings(max_examples=200, deadline=None)
@given(default_tags=_default_tags)
def test_tag_transform_is_a_faithful_bijection(default_tags):
    """The AWSCC tag transform is a faithful bijection with ``default_tags``.

    Feature: foundation-idc-service, Property 1: AWSCC tag transform is a
    faithful bijection with default_tags
    Validates: Requirements 1.9
    """
    result = ftt.tag_transform(default_tags)

    # 1. The output is a list, one object per map entry — length equals map size
    #    (no entry dropped, no object invented or duplicated).
    assert isinstance(result, list)
    assert len(result) == len(default_tags), (
        f"transform of {default_tags!r} has {len(result)} objects, "
        f"expected {len(default_tags)}"
    )

    # 2. Every emitted object is exactly { key, value } — no stray fields, no
    #    missing field.
    for obj in result:
        assert set(obj.keys()) == {"key", "value"}, (
            f"tag object {obj!r} has fields {sorted(obj.keys())}, "
            f"expected exactly 'key' and 'value'"
        )

    # 3. The set of (key, value) pairs in the output equals the map's entries
    #    exactly — faithful (lossless) and injective (no extra pair). Using a set
    #    comparison catches a dropped entry, an invented pair, a mangled
    #    key/value, and (combined with the length check) a duplicate.
    output_pairs = {(obj["key"], obj["value"]) for obj in result}
    assert output_pairs == set(default_tags.items()), (
        f"transform of {default_tags!r} yielded pairs {output_pairs!r}, "
        f"expected {set(default_tags.items())!r}"
    )

    # 4. Bijection, explicitly: because map keys are unique, the length check
    #    plus the set equality means the map is fully recoverable from the list.
    recovered = {obj["key"]: obj["value"] for obj in result}
    assert recovered == default_tags, (
        f"map not recoverable from transform output: got {recovered!r}, "
        f"expected {default_tags!r}"
    )
