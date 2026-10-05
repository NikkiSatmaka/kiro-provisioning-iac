"""Example test for credentials-renderer backward compatibility.

Feature: idc-region-account-mapping, Task 4.7
Validates: Requirements 2.1, 6.1

A manifest exported *before* this feature carries neither ``kiro_region`` nor
``account_id``. The renderer must still load and render such a manifest without
crashing, falling back to the prior behavior:

* ``kiro_region`` is absent -> ``_load_manifest`` defaults it to the deployment
  ``region``, so the Kiro-sign-in-region header and the "how to sign in"
  instruction both show ``region`` (R2.1 — the sign-in region still renders).
* ``account_id`` is absent -> ``_load_manifest`` defaults it to ``""``, which
  ``_render`` turns into a dash. Both the document-level ``Account ID`` header
  and every per-user ``Account ID`` cell render ``—`` (R6.1).

This is an example test (one concrete pre-change manifest), complementing the
property tests for the new-field behavior. It drives the real public entry
points: ``_load_manifest`` reads from a file on disk (as it does in
production), then ``_render`` produces the Markdown.
"""

from __future__ import annotations

import json

import pytest
from provision_passwords_and_output import _load_manifest, _render


@pytest.fixture()
def pre_change_manifest_path(tmp_path):
    """Write a pre-change manifest (no kiro_region, no account_id) to disk.

    This mirrors the exact shape a manifest had before the region-split and
    account-mapping fields were added: only the historically-required keys
    (``region``, ``identity_store_id``, ``users``, ``sign_in_url``), plus a
    couple of long-standing optional ones. Crucially, no user carries an
    ``account_id`` either, so the per-user column must fall back to a dash.
    """
    manifest = {
        "region": "ap-southeast-1",
        "identity_store_id": "d-1234567890",
        "sign_in_url": "https://d-1234567890.awsapps.com/start",
        "kiro_tier": "free",
        "users": {
            "kiro-user-01": {
                "username": "kiro-user-01",
                "email": "u1@example.com",
            },
            "kiro-user-02": {
                "username": "kiro-user-02",
                "email": None,
            },
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_pre_change_manifest_loads_without_the_new_fields(pre_change_manifest_path):
    """An old manifest loads: new fields are normalized, not required."""
    data = _load_manifest(pre_change_manifest_path)
    # kiro_region falls back to the deployment region; account_id defaults to "".
    assert data["kiro_region"] == "ap-southeast-1"
    assert data["account_id"] == ""


def test_pre_change_manifest_renders_without_crashing(pre_change_manifest_path):
    """Loading + rendering an old manifest produces a non-empty document."""
    data = _load_manifest(pre_change_manifest_path)
    out = _render(data, otps={}, note="")
    assert isinstance(out, str) and out.strip() != ""


def test_sign_in_region_falls_back_to_region(pre_change_manifest_path):
    """With no kiro_region, the sign-in region shown is the deployment region.

    Checks both surfaces (R2.1): the header field and the "how to sign in"
    instruction a participant reads to know which region to enter.
    """
    data = _load_manifest(pre_change_manifest_path)
    out = _render(data, otps={}, note="")

    # Header field presents the (fallback) Kiro sign-in region.
    assert "- **Kiro sign-in region:** `ap-southeast-1`" in out
    # The sign-in instruction tells the participant to enter that same region.
    assert "the Kiro sign-in region `ap-southeast-1`" in out


def test_account_cells_render_dash(pre_change_manifest_path):
    """With no account_id anywhere, every account cell renders a dash (R6.1).

    Covers the document-level header field and each per-user table row.
    """
    data = _load_manifest(pre_change_manifest_path)
    out = _render(data, otps={}, note="")

    # Document-level header account field renders a dash.
    assert "- **Account ID:** `—`" in out

    # Every per-user row's Account ID cell is a dash. The user table rows carry
    # the username in backticks followed by the email cell and the account cell;
    # assert the dash appears in each data row rather than relying on column
    # position. There are two users, so there must be two per-user rows, and the
    # account column in each is "—".
    user_rows = [
        line
        for line in out.splitlines()
        if line.startswith("|") and "`kiro-user-" in line
    ]
    assert len(user_rows) == 2
    for row in user_rows:
        # Split the Markdown row into its cells (drop the leading/trailing "").
        cells = [c.strip() for c in row.split("|")[1:-1]]
        # Columns: # | Username | Email | Account ID | Group(s) | Password/OTP | Status
        account_cell = cells[3]
        assert account_cell == "—", f"expected dash account cell, got {account_cell!r}"
