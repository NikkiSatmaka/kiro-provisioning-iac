#!/usr/bin/env python3
"""Cross-workshop teardown isolation check (Requirement 10.6).

Tearing one workshop down must leave every *other* workshop untouched. This
script makes that verifiable: it snapshots a chosen *other* workshop's
observable resources before a destructive operation and, afterwards, re-reads
the same resources and diffs the two snapshots. If anything the other workshop
owns was removed or modified, the diff names it and the process exits non-zero.

Two phases, one baseline file:

    # BEFORE tearing down workshop A, snapshot the bystander workshop B:
    python scripts/verify_isolation.py \
        --other-workshop kiro-2025-10-10-b \
        --phase baseline \
        --baseline /tmp/ws-b.before.json

    # ... run `tofu destroy` against workshop A ...

    # AFTER: re-read workshop B and diff against the baseline:
    python scripts/verify_isolation.py \
        --other-workshop kiro-2025-10-10-b \
        --phase verify \
        --baseline /tmp/ws-b.before.json

``verify`` exits ``0`` and prints ``unchanged`` when the other workshop's
resources are identical to the baseline; it exits non-zero and lists the
affected resources when they differ.

Design split (so the correctness core stays testable):

* :func:`diff_snapshots` is PURE — no AWS, no I/O. It takes two snapshot dicts
  and returns a list of human-readable strings, one per resource that was
  removed or modified between ``before`` and ``after``. Property 10 (task 9.2)
  exercises it directly over generated snapshot pairs.
* Every boto3 call lives in a reader (``read_*`` / :func:`build_snapshot`).
  The readers are confined to building the snapshot dict; nothing else in the
  module touches AWS.

Resources covered for the other workshop (Requirement 10.6): its IdC groups and
users (filtered to that workshop by the ``kiro-<workshop_id>`` permission set and
the ``<workshop_id>-...`` username namespace), the account assignments on its
permission set, and its claim-service resources derived from
``credential-claim-<workshop_id>`` (table, Lambda, Function URL, role, policy).

Region is derived only from the environment (``AWS_REGION``), never hardcoded —
mirroring the sibling claim-service scripts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

# Deployment region, derived only from the environment (never hardcoded),
# matching claim-service/scripts/*.py. us-east-1 is the fallback when unset.
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Namespacing conventions, kept in lockstep with the OpenTofu derivations so the
# readers address exactly the resources a given workshop_id owns:
#   * subscription/terraform/identity_center.tf: permission set name "kiro-<id>".
#   * claim-service/terraform/{dynamodb,lambda}.tf: local.name "credential-claim-<id>".
#   * subscription/terraform/locals.tf: username "<id>-<acct_last4>-<group>-<NN>".
PERMISSION_SET_NAME_PREFIX = "kiro-"
CLAIM_NAME_PREFIX = "credential-claim-"


def permission_set_name(workshop_id: str) -> str:
    """The permission set name OpenTofu derives for ``workshop_id``."""
    return f"{PERMISSION_SET_NAME_PREFIX}{workshop_id}"


def claim_name(workshop_id: str) -> str:
    """The claim-service ``local.name`` base for ``workshop_id``.

    The table, Lambda, and Function URL function name are exactly this; the role
    is ``<name>-lambda`` and the table-access policy is ``<name>-table-access``.
    """
    return f"{CLAIM_NAME_PREFIX}{workshop_id}"


# ---------------------------------------------------------------------------
# Pure diff core (no AWS, no I/O — testable in isolation; Property 10)
# ---------------------------------------------------------------------------


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Return the resources removed or modified between two snapshots.

    PURE: no AWS, no I/O. ``before`` and ``after`` are snapshot dicts of the
    shape :func:`build_snapshot` produces — a mapping of resource category
    (``"groups"``, ``"users"``, ``"account_assignments"``, ``"claim"``) to a
    map of ``resource key -> stable value``.

    The result is a list of human-readable strings, one per resource that was
    present in ``before`` but is now **missing** or **modified** in ``after``.
    An empty list means the other workshop's resources are intact — nothing it
    owned was removed or changed (Requirement 10.6).

    Only removals and modifications are flagged, never additions: a teardown of
    *another* workshop can only ever delete or mutate a bystander's resources,
    and growth in the bystander (e.g. a concurrently running provision) is not a
    violation of isolation. Each flagged resource is reported with its category
    and key so an operator can act on it directly.

    Deterministic ordering: categories in sorted order, keys within a category
    in sorted order, so the same (before, after) pair always yields byte-
    identical output.
    """
    findings: list[str] = []
    for category in sorted(before):
        before_items = before.get(category) or {}
        after_items = after.get(category) or {}
        for key in sorted(before_items):
            if key not in after_items:
                findings.append(f"{category}: {key} was removed")
            elif after_items[key] != before_items[key]:
                findings.append(f"{category}: {key} was modified")
    return findings


