"""Drive the foundation stack's Kiro guardrail SCP rendering offline.

Feature: workshop-account-governance, Property 1: Guardrail renders exactly the
supplied allowlist

This harness renders ``foundation/terraform`` with ``tofu plan`` over a given
``kiro_allowed_actions`` list and returns the planned
``aws_organizations_policy.kiro_guardrail.content`` — the fully rendered SCP
JSON document — so Property 1 can assert the guardrail is a single ``Allow``
whose action set equals exactly the supplied allowlist and grants nothing
outside it (Requirements 4.3, 4.4).

Where the guardrail lives now: the Kiro guardrail SCP *policy object*
(``data.aws_iam_policy_document.kiro_guardrail`` feeding
``aws_organizations_policy.kiro_guardrail.content``) is a
once-per-management-account singleton owned by ``foundation/``. The
``governance/`` stack only ATTACHES that shared policy to each workshop OU
(``aws_organizations_policy_attachment.kiro_guardrail``, consuming
``var.kiro_guardrail_scp_id``) and no longer renders the document. So the
allowlist-rendering property is planned against foundation, where the document
is produced.

Why a plan works fully offline here:
a policy document renders entirely at plan time — ``content`` is a KNOWN value,
not known-after-apply — so there is nothing to wait for an apply to resolve. We
read it straight off the planned resource values.

Offline-ness: foundation's live-only reads are isolated to
``identity_center.tf`` (``data.aws_ssoadmin_instances``) and ``budgets_role.tf``
(``data.aws_caller_identity`` + the IAM role), neither of which feeds the
guardrail document. The harness drops both (plus ``outputs.tf``, which
references their resources) and swaps ``providers.tf`` for a credential-free
stub with static dummy creds + skip_* flags, so the plan needs no credentials or
network. ``scps.tf`` — the code under test — is left byte-for-byte unchanged.
Nothing here is copied back into the real stack; it is a throwaway rendering
lens over the committed ``foundation/terraform/scps.tf``.
"""

from __future__ import annotations

import atexit
import json
import shutil
import subprocess
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FOUNDATION_TF_DIR = REPO_ROOT / "foundation" / "terraform"

# Credential-free aws provider. Replaces the real providers.tf for the plan.
# Static dummy creds plus the skip_* flags remove every network dependency; the
# guardrail document renders from var.kiro_allowed_actions alone, so no STS /
# caller-identity read is needed (unlike the pre-refactor governance harness,
# whose budgets trust policy read data.aws_caller_identity). The real
# providers.tf also declares data.aws_region.current, redeclared here so any
# residual reference resolves without a metadata call.
_STUB_PROVIDER_TF = """\
provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
}

# Redeclared from the real providers.tf (removed in the harness) so any
# data.aws_region.current reference resolves from the static region above
# (no metadata call).
data "aws_region" "current" {}
"""


def tofu_available() -> bool:
    """True when a ``tofu`` binary is on PATH (plan-backed tests skip if not)."""
    return shutil.which("tofu") is not None


