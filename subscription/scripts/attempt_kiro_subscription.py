#!/usr/bin/env python3
"""Best-effort, FAIL-CLOSED attempt to subscribe IdC groups to a Kiro tier.

READ THIS FIRST
---------------
Assigning a Kiro subscription tier to a group is driven by the **Kiro console**
("Onboard your team to Kiro" -> Add group -> pick tier). The underlying API
(seen in CloudTrail as `q:CreateAssignment`) is internal and undocumented, and
has a track record of returning `UnknownError` when called outside the console.
There is ALSO a one-time "Enable Kiro" console step that provisions the Kiro
profile + service-linked role; it cannot be scripted reliably.

Therefore this script:

  * Does NOTHING unless you pass --attempt (fail-closed by default).
  * Discovers, at runtime, whether the installed AWS SDK even exposes a
    plausible subscription API. If not, it prints the console steps and exits
    non-zero. It will NOT pretend success.
  * If a plausible API exists, it tries it per group and reports exactly what
    happened. Treat any success as needing verification in the Kiro console.

This script never touches passwords and never edits the Markdown output.

USAGE
-----
  # Dry run — just report what it WOULD do and whether an API is available:
  python attempt_kiro_subscription.py --manifest ../output/manifest.json

  # Actually attempt (opt-in):
  python attempt_kiro_subscription.py --manifest ../output/manifest.json \
      --attempt --tier PRO
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Map our tier names to the subscription identifiers seen in Kiro/CodeWhisperer
# CloudTrail (`subscriptionType`). These are best-effort guesses used ONLY when
# a mutating API is actually present; the console is the source of truth.
TIER_TO_SUBSCRIPTION_TYPE = {
    "PRO": "Q_DEVELOPER_STANDALONE_PRO",
    "PRO_PLUS": "Q_DEVELOPER_STANDALONE_PRO_PLUS",
    "PRO_MAX": "Q_DEVELOPER_STANDALONE_PRO_MAX",
    "POWER": "Q_DEVELOPER_STANDALONE_POWER",
}

CONSOLE_STEPS = """\
Could not assign the Kiro tier via API. Do it in the console (reliable path):

  1. AWS console -> Kiro. If first time: click "Onboard your team to Kiro"
     (or "Enable small teams"); choose IAM Identity Center as the identity
     source; click Enable. Note the Sign-in URL.
  2. Users & Groups -> Groups tab -> Add group.
  3. Select each group listed below and choose the desired tier.
See RUNBOOK.md for the full walkthrough and verification.
"""


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", required=True, type=pathlib.Path,
                   help="manifest.json (tofu output -json provisioning_manifest).")
    p.add_argument("--tier", choices=sorted(TIER_TO_SUBSCRIPTION_TYPE), default=None,
                   help="Override tier. Defaults to the manifest's kiro_tier.")
    p.add_argument("--attempt", action="store_true",
                   help="Actually call the API. Without this flag the script only reports (dry run).")
    p.add_argument("--region", default=None, help="Override region (defaults to manifest region).")
    return p.parse_args(argv)


def _load_manifest(path: pathlib.Path) -> dict:
    if not path.exists():
        sys.exit(f"ERROR: manifest not found: {path}\n"
                 f"Generate it:  tofu output -json provisioning_manifest > {path}")
    data = json.loads(path.read_text())
    if "value" in data and "identity_store_id" not in data:
        data = data["value"]
    return data


def _discover_subscription_client(session, region: str):
    """Return (client, service_name, create_op) if a plausible API exists, else None.

    We probe service names that have historically carried Q Developer / Kiro
    subscription operations. This is deliberately defensive: SDK surfaces change,
    and we would rather report "no API available" than call the wrong thing.
    """
    available = set(session.get_available_services())
    # Candidate (service_name, operation_name) pairs, most-specific first.
    candidates = [
        ("qdeveloper", "create_subscription"),
        ("q", "create_subscription"),
        ("qdeveloper", "create_assignment"),
        ("q", "create_assignment"),
        ("codewhisperer", "create_subscription"),
    ]
    for service, op in candidates:
        if service not in available:
            continue
        try:
            client = session.client(service, region_name=region)
        except Exception:
            continue
        if hasattr(client, op):
            return client, service, op
    return None


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    manifest = _load_manifest(args.manifest)
    region = args.region or manifest.get("region")
    tier = args.tier or manifest.get("kiro_tier", "PRO")
    sub_type = TIER_TO_SUBSCRIPTION_TYPE.get(tier)
    groups = manifest.get("groups", {})
    instance_arn = manifest.get("instance_arn", "")

    if not groups:
        print("No groups in manifest; nothing to subscribe.")
        return 0

    print(f"Target tier: {tier} ({sub_type})")
    print(f"Region:      {region}")
    print(f"Groups:      {len(groups)}")
    for g in sorted(groups.values(), key=lambda x: x.get('display_name', '')):
        print(f"  - {g.get('display_name')}  ({g.get('group_id')})")
    print()

    # Import boto3 lazily so the output script has no hard dependency on it.
    try:
        import boto3  # noqa: F401
    except ImportError:
        print("boto3 not installed. Install it (project venv has it) or use the console.")
        print(CONSOLE_STEPS)
        return 2

    import boto3  # type: ignore
    session = boto3.Session(region_name=region)
    found = _discover_subscription_client(session, region)

    if found is None:
        print("No Kiro/Q subscription API is exposed by the installed AWS SDK.")
        print("This is expected: Kiro tier assignment is a console operation.")
        print()
        print(CONSOLE_STEPS)
        return 3

    client, service, op = found
    print(f"Found candidate API: {service}.{op}")

    if not args.attempt:
        print("\nDry run (no --attempt). Not calling the API.")
        print("Re-run with --attempt to try it. Verify results in the Kiro console afterwards.")
        return 0

    # Opt-in attempt. We do not know the exact parameter contract, so we try the
    # most likely shapes and report precisely. Any ClientError is surfaced, not
    # swallowed.
    from botocore.exceptions import ClientError, ParamValidationError  # type: ignore

    failures = 0
    for g in groups.values():
        gid = g.get("group_id")
        name = g.get("display_name")
        attempts = [
            {"groupId": gid, "subscriptionType": sub_type},
            {"principalId": gid, "principalType": "GROUP", "subscriptionType": sub_type},
            {"instanceArn": instance_arn, "principalId": gid, "principalType": "GROUP",
             "subscriptionType": sub_type},
        ]
        ok = False
        last_err = None
        for params in attempts:
            try:
                getattr(client, op)(**params)
                print(f"  OK   {name}: {op}({', '.join(params)}) accepted.")
                ok = True
                break
            except (ClientError, ParamValidationError) as exc:
                last_err = exc
                continue
            except Exception as exc:  # noqa: BLE001 - report anything unexpected
                last_err = exc
                continue
        if not ok:
            failures += 1
            print(f"  FAIL {name}: all parameter shapes rejected. Last error: {last_err}")

    print()
    if failures:
        print(f"{failures}/{len(groups)} group(s) could not be subscribed via API.")
        print(CONSOLE_STEPS)
        return 4

    print("All groups accepted by the API. IMPORTANT: verify each subscription "
          "in the Kiro console — an accepted call is not proof of an active plan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
