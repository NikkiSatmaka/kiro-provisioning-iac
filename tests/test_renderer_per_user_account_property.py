"""Property 6: the per-user Account ID column reflects each user's account.

Feature: idc-region-account-mapping, Property 6: per-user account column
reflects each user's account
Validates: Requirements 6.2, 6.3

Property 6: *For any* set of users each annotated with its own ``account_id``,
the credentials document ``_render`` produces renders, in each user's row, that
specific user's ``account_id`` — not a shared value, not another user's value.
So when users map to different child AWS accounts, the per-user Account ID
column shows their respective values (R6.2), and a user that maps to an account
shows that account in that user's row (R6.3).

The property drives the *real* renderer: each example builds a manifest whose
``users`` map carries hypothesis-chosen, intentionally divergent per-user
``account_id`` values, runs ``_render``, locates the Markdown users table, and
asserts the Account ID cell of each user's row equals that user's
``account_id``. A regression that rendered a single document-level account for
every row, or that read the wrong user's value, fails here.

Harness note
------------
``provision_passwords_and_output`` lives under ``subscription/scripts/`` and is
not an installed package. This module prepends that directory to ``sys.path``
(mirroring the additive shim the claim-service suite uses for its scripts) so
``import provision_passwords_and_output`` resolves. Kept local to this test
rather than in the shared conftest so the env-helper shim there stays focused.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "subscription" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import provision_passwords_and_output as renderer  # noqa: E402
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

# Account IDs are 12-digit AWS account numbers (the Idc_Account_Map validation
# enforces ``^[0-9]{12}$``). Generating full 12-digit strings keeps the values
# in the real input space; drawing them per user with ``unique=True`` guarantees
# the DIVERGENT per-user values the property demands — no two users share an
# account, so a row showing the wrong account is unambiguously detectable.
_account_ids = st.text(alphabet="0123456789", min_size=12, max_size=12)

# Usernames: the manifest ``users`` map is keyed by an opaque key and each entry
# carries a ``username``. The renderer sorts by key and prints ``username`` in
# the row, so usernames only need to round-trip through a single Markdown table
# cell. Restrict to characters that cannot be confused with the table's ``|``
# column separator or break a one-line row, so cell-splitting stays reliable.
_usernames = st.text(
    alphabet=st.characters(
        min_codepoint=0x21,
        max_codepoint=0x7E,
        blacklist_characters="|`",
    ),
    min_size=1,
    max_size=24,
).filter(lambda s: s.strip() != "")


@st.composite
def _users_with_divergent_accounts(draw):
    """A ``users`` map whose entries carry distinct, divergent account_ids.

    Draws a set of unique usernames, then zips each with a unique 12-digit
    account id, so every user maps to a different child account. Returns a
    manifest-shaped ``{key: {username, account_id}}`` map keyed by username
    (the renderer only requires the key be unique and sorts by it).
    """
    usernames = draw(
        st.lists(_usernames, min_size=1, max_size=12, unique=True)
    )
    account_ids = draw(
        st.lists(
            _account_ids,
            min_size=len(usernames),
            max_size=len(usernames),
            unique=True,
        )
    )
    return {
        uname: {"username": uname, "account_id": acct}
        for uname, acct in zip(usernames, account_ids)
    }


def _make_manifest(users: dict) -> dict:
    """A minimal manifest ``_render`` accepts, carrying the drawn users."""
    return {
        "region": "ap-southeast-1",
        "kiro_region": "us-east-1",
        "account_id": "",
        "identity_store_id": "d-1234567890",
        "sign_in_url": "https://d-1234567890.awsapps.com/start",
        "users": users,
        "groups": {},
    }


def _row_cells(line: str) -> list[str]:
    """Split a Markdown table row ``| a | b | ... |`` into its trimmed cells."""
    # A table row starts and ends with a pipe; stripping the outer empties the
    # split produces and trimming each cell yields the logical column values.
    parts = line.split("|")[1:-1]
    return [cell.strip() for cell in parts]


def _user_rows(markdown: str) -> list[list[str]]:
    """Return the cell lists of the users-table data rows (not the header).

    The users table header is ``| # | Username | Email | Account ID | ...``
    followed by a ``|---|...|`` separator; the data rows follow until the first
    non-row line. Each data row's first cell is the 1-based index.
    """
    lines = markdown.splitlines()
    rows: list[list[str]] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("| # | Username |"):
            in_table = True
            continue
        if in_table:
            if stripped.startswith("|---"):
                continue
            if not stripped.startswith("|"):
                break
            rows.append(_row_cells(stripped))
    return rows


# Column index of the "Account ID" cell in a data row, from the header layout
# ``| # | Username | Email | Account ID | Group(s) | Password / OTP | Status |``.
_USERNAME_COL = 1
_ACCOUNT_ID_COL = 3


@settings(max_examples=200, deadline=None)
@given(users=_users_with_divergent_accounts())
def test_each_user_row_shows_that_users_account_id(users):
    """Each rendered user row shows that specific user's account_id.

    Feature: idc-region-account-mapping, Property 6: per-user account column
    reflects each user's account
    Validates: Requirements 6.2, 6.3
    """
    manifest = _make_manifest(users)

    rendered = renderer._render(manifest, otps={}, note="")

    rows = _user_rows(rendered)

    # Every drawn user must appear as exactly one data row (sanity: the table
    # neither drops nor duplicates users), so the per-row account assertion
    # covers the whole set.
    assert len(rows) == len(users)

    # The renderer prints the username wrapped in backticks (`uname`); strip
    # them to recover the key into the drawn users map.
    for row in rows:
        rendered_username = row[_USERNAME_COL].strip("`")
        rendered_account = row[_ACCOUNT_ID_COL].strip("`")

        assert rendered_username in users, (
            f"row for unknown username {rendered_username!r}"
        )
        expected_account = users[rendered_username]["account_id"]

        # The Account ID cell of THIS user's row equals THIS user's account_id
        # (R6.3) — and because the drawn accounts are all distinct, this also
        # proves divergent users show their respective values rather than a
        # shared document-level account (R6.2).
        assert rendered_account == expected_account, (
            f"user {rendered_username!r}: Account ID cell {rendered_account!r} "
            f"!= its account_id {expected_account!r}"
        )