# ---------------------------------------------------------------------------
# AWS-touching readers (ALL boto3 access is confined below this line)
# ---------------------------------------------------------------------------


def _is_resource_not_found(exc: ClientError) -> bool:
    """True for the various 'does not exist' error codes across services.

    Matched on the error code (not an exception class) so the check holds for a
    live client or a stubbed one in tests. A missing resource is treated as
    simply absent from the snapshot, not an error — a bystander workshop may
    legitimately have no claim service, for instance.
    """
    code = exc.response.get("Error", {}).get("Code")
    return code in {
        "ResourceNotFoundException",
        "ResourceNotFound",
        "NoSuchEntity",
    }


def _find_permission_set_arn(
    sso_admin: Any, instance_arn: str, workshop_id: str
) -> str | None:
    """Return the ARN of the ``kiro-<workshop_id>`` permission set, or None.

    Lists the instance's permission sets and matches on the name OpenTofu
    derived for this workshop, so the reader scopes to exactly the other
    workshop's permission set and never a different workshop's.
    """
    wanted = permission_set_name(workshop_id)
    paginator = sso_admin.get_paginator("list_permission_sets")
    for page in paginator.paginate(InstanceArn=instance_arn):
        for ps_arn in page.get("PermissionSets", []):
            described = sso_admin.describe_permission_set(
                InstanceArn=instance_arn, PermissionSetArn=ps_arn
            )
            name = described.get("PermissionSet", {}).get("Name")
            if name == wanted:
                return ps_arn
    return None


def read_account_assignments(
    sso_admin: Any, instance_arn: str, workshop_id: str
) -> dict[str, dict[str, str]]:
    """Snapshot the account assignments on the other workshop's permission set.

    Keyed ``"<account_id>:<principal_type>:<principal_id>"`` so each group's
    binding is a distinct, stable entry (Requirement 10.6 covers account
    assignments). Returns an empty map when the workshop has no permission set.
    """
    assignments: dict[str, dict[str, str]] = {}
    ps_arn = _find_permission_set_arn(sso_admin, instance_arn, workshop_id)
    if ps_arn is None:
        return assignments

    # The provisioned principals are groups; enumerate assignments for the
    # permission set across the accounts it targets.
    accounts_paginator = sso_admin.get_paginator(
        "list_accounts_for_provisioned_permission_set"
    )
    for acct_page in accounts_paginator.paginate(
        InstanceArn=instance_arn, PermissionSetArn=ps_arn
    ):
        for account_id in acct_page.get("AccountIds", []):
            assign_paginator = sso_admin.get_paginator("list_account_assignments")
            for page in assign_paginator.paginate(
                InstanceArn=instance_arn,
                AccountId=account_id,
                PermissionSetArn=ps_arn,
            ):
                for a in page.get("AccountAssignments", []):
                    principal_type = a.get("PrincipalType", "")
                    principal_id = a.get("PrincipalId", "")
                    key = f"{account_id}:{principal_type}:{principal_id}"
                    assignments[key] = {
                        "account_id": account_id,
                        "principal_type": principal_type,
                        "principal_id": principal_id,
                        "permission_set_arn": ps_arn,
                    }
    return assignments