@lru_cache(maxsize=1)
def _initialized_harness_dir() -> Path:
    """Build + init a throwaway, credential-free copy of the foundation stack ONCE.

    Copies the committed ``*.tf``, drops the remote backend and the live-only
    reads that do not feed the guardrail document (``identity_center.tf``,
    ``budgets_role.tf``, and ``outputs.tf`` which references their resources),
    and swaps in a static provider stub. The result plans fully offline while
    leaving ``scps.tf`` — the code under test — byte-for-byte unchanged.

    Cached for the test session: ``tofu init`` (the slow provider-link step)
    runs once, and each per-example plan reuses this directory's ``.terraform``
    with a different ``-var-file``. ``tofu plan`` does not mutate the directory,
    so reuse is safe across examples.
    """
    tmp = Path(tempfile.mkdtemp(prefix="gov-prop1-"))
    for tf in FOUNDATION_TF_DIR.glob("*.tf"):
        shutil.copy(tf, tmp / tf.name)
    lock = FOUNDATION_TF_DIR / ".terraform.lock.hcl"
    if lock.exists():
        shutil.copy(lock, tmp / lock.name)

    # Remote S3 backend -> local/offline init.
    (tmp / "backend.tf").unlink(missing_ok=True)
    # Live-only reads that do NOT feed the guardrail document:
    #   identity_center.tf -> data.aws_ssoadmin_instances (needs the org API)
    #   budgets_role.tf     -> data.aws_caller_identity (needs STS) + the role
    # Drop both, and outputs.tf which references their resources/locals.
    (tmp / "identity_center.tf").unlink(missing_ok=True)
    (tmp / "budgets_role.tf").unlink(missing_ok=True)
    (tmp / "outputs.tf").unlink(missing_ok=True)
    # The real providers.tf reads data.aws_region; replace with the static stub
    # (which redeclares that data source and needs no credentials/network).
    (tmp / "providers.tf").write_text(_STUB_PROVIDER_TF)

    subprocess.run(
        ["tofu", "init", "-backend=false", "-input=false", "-no-color"],
        cwd=tmp,
        check=True,
        capture_output=True,
        text=True,
    )
    # Remove the session-cached harness dir at interpreter exit so test runs
    # leave no throwaway directories behind.
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    return tmp


def _sample_tfvars(allowed_actions: list[str]) -> str:
    """Minimal valid tfvars for a plan over the given guardrail allowlist."""
    actions = ", ".join(f'"{a}"' for a in allowed_actions)
    return f"kiro_allowed_actions = [{actions}]\n"


def plan_guardrail_document(allowed_actions: list[str]) -> dict:
    """Plan the stack and return the rendered guardrail SCP document.

    Returns the parsed JSON of ``aws_organizations_policy.kiro_guardrail.content``
    — a policy document shaped like::

        {"Version": "2012-10-17", "Statement": [{"Sid": ..., "Effect": "Allow",
         "Action": [...], "Resource": "*"}]}

    ``content`` is a KNOWN value at plan time (a policy document renders fully
    offline), so this reads straight off the planned resource values.
    """
    tmp = _initialized_harness_dir()
    # Unique per-call file names so sequential plans in the shared cached dir
    # never clobber each other.
    token = uuid.uuid4().hex
    tfvars = tmp / f"harness-{token}.tfvars"
    plan_bin = tmp / f"plan-{token}.tfplan"
    try:
        tfvars.write_text(_sample_tfvars(allowed_actions))
        subprocess.run(
            [
                "tofu", "plan", "-no-color", "-input=false",
                f"-var-file={tfvars.name}", f"-out={plan_bin.name}",
            ],
            cwd=tmp,
            check=True,
            capture_output=True,
            text=True,
        )
        shown = subprocess.run(
            ["tofu", "show", "-json", plan_bin.name],
            cwd=tmp,
            check=True,
            capture_output=True,
            text=True,
        )
        plan = json.loads(shown.stdout)
        return _extract_guardrail_document(plan)
    finally:
        tfvars.unlink(missing_ok=True)
        plan_bin.unlink(missing_ok=True)


def _extract_guardrail_document(plan: dict) -> dict:
    """Pull the planned guardrail SCP ``content`` JSON out of the plan.

    Walks ``planned_values`` for the single
    ``aws_organizations_policy.kiro_guardrail`` resource and parses its
    ``content`` string (the SCP always carries a concrete, known content).
    """
    resources = (
        plan.get("planned_values", {})
        .get("root_module", {})
        .get("resources", [])
    )
    for r in resources:
        if r.get("type") != "aws_organizations_policy":
            continue
        if r.get("name") != "kiro_guardrail":
            continue
        content = (r.get("values") or {}).get("content")
        if not content:
            raise AssertionError(
                "aws_organizations_policy.kiro_guardrail has no planned 'content'; "
                "the guardrail document did not render at plan time."
            )
        return json.loads(content)
    raise AssertionError(
        "aws_organizations_policy.kiro_guardrail not found in the plan; "
        "foundation/terraform/scps.tf may have changed."
    )
