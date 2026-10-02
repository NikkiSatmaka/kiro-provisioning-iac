#!/usr/bin/env python3
"""Entrypoint that drives the AUTOMATABLE provisioning steps end to end.

READ THIS FIRST
---------------
This orchestrates only the steps AWS actually exposes as APIs/IaC:

  1. tofu init          (in ../terraform; REQUIRES the remote S3 backend)
  2. tofu plan          (always shown)
  3. tofu apply         (only with --apply)
  4. export the provisioning_manifest output -> ../output/manifest.json
  5. render ../output/credentials.md from the manifest (+ optional OTP CSV)

Remote S3 state is MANDATORY for the main config. Step 1 inits with
`-backend-config=backend.hcl`, so `backend.tf` + `backend.hcl` must exist in
../terraform first (set up once via the backend-bootstrap config — see RUNBOOK
step 1b). If either file is missing the script FAILS CLOSED (prints the fix and
exits non-zero); it never silently falls back to local state, because local
state is git-ignored and would make teardown from a fresh clone impossible.
`--render-only` is exempt — it runs no tofu.

It then PRINTS the console-only steps it cannot do (make MFA optional, enable
Kiro, assign the tier, generate one-time passwords) as a checklist. It never
pretends to have done them. See RUNBOOK.md for the full walkthrough.

Mirrors teardown.py's conventions: DRY RUN by default (plan only), mutation is
opt-in (--apply), and it refuses to invent success.

USAGE
-----
  # Dry run — init + plan only, no changes (safe, default):
  python provision.py

  # Apply (creates the IdC instance, users, groups, memberships), then export
  # the manifest and render credentials.md with a TODO password column:
  python provision.py --apply

  # Apply and auto-approve (non-interactive / CI):
  python provision.py --apply --yes

  # After you have collected OTPs from the console, re-render with them and the
  # real sign-in URL (no tofu needed):
  python provision.py --render-only \
      --sign-in-url https://d-xxxx.awsapps.com/start \
      --otp-csv ../output/otps.csv

  # Pass extra args straight through to tofu (after a --):
  python provision.py --apply -- -var 'user_count=25'
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
TERRAFORM_DIR = (HERE / ".." / "terraform").resolve()
OUTPUT_DIR = (HERE / ".." / "output").resolve()
MANIFEST = OUTPUT_DIR / "manifest.json"
CREDENTIALS = OUTPUT_DIR / "credentials.md"
RENDER_SCRIPT = HERE / "provision_passwords_and_output.py"

# Remote S3 state is mandatory for the main config (see module docstring). Both
# must exist before `tofu init`: backend.tf activates the S3 backend, backend.hcl
# carries the account-specific partial config. Both are git-ignored; only the
# tracked .example templates live in the repo.
BACKEND_TF = TERRAFORM_DIR / "backend.tf"
BACKEND_HCL = TERRAFORM_DIR / "backend.hcl"

CONSOLE_STEPS = """\
================================================================================
CONSOLE-ONLY STEPS — AWS exposes no stable API for these. Do them by hand.
(Full detail + verification in RUNBOOK.md.)
================================================================================
[ ] Step 2b  Make MFA optional:
             IAM Identity Center -> Settings -> Authentication ->
             Multi-factor authentication -> Configure ->
             Prompt users for MFA -> "Never (disabled)" -> Save.
[ ] Step 3   Enable Kiro:
             Kiro console -> "Onboard your team to Kiro" -> identity source
             = IAM Identity Center -> Enable. COPY the Sign-in URL.
[ ] Step 4   Assign the tier to each group:
             Kiro console -> Users & Groups -> Groups -> Add group ->
             pick the tier (or try: python attempt_kiro_subscription.py --attempt).
[ ] Step 5   Generate a one-time password per user (IdC -> Users -> Reset
             password -> Generate one-time password), save them to
             ../output/otps.csv (header: username,otp), then re-run:
             python provision.py --render-only --sign-in-url <URL> \\
                 --otp-csv ../output/otps.csv
================================================================================
"""

BACKEND_SETUP_HELP = """\
================================================================================
REMOTE S3 STATE IS REQUIRED — set it up once, then re-run (fail closed).
(Full detail in RUNBOOK.md step 1b.)
================================================================================
Why: `tofu destroy` can only delete what is in its STATE. Local state is
git-ignored and does not travel with the repo, so teardown a month later from a
fresh clone would orphan every user, group, and the account instance. State must
live in S3.

Fix (copy-paste), from iac/terraform:

  # 1) Create the state bucket + lock table (one time):
  cd backend-bootstrap
  cp terraform.tfvars.example terraform.tfvars   # set a globally-unique bucket
  mise run backend-bootstrap                      # prompts to approve

  # 2) Activate the backend in the main config:
  cd ..                                           # back in iac/terraform
  mv backend.tf.example backend.tf
  cp backend.hcl.example backend.hcl              # paste values from:
  tofu -chdir=backend-bootstrap output backend_hcl

  # 3) Re-run provisioning (mise handles `tofu init -backend-config=backend.hcl`):
  mise run provision-plan        # or: mise run provision
