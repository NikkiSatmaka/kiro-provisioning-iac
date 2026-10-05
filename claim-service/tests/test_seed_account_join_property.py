"""Property test for the seed account-join: each CRED# item carries its IdC account.

Feature: idc-region-account-mapping, Property 4
Property 4: Each user record carries its IdC's account ID
Validates: Requirements 5.3

Requirement 5.3 — "WHEN a user maps to a specific IdC, THE Provisioning_Manifest
SHALL associate that user with the Account_Id of that IdC." The seed script
honours that association on the write path: ``load_manifest`` builds a
``username -> account_id`` lookup from the manifest ``users`` map, and ``seed``
resolves each valid row's account via that lookup (falling back to the
document-level ``account_id``, then ``""``) before ``credential_item`` stamps it
onto the ``CRED#`` item.

For any set of users each annotated with an ``account_id`` plus a per-user OTP,
this property asserts that:

  * the ``username -> account_id`` lookup ``load_manifest`` returns matches each
    user's manifest ``account_id`` exactly, and
  * the ``CRED#`` item produced for that user (resolving the account the same
    way ``seed`` does: lookup first, then document default, then ``""``) carries
    that user's account ID.

Users are generated with distinct usernames and divergent per-user account IDs
so the join cannot pass by coincidence (e.g. a single shared account). The
manifest is written to a temp file and read back through ``load_manifest`` so the
real lookup-building code (not a reimplementation) is exercised.
"""

from __future__ import annotations

import json
import pathlib

from hypothesis import given, settings
from hypothesis import strategies as st
from seed_claim_pool import SeedRow, credential_item, load_manifest

# A 12-digit AWS account ID — the shape idc_account_map validation enforces.
account_id = st.text(alphabet="0123456789", min_size=12, max_size=12)

# A username that is non-empty after .strip() (what the seed treats as present),
# and that does not collide across users (unique_by below keys on the trimmed
# form, which is also what load_manifest keys the lookup by).
username = st.text(min_size=1, max_size=20).filter(lambda s: s.strip() != "")

# One user as it appears in the manifest ``users`` map value.
user_entry = st.fixed_dictionaries(
    {
        "username": username,
        "account_id": account_id,
        "otp": st.text(min_size=1, max_size=12).filter(lambda s: s.strip() != ""),
    }
)

# A set of users with distinct trimmed usernames (the manifest users map and the
# OTP CSV are both keyed by username, so collisions are not a meaningful input).
users = st.lists(
    user_entry,
    min_size=1,
    max_size=25,
    unique_by=lambda u: u["username"].strip(),
)

# Non-sign-in-region manifest fields the loader also requires to be present.
SIGN_IN_URL = st.text(min_size=1, max_size=80).filter(lambda s: s.strip() != "")
REGION = st.text(min_size=1, max_size=20).filter(lambda s: s.strip() != "")
# Document-level default account; may be empty (pre-change) or a 12-digit id.
DOC_ACCOUNT = st.one_of(st.just(""), account_id)


def _write_manifest(
    tmp_path: pathlib.Path,
    sign_in_url: str,
    region: str,
    doc_account: str,
    user_list: list[dict[str, str]],
) -> pathlib.Path:
    """Write a provisioning manifest with a map-keyed ``users`` block."""
    manifest = {
        "sign_in_url": sign_in_url,
        "region": region,
        "account_id": doc_account,
        "users": {
            # Map-keyed by a padded sequence, mirroring the real manifest shape;
            # the lookup keys off each entry's ``username``, not this key.
            f"{idx:03d}": {
                "username": u["username"],
                "account_id": u["account_id"],
            }
            for idx, u in enumerate(user_list, start=1)
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


@settings(max_examples=200)
@given(
    user_list=users,
    sign_in_url=SIGN_IN_URL,
    region=REGION,
    doc_account=DOC_ACCOUNT,
)
def test_each_cred_item_carries_its_users_account_id(
    tmp_path_factory, user_list, sign_in_url, region, doc_account
):
    """The lookup and each CRED# item carry the user's IdC account_id."""
    tmp_path = tmp_path_factory.mktemp("manifest")
    manifest_path = _write_manifest(
        tmp_path, sign_in_url, region, doc_account, user_list
    )

    loaded_url, loaded_region, loaded_account, lookup = load_manifest(
        manifest_path
    )

    # Non-account fields round-trip (the loader trims surrounding whitespace).
    assert loaded_url == sign_in_url.strip()
    assert loaded_region == region.strip()
    assert loaded_account == doc_account.strip()

    for u in user_list:
        uname = u["username"].strip()
        expected_account = u["account_id"].strip()

        # The account-join lookup associates this user with its IdC account.
        assert lookup[uname] == expected_account

        # seed() resolves per-user via the lookup, falling back to the
        # document-level account then "". With a present per-user account the
        # lookup always wins; replicate that resolution and assert the stamp.
        resolved = lookup.get(uname, loaded_account)
        item = credential_item(
            SeedRow(username=uname, otp=u["otp"].strip()),
            loaded_url,
            loaded_region,
            resolved,
        )

        assert resolved == expected_account
        assert item["account_id"] == expected_account
        assert item["PK"] == f"CRED#{uname}"
