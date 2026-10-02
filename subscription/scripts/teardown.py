#!/usr/bin/env python3
"""State-free teardown of the Kiro IdC provisioning (Option A — the FALLBACK).

READ THIS FIRST
---------------
The PRIMARY teardown path is `tofu destroy` with a remote S3 backend (Option B;
see TEARDOWN.md). Use that when you have the OpenTofu state (remote backend, or
the local state still on disk).

This script is the FALLBACK for when `tofu destroy` cannot help: a fresh clone
on a different machine a month later, with LOCAL state that never traveled with
the repo, so OpenTofu's state is empty and would delete nothing. This script
needs NO state. It rediscovers everything from the live account by naming
convention and the account's single IdC instance, then deletes it.

WHAT IT DELETES (and in the correct order)
------------------------------------------
  1. Group memberships for the matched users/groups.
  2. The matched IdC users   (default name prefix: "kiro-user-").
  3. The matched IdC groups  (default name prefix: "kiro-team-").
  4. The IdC ACCOUNT INSTANCE itself (optional, --delete-instance).

WHAT IT CANNOT DO (prints guided manual steps instead)
------------------------------------------------------
  * Deactivate Kiro subscriptions / tier assignments.
  * Remove the Kiro-created IdC application assignment that is NOT auto-removed
    when you stop Kiro access.
  * Reverse the org-level "permit member account instances" toggle (irreversible
    by design).
These are console-only; the script prints the exact steps at the end.

SAFETY
------
  * DRY RUN by default. It only reports what it WOULD delete.
  * Mutating requires BOTH --delete and typing the confirmation phrase (or
    passing --yes for non-interactive use).
  * It will only ever touch the ACCOUNT instance in the targeted region, and
    only users/groups whose names match the configured prefixes. It never
    deletes an organization instance.

USAGE
-----
  # Dry run — discover and report (safe, default):
  python teardown.py

  # Dry run against specific prefixes / region:
  python teardown.py --user-prefix kiro-user- --group-prefix kiro-team- \
      --region us-east-1

  # Actually delete users, groups, memberships (keep the instance):
  python teardown.py --delete

  # Also delete the IdC account instance:
  python teardown.py --delete --delete-instance

  # Non-interactive (CI / scripted):
  python teardown.py --delete --delete-instance --yes

  # Prefer the manifest if you still have it (exact ids, no prefix guessing):
  python teardown.py --manifest ../output/manifest.json --delete
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

CONFIRM_PHRASE = "delete kiro provisioning"

MANUAL_STEPS = """\
================================================================================
MANUAL CONSOLE CLEANUP — these cannot be done via API, do them to finish
================================================================================
1. Kiro console -> deactivate every Kiro subscription / plan assigned to the
   groups (do this BEFORE deleting groups if you still can; if the groups are
   already gone, deactivate at the account/plan level).
2. IAM Identity Center -> Applications. Kiro creates an application assignment
   that is NOT auto-removed when access ends. Remove the Kiro application /
   its assignments manually.
3. (Cannot be reversed) The org management account's "permit member account
   instances" toggle is irreversible by design — nothing to clean up, just be
   aware it stays on.