def _assignment_group_ids(assignments: dict[str, dict[str, str]]) -> set[str]:
    """The IdC group ids bound by the workshop's account assignments.

    Groups are the only principal type the subscription stack assigns, so an
    assignment's ``principal_id`` (when its type is ``GROUP``) identifies a group
    that belongs to this workshop. Used to scope the group/user readers to the
    other workshop without over-reading the shared identity store.
    """
    return {
        a["principal_id"]
        for a in assignments.values()
        if a.get("principal_type") == "GROUP" and a.get("principal_id")
    }


def read_groups(
    identitystore: Any, identity_store_id: str, group_ids: set[str]
) -> dict[str, dict[str, str]]:
    """Snapshot the other workshop's IdC groups by id.

    Reads only the groups the workshop's account assignments reference, so the
    reader never touches another workshop's groups in the shared identity store.
    Keyed by ``group_id``; the value carries the display name so a rename shows
    up as a modification in the diff.
    """
    groups: dict[str, dict[str, str]] = {}
    for group_id in sorted(group_ids):
        try:
            described = identitystore.describe_group(
                IdentityStoreId=identity_store_id, GroupId=group_id
            )
        except ClientError as exc:
            if _is_resource_not_found(exc):
                continue
            raise
        groups[group_id] = {
            "group_id": group_id,
            "display_name": described.get("DisplayName", ""),
        }
    return groups


def read_users(
    identitystore: Any, identity_store_id: str, group_ids: set[str]
) -> dict[str, dict[str, str]]:
    """Snapshot the other workshop's IdC users by id.

    A user belongs to the workshop when it is a member of one of the workshop's
    groups (``group_ids``). The reader walks each group's memberships and
    describes each member, so it scopes to exactly this workshop's participants.
    Keyed by ``user_id``; the value carries the username and display name so a
    rename shows up as a modification in the diff.
    """
    users: dict[str, dict[str, str]] = {}
    member_paginator = identitystore.get_paginator("list_group_memberships")
    for group_id in sorted(group_ids):
        for page in member_paginator.paginate(
            IdentityStoreId=identity_store_id, GroupId=group_id
        ):
            for membership in page.get("GroupMemberships", []):
                member = membership.get("MemberId", {})
                user_id = member.get("UserId")
                if not user_id or user_id in users:
                    continue
                try:
                    described = identitystore.describe_user(
                        IdentityStoreId=identity_store_id, UserId=user_id
                    )
                except ClientError as exc:
                    if _is_resource_not_found(exc):
                        continue
                    raise
                users[user_id] = {
                    "user_id": user_id,
                    "user_name": described.get("UserName", ""),
                    "display_name": described.get("DisplayName", ""),
                }
    return users