================================================================================
"""


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--apply", action="store_true",
                   help="Run `tofu apply`. Without it the script does init + plan only (DRY RUN).")
    p.add_argument("--yes", action="store_true",
                   help="Auto-approve the apply (passes -auto-approve to tofu). Requires --apply.")
    p.add_argument("--render-only", action="store_true",
                   help="Skip tofu entirely; just (re)render credentials.md from an existing manifest.")
    p.add_argument("--sign-in-url", default="",
                   help="Kiro/IdC sign-in URL for credentials.md (get it from the Kiro console, step 3).")
    p.add_argument("--otp-csv", type=pathlib.Path, default=None,
                   help="Optional username,otp CSV to embed in credentials.md.")
    p.add_argument("--no-render", action="store_true",
                   help="Do not render credentials.md (just do tofu + manifest export).")
    p.add_argument("tofu_args", nargs="*",
                   help="Extra args forwarded to tofu plan/apply (put them after a --).")
    return p.parse_args(argv)


def _require_tofu() -> str:
    exe = shutil.which("tofu") or shutil.which("terraform")
    if not exe:
        sys.exit("ERROR: neither `tofu` nor `terraform` on PATH. `mise install` first.")
    return exe


def _require_backend() -> None:
    """Fail closed if the mandatory remote S3 backend is not set up.

    The main config MUST init against S3 state. If backend.tf or backend.hcl is
    missing, print the exact fix and exit non-zero rather than silently running
    `tofu init` with local state.
    """
    missing = [p.name for p in (BACKEND_TF, BACKEND_HCL) if not p.exists()]
    if missing:
        print(f"ERROR: remote S3 state not set up — missing in {TERRAFORM_DIR}: "
              f"{', '.join(missing)}")
        print(BACKEND_SETUP_HELP)
        sys.exit(2)


def _run(cmd: list[str], cwd: pathlib.Path) -> int:
    print(f"\n$ {' '.join(cmd)}   (cwd={cwd})")
    return subprocess.run(cmd, cwd=str(cwd)).returncode


def _export_manifest(tofu: str) -> bool:
    """tofu output -json provisioning_manifest > output/manifest.json."""
    print(f"\n$ {tofu} output -json provisioning_manifest > {MANIFEST}")
    proc = subprocess.run(
        [tofu, "output", "-json", "provisioning_manifest"],
        cwd=str(TERRAFORM_DIR), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(proc.stderr.strip() or "failed to read tofu output")
        return False
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(proc.stdout)
    print(f"Wrote {MANIFEST}")
    return True


def _render(sign_in_url: str, otp_csv: pathlib.Path | None) -> int:
    if not MANIFEST.exists():
        print(f"NOTE: {MANIFEST} not found; skipping credentials render. "
              f"Run with --apply first (or export the manifest).")
        return 0
    cmd = [sys.executable, str(RENDER_SCRIPT),
           "--manifest", str(MANIFEST),
           "--out", str(CREDENTIALS)]
    if sign_in_url:
        cmd += ["--sign-in-url", sign_in_url]
    if otp_csv:
        cmd += ["--otp-csv", str(otp_csv)]
    return _run(cmd, cwd=HERE)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    passthrough = [a for a in args.tofu_args if a != "--"]

    # Render-only short-circuit (no tofu).
    if args.render_only:
        rc = _render(args.sign_in_url, args.otp_csv)
        print(CONSOLE_STEPS)
        return rc

    tofu = _require_tofu()
    _require_backend()

    print("=" * 72)
    print("Kiro IdC provisioning entrypoint")
    print("=" * 72)
    print(f"Terraform dir: {TERRAFORM_DIR}")
    print(f"Mode:          {'APPLY' if args.apply else 'DRY RUN (plan only)'}")
    print()
    print("Reminder: Step 0 (org management account: permit member-account IdC "
          "instances) must already be done, or `apply` will be denied.")
    print("Reminder: remote S3 state is required and set up once via the "
          "backend-bootstrap step (RUNBOOK step 1b); init uses backend.hcl.")

    if _run([tofu, "init", "-input=false", "-backend-config=backend.hcl"],
            TERRAFORM_DIR) != 0:
        return 1

    if _run([tofu, "plan"] + passthrough, TERRAFORM_DIR) != 0:
        return 1

    if not args.apply:
        print("\nDRY RUN complete — nothing created. Re-run with --apply to create resources.")
        print(CONSOLE_STEPS)
        return 0

    apply_cmd = [tofu, "apply"] + passthrough
    if args.yes:
        apply_cmd.append("-auto-approve")
    if _run(apply_cmd, TERRAFORM_DIR) != 0:
        return 1

    if not _export_manifest(tofu):
        return 1

    if not args.no_render:
        _render(args.sign_in_url, args.otp_csv)

    print("\nIaC steps done: IdC instance + users + groups + memberships created.")
    print(CONSOLE_STEPS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