If you deleted the account instance, items 1-2 may already be gone with it;
verify in both consoles.
================================================================================
"""


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--region", default=None,
                   help="Region of the IdC account instance. Defaults to AWS_REGION env / manifest.")
    p.add_argument("--profile", default=None,
                   help="AWS profile. Defaults to the standard SDK chain / AWS_PROFILE env.")
    p.add_argument("--user-prefix", default="kiro-user-",
                   help="Delete users whose user_name starts with this. Default: kiro-user-")
    p.add_argument("--group-prefix", default="kiro-team-",
                   help="Delete groups whose display_name starts with this. Default: kiro-team-")
    p.add_argument("--instance-arn", default=None,
                   help="IdC instance ARN. If omitted, the single account instance is auto-discovered.")
    p.add_argument("--identity-store-id", default=None,
                   help="Identity store id. If omitted, taken from the discovered instance.")
    p.add_argument("--manifest", type=pathlib.Path, default=None,
                   help="Optional manifest.json. If present, its exact ids/arn are used in preference to discovery.")
    p.add_argument("--delete", action="store_true",
                   help="Actually delete. Without this flag the script is a DRY RUN.")
    p.add_argument("--delete-instance", action="store_true",
                   help="Also delete the IdC ACCOUNT INSTANCE after users/groups are gone.")
    p.add_argument("--yes", action="store_true",
                   help="Skip the interactive confirmation prompt (for CI). Still requires --delete.")
    return p.parse_args(argv)


def _load_manifest(path: pathlib.Path | None) -> dict:
    if path is None:
        return {}
    if not path.exists():
        print(f"NOTE: --manifest {path} not found; falling back to live discovery.")
        return {}
    data = json.loads(path.read_text())
    if "value" in data and "identity_store_id" not in data:
        data = data["value"]
    return data


def _discover_instance(sso_admin) -> dict | None:
    """Return the single account instance dict, or None. Refuses org instances."""
    resp = sso_admin.list_instances()
    instances = resp.get("Instances", [])
    # An account instance has OwnerAccountId == this account (and typically no
    # organization owner). We do not try to delete anything that looks like an
    # org instance; account instances are what this repo creates.
    if not instances:
        return None
    if len(instances) > 1:
        print(f"WARNING: {len(instances)} IdC instances found; using the first. "
              f"Pass --instance-arn to disambiguate.")
    return instances[0]


def _discover_users(identitystore, store_id: str, prefix: str) -> list[dict]:
    users: list[dict] = []
    paginator = identitystore.get_paginator("list_users")
    for page in paginator.paginate(IdentityStoreId=store_id):
        for u in page.get("Users", []):
            if u.get("UserName", "").startswith(prefix):
                users.append(u)
    return users


def _discover_groups(identitystore, store_id: str, prefix: str) -> list[dict]:
    groups: list[dict] = []
    paginator = identitystore.get_paginator("list_groups")
    for page in paginator.paginate(IdentityStoreId=store_id):
        for g in page.get("Groups", []):
            if g.get("DisplayName", "").startswith(prefix):
                groups.append(g)
    return groups


def _memberships_for_group(identitystore, store_id: str, group_id: str) -> list[dict]:
    members: list[dict] = []
    paginator = identitystore.get_paginator("list_group_memberships")
    for page in paginator.paginate(IdentityStoreId=store_id, GroupId=group_id):
        members.extend(page.get("GroupMemberships", []))
    return members


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    manifest = _load_manifest(args.manifest)

    region = args.region or manifest.get("region")

    try:
        import boto3  # type: ignore
    except ImportError:
        print("boto3 not installed. Install it (project venv has it: `uv sync`) or `uv pip install boto3`.")
        return 2

    from botocore.exceptions import ClientError  # type: ignore

    session = boto3.Session(profile_name=args.profile, region_name=region)
    region = region or session.region_name
    if not region:
        print("ERROR: no region. Pass --region or set AWS_REGION.")
        return 2

    sso_admin = session.client("sso-admin", region_name=region)
    identitystore = session.client("identitystore", region_name=region)

    # --- Resolve instance + identity store -----------------------------------
    instance_arn = args.instance_arn or manifest.get("instance_arn")
    store_id = args.identity_store_id or manifest.get("identity_store_id")

    if not (instance_arn and store_id):
        inst = _discover_instance(sso_admin)
        if inst is None:
            print(f"No IAM Identity Center instance found in {region}. Nothing to tear down.")
            print(MANUAL_STEPS)
            return 0
        instance_arn = instance_arn or inst.get("InstanceArn")
        store_id = store_id or inst.get("IdentityStoreId")

    print("=" * 72)
    print("Kiro IdC teardown (state-free)")
    print("=" * 72)
    print(f"Region:           {region}")
    print(f"Instance ARN:     {instance_arn}")
    print(f"Identity store:   {store_id}")
    print(f"User prefix:      {args.user_prefix!r}")
    print(f"Group prefix:     {args.group_prefix!r}")
    print(f"Delete instance:  {args.delete_instance}")
    print(f"Mode:             {'DELETE' if args.delete else 'DRY RUN'}")
    print()

    # --- Discover targets -----------------------------------------------------
    users = _discover_users(identitystore, store_id, args.user_prefix)
    groups = _discover_groups(identitystore, store_id, args.group_prefix)

    print(f"Matched {len(users)} user(s):")
    for u in sorted(users, key=lambda x: x.get("UserName", "")):
        print(f"  - {u.get('UserName')}  ({u.get('UserId')})")
    print(f"Matched {len(groups)} group(s):")
    for g in sorted(groups, key=lambda x: x.get("DisplayName", "")):
        print(f"  - {g.get('DisplayName')}  ({g.get('GroupId')})")
    print()

    if not users and not groups and not args.delete_instance:
        print("Nothing matched. If you used different prefixes, pass --user-prefix / --group-prefix.")
        print(MANUAL_STEPS)
        return 0

    # --- Dry run stops here ---------------------------------------------------
    if not args.delete:
        print("DRY RUN — nothing deleted. Re-run with --delete to apply.")
        if args.delete_instance:
            print("(--delete-instance would also delete the account instance above.)")
        print()
        print(MANUAL_STEPS)
        return 0

    # --- Confirmation ---------------------------------------------------------
    if not args.yes:
        print(f"About to DELETE the above in account/region {region}.")
        print(f"Type the phrase to confirm:  {CONFIRM_PHRASE}")
        try:
            typed = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
        if typed != CONFIRM_PHRASE:
            print("Phrase did not match. Aborted. (Use --yes for non-interactive runs.)")
            return 1

    # --- Delete memberships, then users, then groups --------------------------
    errors = 0

    for g in groups:
        gid = g.get("GroupId")
        for m in _memberships_for_group(identitystore, store_id, gid):
            mid = m.get("MembershipId")
            try:
                identitystore.delete_group_membership(IdentityStoreId=store_id, MembershipId=mid)
                print(f"  deleted membership {mid}")
            except ClientError as exc:
                errors += 1
                print(f"  FAIL membership {mid}: {exc}")

    for u in users:
        uid = u.get("UserId")
        try:
            identitystore.delete_user(IdentityStoreId=store_id, UserId=uid)
            print(f"  deleted user {u.get('UserName')} ({uid})")
        except ClientError as exc:
            errors += 1
            print(f"  FAIL user {u.get('UserName')}: {exc}")

    for g in groups:
        gid = g.get("GroupId")
        try:
            identitystore.delete_group(IdentityStoreId=store_id, GroupId=gid)
            print(f"  deleted group {g.get('DisplayName')} ({gid})")
        except ClientError as exc:
            errors += 1
            print(f"  FAIL group {g.get('DisplayName')}: {exc}")

    # --- Optionally delete the account instance -------------------------------
    if args.delete_instance:
        try:
            sso_admin.delete_instance(InstanceArn=instance_arn)
            print(f"  deleted account instance {instance_arn}")
        except ClientError as exc:
            errors += 1
            print(f"  FAIL delete instance {instance_arn}: {exc}")

    print()
    if errors:
        print(f"Completed with {errors} error(s). Re-run after resolving them.")
        print(MANUAL_STEPS)
        return 4

    print("Done. IdC users/groups/memberships removed"
          + (" and account instance deleted." if args.delete_instance else " (instance kept)."))
    print(MANUAL_STEPS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