def read_claim_resources(
    dynamodb: Any, lambda_client: Any, iam: Any, workshop_id: str
) -> dict[str, dict[str, str]]:
    """Snapshot the other workshop's claim-service resources.

    Derives every name from ``credential-claim-<workshop_id>`` (the claim stack's
    ``local.name``) and reads each resource's existence/identity: the DynamoDB
    table, the Lambda function, its Function URL, the execution role
    (``<name>-lambda``), and the inline table-access policy
    (``<name>-table-access``). Each present resource is a keyed entry; a missing
    one is simply absent (so a removal between baseline and verify shows up in
    the diff). Keyed by ``"<kind>:<name>"``.
    """
    name = claim_name(workshop_id)
    role_name = f"{name}-lambda"
    policy_name = f"{name}-table-access"
    resources: dict[str, dict[str, str]] = {}

    # DynamoDB table.
    try:
        table = dynamodb.describe_table(TableName=name).get("Table", {})
        resources[f"table:{name}"] = {
            "kind": "dynamodb_table",
            "name": name,
            "arn": table.get("TableArn", ""),
            "status": table.get("TableStatus", ""),
        }
    except ClientError as exc:
        if not _is_resource_not_found(exc):
            raise

    # Lambda function.
    try:
        fn = lambda_client.get_function(FunctionName=name).get(
            "Configuration", {}
        )
        resources[f"lambda:{name}"] = {
            "kind": "lambda_function",
            "name": name,
            "arn": fn.get("FunctionArn", ""),
            "runtime": fn.get("Runtime", ""),
            "handler": fn.get("Handler", ""),
        }
    except ClientError as exc:
        if not _is_resource_not_found(exc):
            raise

    # Lambda Function URL (the function name is the same local.name).
    try:
        url_config = lambda_client.get_function_url_config(FunctionName=name)
        resources[f"function_url:{name}"] = {
            "kind": "lambda_function_url",
            "name": name,
            "function_url": url_config.get("FunctionUrl", ""),
            "auth_type": url_config.get("AuthType", ""),
        }
    except ClientError as exc:
        if not _is_resource_not_found(exc):
            raise

    # Execution role.
    try:
        role = iam.get_role(RoleName=role_name).get("Role", {})
        resources[f"role:{role_name}"] = {
            "kind": "iam_role",
            "name": role_name,
            "arn": role.get("Arn", ""),
        }
    except ClientError as exc:
        if not _is_resource_not_found(exc):
            raise

    # Inline table-access policy on the role.
    try:
        policy = iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)
        document = policy.get("PolicyDocument", "")
        resources[f"role_policy:{role_name}/{policy_name}"] = {
            "kind": "iam_role_policy",
            "role_name": role_name,
            "policy_name": policy_name,
            # Serialize so the stored value is comparable/stable; the document
            # may come back as a dict (live client) or string (stubbed).
            "document": json.dumps(document, sort_keys=True)
            if isinstance(document, (dict, list))
            else str(document),
        }
    except ClientError as exc:
        if not _is_resource_not_found(exc):
            raise

    return resources


def build_snapshot(
    workshop_id: str,
    instance_arn: str,
    identity_store_id: str,
    *,
    session: Any | None = None,
) -> dict[str, Any]:
    """Build the full snapshot dict for the other workshop.

    All AWS access for a snapshot funnels through here and the ``read_*``
    readers it calls — the one place the module talks to the cloud. The result
    is a plain, JSON-serializable dict :func:`diff_snapshots` can consume
    directly::

        {
          "workshop_id": "<id>",
          "groups": { <group_id>: {...} },
          "users": { <user_id>: {...} },
          "account_assignments": { "<acct>:<type>:<id>": {...} },
          "claim": { "<kind>:<name>": {...} }
        }

    ``session`` lets tests inject a boto3 Session with stubbed clients; by
    default a session is created from the ambient credentials.
    """
    session = session or boto3.Session(region_name=REGION)
    sso_admin = session.client("sso-admin", region_name=REGION)
    identitystore = session.client("identitystore", region_name=REGION)
    dynamodb = session.client("dynamodb", region_name=REGION)
    lambda_client = session.client("lambda", region_name=REGION)
    iam = session.client("iam", region_name=REGION)

    assignments = read_account_assignments(sso_admin, instance_arn, workshop_id)
    group_ids = _assignment_group_ids(assignments)
    groups = read_groups(identitystore, identity_store_id, group_ids)
    users = read_users(identitystore, identity_store_id, group_ids)
    claim = read_claim_resources(dynamodb, lambda_client, iam, workshop_id)

    return {
        "workshop_id": workshop_id,
        "groups": groups,
        "users": users,
        "account_assignments": assignments,
        "claim": claim,
    }


# ---------------------------------------------------------------------------
# I/O helpers (snapshot persistence) and CLI
# ---------------------------------------------------------------------------


