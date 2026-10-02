#!/usr/bin/env python3
"""Build the Kiro credentials Markdown file from the OpenTofu manifest + OTPs.

WHY THIS EXISTS
---------------
IAM Identity Center exposes NO public API to set, reset, or share a user
password, and `CreateUser` neither sets a password nor sends the invitation
email. The only ways to give a user a usable password are console-only:

  * "Generate a one-time password" (admin reads it; user must change it on first
    sign-in). This is the closest thing to a shared/default password.
  * "Send an email with password-setup instructions" (needs real inboxes).

So this script does NOT set passwords. It:

  1. Reads the provisioning manifest produced by OpenTofu
     (`tofu output -json provisioning_manifest`).
  2. Optionally reads a CSV of one-time passwords you collected from the console
     (username,otp) so they can be embedded in the output.
  3. Renders a single Markdown file with the sign-in URL, region, and a row per
     user (username, email, group(s), password/OTP, status). Email is optional;
     anonymous users show a dash.

NOTHING here calls a mutating AWS API. It is safe to run repeatedly.

USAGE
-----
  # 1. Export the manifest from terraform/:
  #    tofu output -json provisioning_manifest > ../output/manifest.json
  #
  # 2. (optional) Collect OTPs from the console into a CSV:
  #    username,otp
  #    kiro-user-01,Ab12...
  #
  # 3. Render:
  python provision_passwords_and_output.py \
      --manifest ../output/manifest.json \
      --sign-in-url https://d-xxxx.awsapps.com/start \
      --otp-csv ../output/otps.csv \
      --out ../output/credentials.md

If --sign-in-url is omitted, the script leaves a clear TODO placeholder (you get
the real URL from the Kiro console after enabling Kiro — see RUNBOOK.md).
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import pathlib
import sys


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", required=True, type=pathlib.Path,
                   help="Path to manifest.json (tofu output -json provisioning_manifest).")
    p.add_argument("--out", required=True, type=pathlib.Path,
                   help="Path to write the credentials Markdown file.")
    p.add_argument("--sign-in-url", default="",
                   help="Kiro / IdC access portal sign-in URL. Get it from the Kiro console after enabling Kiro.")
    p.add_argument("--otp-csv", type=pathlib.Path, default=None,
                   help="Optional CSV with header 'username,otp' mapping users to one-time passwords.")
    p.add_argument("--note", default="",
                   help="Optional free-text note included in the output header.")
    return p.parse_args(argv)


def _load_manifest(path: pathlib.Path) -> dict:
    if not path.exists():
        sys.exit(f"ERROR: manifest not found: {path}\n"
                 f"Generate it first:  tofu output -json provisioning_manifest > {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        sys.exit(f"ERROR: manifest is not valid JSON: {exc}")

    # `tofu output -json <name>` emits the raw value. `tofu output -json` (all
    # outputs) wraps each in {"value": ...}. Accept both shapes.
    if "value" in data and "identity_store_id" not in data:
        data = data["value"]
    required = {"region", "identity_store_id", "users"}
    missing = required - set(data)
    if missing:
        sys.exit(f"ERROR: manifest missing keys: {sorted(missing)}. "
                 f"Did you export the 'provisioning_manifest' output?")
    return data


def _load_otps(path: pathlib.Path | None) -> dict[str, str]:
    if path is None:
        return {}
    if not path.exists():
        sys.exit(f"ERROR: --otp-csv given but file not found: {path}")
    otps: dict[str, str] = {}
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or "username" not in reader.fieldnames or "otp" not in reader.fieldnames:
            sys.exit("ERROR: otp CSV must have a header row: username,otp")
        for row in reader:
            uname = (row.get("username") or "").strip()
            if uname:
                otps[uname] = (row.get("otp") or "").strip()
    return otps


def _user_to_groups(manifest: dict) -> dict[str, list[str]]:
    """Best-effort username -> [group display names] from the manifest.

    The manifest's `groups` carry ids, not memberships. Memberships live in the
    separate `memberships` tofu output. If you also export that, drop it in as
    manifest['memberships'] = {k: {username, group}} and this will use it.
    """
    mapping: dict[str, list[str]] = {}
    memberships = manifest.get("memberships") or {}
    for m in memberships.values():
        mapping.setdefault(m.get("username", ""), []).append(m.get("group", ""))
    return mapping


def _render(manifest: dict, otps: dict[str, str], sign_in_url: str, note: str) -> str:
    region = manifest["region"]
    identity_store_id = manifest["identity_store_id"]
    tier = manifest.get("kiro_tier", "(set in tfvars)")
    users = manifest["users"]
    groups = manifest.get("groups", {})
    user_groups = _user_to_groups(manifest)
    generated = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    # Precedence: an explicit --sign-in-url wins (lets you supply a custom vanity
    # subdomain). Otherwise fall back to the default URL the manifest derives
    # from the identity store id, so users never paste it by hand. Only if both
    # are absent do we leave a TODO placeholder.
    resolved_url = sign_in_url or manifest.get("sign_in_url", "")
    url_cell = resolved_url or "TODO — get sign-in URL from the Kiro console (see RUNBOOK.md)"

    lines: list[str] = []
    lines.append("# Kiro Access Credentials")
    lines.append("")
    lines.append("> SENSITIVE — contains sign-in details. Do not commit. Distribute securely, then delete.")
    lines.append("")
    if note:
        lines.append(f"**Note:** {note}")
        lines.append("")
    lines.append(f"- **Generated (UTC):** {generated}")
    lines.append(f"- **Sign-in URL:** {url_cell}")
    lines.append(f"- **Region code:** `{region}`")
    lines.append(f"- **Identity store:** `{identity_store_id}`")
    lines.append(f"- **Kiro tier:** {tier}")
    lines.append(f"- **Users:** {len(users)}  |  **Groups:** {len(groups)}")
    lines.append("")
    lines.append("## How to sign in")
    lines.append("")
    lines.append("1. Open Kiro. Choose sign in with your organization.")
    lines.append("2. Choose **Sign in via IAM Identity Center**.")
    lines.append(f"3. Enter the sign-in URL above and the region code `{region}`.")
    lines.append("4. Sign in with the username + password below. You will be asked to set a new password on first login.")
    lines.append("")
    lines.append("## Users")
    lines.append("")
    lines.append("| # | Username | Email | Group(s) | Password / OTP | Status |")
    lines.append("|---|----------|-------|----------|----------------|--------|")

    missing_otp = 0
    for i, (key, u) in enumerate(sorted(users.items()), start=1):
        uname = u.get("username", "")
        # email is optional (anonymous users have none). Null/missing => dash,
        # so the table never prints a literal "None".
        email = u.get("email") or "—"
        grp = ", ".join(g for g in user_groups.get(uname, []) if g) or "—"
        otp = otps.get(uname, "")
        if otp:
            pw_cell = f"`{otp}`"
            status = "OTP set"
        else:
            pw_cell = "TODO — generate one-time password in console"
            status = "pending password"
            missing_otp += 1
        lines.append(f"| {i} | `{uname}` | {email} | {grp} | {pw_cell} | {status} |")

    lines.append("")
    if missing_otp:
        lines.append(f"> {missing_otp} user(s) still need a one-time password. "
                     f"See RUNBOOK.md step 5, then re-run with `--otp-csv`.")
        lines.append("")
    lines.append("## Reminder on passwords")
    lines.append("")
    lines.append("AWS IAM Identity Center does not allow an admin-chosen shared password. "
                 "Each password above is a per-user one-time password generated in the console; "
                 "users must set their own password on first sign-in.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    manifest = _load_manifest(args.manifest)
    otps = _load_otps(args.otp_csv)
    md = _render(manifest, otps, args.sign_in_url, args.note)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md)
    print(f"Wrote {args.out}  ({len(manifest['users'])} users).")
    if not args.sign_in_url:
        if manifest.get("sign_in_url"):
            print(f"NOTE: no --sign-in-url given; used the manifest's derived URL "
                  f"({manifest['sign_in_url']}).")
        else:
            print("NOTE: no --sign-in-url given and none in the manifest; a TODO "
                  "placeholder was written instead.")
    if not otps:
        print("NOTE: no --otp-csv given; password cells are TODO placeholders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
