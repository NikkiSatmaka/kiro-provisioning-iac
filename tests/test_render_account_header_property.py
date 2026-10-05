"""Property 5: Account ID appears as a document-level header field.

Feature: idc-region-account-mapping, Property 5: Account ID appears as a
document-level header field
Validates: Requirements 6.1

Property 5: *For any* manifest carrying an ``account_id`` value, the rendered
credentials document presents that value as a *document-level header field* —
i.e. in the top-of-document metadata block (``- **Account ID:** `<value>` ``),
above the per-user table — so an operator reading the credentials file sees, at
a glance, which AWS account the whole document belongs to.

This drives the *real* renderer: each example builds a minimal-but-valid
provisioning manifest with a hypothesis-chosen ``account_id`` and invokes
``provision_passwords_and_output._render`` directly, then asserts on the Markdown
it produces. A regression that drops the header field, moves it below the table,
or mislabels it fails here.

Generator notes
---------------
``account_id`` ranges over:

  * realistic non-empty 12-digit AWS account ids (the production shape), and
  * the empty string — the documented "absent" case the renderer maps to the
    em dash ``"—"`` placeholder (``account_id or "—"`` in ``_render``).

So the property pins both the happy path (a real account id is surfaced
verbatim) and the empty-manifest fallback (the header still renders, as a dash).
The expected *displayed* value is therefore ``account_id or "—"`` — exactly the
renderer's own rule — which keeps this a property over the contract (the value
appears as a header field) rather than a copy of the implementation string.
"""

from __future__ import annotations

import provision_passwords_and_output as renderer
from hypothesis import given, settings
from hypothesis import strategies as st

# Realistic AWS account ids are exactly 12 digits. Generate the full 12-digit
# space (leading zeros allowed — account ids are opaque digit strings, not
# numbers) so the property holds for any valid id, not just a sampled few.
_twelve_digit_ids = st.text(alphabet="0123456789", min_size=12, max_size=12)

# The input space for Property 5: a real 12-digit id, OR the empty string (the
# documented "absent" case the renderer renders as the em-dash placeholder).
account_ids = st.one_of(_twelve_digit_ids, st.just(""))


def _manifest(account_id: str) -> dict:
    """A minimal manifest ``_render`` accepts, carrying the drawn account_id.

    ``_render`` requires ``region``, ``identity_store_id``, ``users`` and
    ``sign_in_url``; everything else it reads defensively via ``.get``. We keep
    the users map empty so this property isolates the *document-level* header
    field from the per-user ``Account ID`` column (Property 6 covers the latter).
    """
    return {
        "region": "ap-southeast-1",
        "kiro_region": "us-east-1",
        "account_id": account_id,
        "identity_store_id": "d-1234567890",
        "sign_in_url": "https://d-1234567890.awsapps.com/start",
        "users": {},
    }


def _header_block(rendered: str) -> str:
    """The document-level metadata block: everything above the Users table.

    The header fields live between the document title and the ``## Users``
    section; splitting there lets us assert the Account ID field is a
    *document-level* header, not a cell in the per-user table that follows.
    """
    marker = "## Users"
    idx = rendered.find(marker)
    return rendered if idx == -1 else rendered[:idx]


@settings(max_examples=200, deadline=None)
@given(account_id=account_ids)
def test_account_id_rendered_as_document_level_header(account_id):
    """For any manifest account_id, _render surfaces it as a header field.

    Feature: idc-region-account-mapping, Property 5: Account ID appears as a
    document-level header field
    Validates: Requirements 6.1
    """
    rendered = renderer._render(_manifest(account_id), otps={}, note="")

    # The renderer's own contract for the displayed value: a real id verbatim,
    # or the em-dash placeholder when absent (account_id or "—").
    displayed = account_id or "—"
    expected_line = f"- **Account ID:** `{displayed}`"

    header = _header_block(rendered)

    # The Account ID header field is present...
    assert expected_line in header, (
        "expected a document-level Account ID header field "
        f"{expected_line!r} in the header block, got:\n{header}"
    )
    # ...as a document-level field, i.e. above the per-user table (not only in
    # the Users section that follows).
    assert "## Users" in rendered
    assert rendered.index(expected_line) < rendered.index("## Users")