def write_snapshot(snapshot: dict[str, Any], destination: Path) -> None:
    """Persist a snapshot to ``destination`` as pretty, stable JSON."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def load_snapshot(path: Path) -> dict[str, Any]:
    """Read a baseline snapshot written by a prior ``baseline`` run."""
    if not path.exists():
        sys.exit(
            f"ERROR: baseline snapshot not found: {path}\n"
            "Run the 'baseline' phase first to capture the other workshop's "
            "resources before the destructive operation."
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"ERROR: baseline snapshot is not valid JSON: {exc}")


def _resolve_foundation_inputs(
    args: argparse.Namespace,
) -> tuple[str, str]:
    """Resolve the Foundation IdC instance ARN and identity store id.

    From ``--idc-instance-arn``/``--identity-store-id`` or their env fallbacks
    (``IDC_INSTANCE_ARN`` / ``IDENTITY_STORE_ID``, with ``TF_VAR_*`` honored
    too). Both are required to read the other workshop's IdC resources; a
    missing one fails before any AWS call.
    """
    instance_arn = (
        args.idc_instance_arn
        or os.environ.get("IDC_INSTANCE_ARN")
        or os.environ.get("TF_VAR_idc_instance_arn")
        or ""
    ).strip()
    identity_store_id = (
        args.identity_store_id
        or os.environ.get("IDENTITY_STORE_ID")
        or os.environ.get("TF_VAR_identity_store_id")
        or ""
    ).strip()
    missing = [
        label
        for label, value in (
            ("--idc-instance-arn (or IDC_INSTANCE_ARN)", instance_arn),
            ("--identity-store-id (or IDENTITY_STORE_ID)", identity_store_id),
        )
        if not value
    ]
    if missing:
        sys.exit(
            "ERROR: missing required Foundation IdC input(s): "
            + ", ".join(missing)
        )
    return instance_arn, identity_store_id


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--other-workshop",
        required=True,
        help=(
            "The workshop_id of the OTHER (bystander) workshop to verify stays "
            "untouched — not the workshop being torn down."
        ),
    )
    p.add_argument(
        "--phase",
        required=True,
        choices=("baseline", "verify"),
        help=(
            "'baseline' snapshots the other workshop before a destructive op; "
            "'verify' re-reads and diffs against that baseline."
        ),
    )
    p.add_argument(
        "--baseline",
        required=True,
        type=Path,
        help=(
            "Path to the baseline snapshot JSON: written in the 'baseline' "
            "phase, read in the 'verify' phase."
        ),
    )
    p.add_argument(
        "--idc-instance-arn",
        default=None,
        help=(
            "Foundation IdC instance ARN. Defaults to IDC_INSTANCE_ARN / "
            "TF_VAR_idc_instance_arn from the environment."
        ),
    )
    p.add_argument(
        "--identity-store-id",
        default=None,
        help=(
            "Foundation IdC identity store id. Defaults to IDENTITY_STORE_ID / "
            "TF_VAR_identity_store_id from the environment."
        ),
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run a baseline or verify phase. Returns a process exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    workshop_id = (args.other_workshop or "").strip()
    if not workshop_id:
        sys.exit("ERROR: --other-workshop must be a non-empty workshop_id.")

    instance_arn, identity_store_id = _resolve_foundation_inputs(args)

    if args.phase == "baseline":
        snapshot = build_snapshot(workshop_id, instance_arn, identity_store_id)
        write_snapshot(snapshot, args.baseline)
        n = (
            len(snapshot["groups"])
            + len(snapshot["users"])
            + len(snapshot["account_assignments"])
            + len(snapshot["claim"])
        )
        print(
            f"Captured baseline for workshop {workshop_id!r} "
            f"({n} resource(s)) to {args.baseline}"
        )
        return 0

    # verify
    before = load_snapshot(args.baseline)
    after = build_snapshot(workshop_id, instance_arn, identity_store_id)
    findings = diff_snapshots(before, after)
    if not findings:
        print(f"unchanged: workshop {workshop_id!r} resources are intact")
        return 0

    print(
        f"ISOLATION FAILURE: workshop {workshop_id!r} had "
        f"{len(findings)} resource(s) removed or modified:",
        file=sys.stderr,
    )
    for finding in findings:
        print(f"  - {finding}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
