"""Drive the governance stack's budget-action freeze targeting offline.

Feature: workshop-account-governance, Property 2: Each budget action freezes
only its own account

This harness renders ``governance/terraform`` with ``tofu plan`` over a
multi-account ``account_ids`` set and returns, per planned
``aws_budgets_budget_action.freeze`` instance, the concrete
``scp_action_definition`` the plan computed:
``{ account_key -> {"target_ids": [...], "references_freeze_policy": bool,
"references_execution_role": bool} }``.

Property 2 asserts every action's ``scp_action_definition.target_ids`` equals
exactly the singleton list of its *own* account id — never the workshop OU id,
never another account's id — and that every action references the freeze policy
and the budgets execution role (Requirements 7.4, 7.5).

Why a plan (not a pure-function mirror):
``aws_budgets_budget_action.freeze`` references ids/arns that are only known
after apply (the freeze ``policy_id``, the execution-role arn, the budget
``name``). ``target_ids = [each.key]`` is, however, a literal derived from the
``for_each`` key, so it is a KNOWN value at plan time: the planned resource
values carry concrete ``target_ids`` per instance even while the surrounding
references are "known after apply". We read those planned values directly.

Offline-ness: the account placements in ``organizations.tf`` use
``aws_organizations_account`` (live reads/imports), and the live
``providers.tf`` sets a management-account profile. The harness drops
``organizations.tf`` and swaps ``providers.tf`` for a credential-free stub
(static dummy creds + skip_* flags). The current ``budgets.tf`` reads no data
source — the budgets execution role and the freeze SCP it once resolved via
``data.aws_caller_identity`` now live in foundation/ and are consumed here as
``var.budgets_execution_role_arn`` / ``var.freeze_scp_id`` — so the stub
redeclares nothing and no mock STS is needed. Nothing here is copied back into
the real stack; it is a throwaway rendering lens over the committed
``budgets.tf``.
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
GOVERNANCE_TF_DIR = REPO_ROOT / "governance" / "terraform"

# Credential-free aws provider. Replaces the real providers.tf for the plan.
# Static dummy creds plus the skip_* flags remove every network dependency. The
# current budgets.tf reads no data source (the budgets role + freeze SCP it once
# resolved via data.aws_caller_identity moved to foundation/ and are consumed
# here by variable), so the stub redeclares nothing and needs no mock STS.
_STUB_PROVIDER_TF = """\
provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
}
"""


def tofu_available() -> bool:
    """True when a ``tofu`` binary is on PATH (plan-backed tests skip if not)."""
    return shutil.which("tofu") is not None


# Throwaway OU stand-in so scps.tf's guardrail attachment resolves after
# organizations.tf (account placement) is dropped. No account placement here, so
# planning touches nothing live. The attributes mirror the real OU resource;
# only its presence (not its values) matters to Property 2.
_HARNESS_OVERRIDES_TF = """\
resource "aws_organizations_organizational_unit" "workshop" {
  name      = "workshop-${var.workshop_id}"
  parent_id = var.parent_id
}
"""


@lru_cache(maxsize=1)
def _initialized_harness_dir() -> Path:
    """Build + init a throwaway, credential-free copy of the governance stack ONCE.

    Copies the committed ``*.tf``, drops the remote backend and the live-only
    bits (``organizations.tf`` account placement, the profile-bound
    ``providers.tf``), and swaps in a static provider stub plus a stub OU the
    guardrail attachment needs. The result plans fully offline while leaving
    ``budgets.tf`` — the code under test — byte-for-byte unchanged.

    Cached for the test session: ``tofu init`` (the slow provider-link step)
    runs once, and each per-example plan reuses this directory's ``.terraform``
    with a different ``-var-file``. ``tofu plan`` does not mutate the directory,
    so reuse is safe across examples.
    """
    tmp = Path(tempfile.mkdtemp(prefix="gov-prop2-"))
    for tf in GOVERNANCE_TF_DIR.glob("*.tf"):
        shutil.copy(tf, tmp / tf.name)
    lock = GOVERNANCE_TF_DIR / ".terraform.lock.hcl"
    if lock.exists():
        shutil.copy(lock, tmp / lock.name)

    # Remote S3 backend -> local/offline init.
    (tmp / "backend.tf").unlink(missing_ok=True)
    # Account placement reads/imports live accounts; irrelevant to Property 2.
    (tmp / "organizations.tf").unlink(missing_ok=True)
    # The real providers.tf binds a management-account profile; replace with
    # the static credential-free stub (no data sources, no STS).
    (tmp / "providers.tf").write_text(_STUB_PROVIDER_TF)
    # Stub OU so scps.tf's guardrail attachment resolves without placement.
    (tmp / "_harness_overrides.tf").write_text(_HARNESS_OVERRIDES_TF)

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


def _sample_tfvars(account_ids: list[str]) -> str:
    """Minimal valid tfvars for a plan over the given multi-account set."""
    ids = ", ".join(f'"{a}"' for a in account_ids)
    return (
        'workshop_id         = "harness"\n'
        'parent_id           = "r-stub"\n'
        f"account_ids         = [{ids}]\n"
        'notification_emails = ["ops@example.com"]\n'
        "budget_limit_amount = 100\n"
    )


def plan_budget_action_targets(account_ids: list[str]) -> dict[str, dict]:
    """Plan the stack and return each freeze action's planned scp definition.

    Returns a map keyed by account id:
        {
          "<account_id>": {
            "target_ids": [...],                 # planned scp_action_definition.target_ids
            "references_freeze_policy": bool,     # policy_id is a ref (known-after-apply)
            "references_execution_role": bool,    # execution_role_arn is a ref
          },
          ...
        }
    """
    tmp = _initialized_harness_dir()
    # Unique per-call file names so concurrent/sequential plans in the shared
    # cached dir never clobber each other.
    token = uuid.uuid4().hex
    tfvars = tmp / f"harness-{token}.tfvars"
    plan_bin = tmp / f"plan-{token}.tfplan"
    try:
        tfvars.write_text(_sample_tfvars(account_ids))
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
        result = _extract_freeze_targets(plan)
        config_refs = _extract_config_references(plan)
        for facts in result.values():
            facts.update(config_refs)
        return result
    finally:
        tfvars.unlink(missing_ok=True)
        plan_bin.unlink(missing_ok=True)


def _extract_freeze_targets(plan: dict) -> dict[str, dict]:
    """Pull scp_action_definition facts out of the planned resource values.

    Walks ``resource_changes`` for ``aws_budgets_budget_action.freeze`` entries;
    each entry's ``index`` is the ``for_each`` key (the account id) and its
    ``change.after`` carries the planned ``definition[0].scp_action_definition``.
    ``policy_id`` / ``execution_role_arn`` are known-after-apply (they reference
    other resources), so they land in ``after_unknown`` rather than ``after`` —
    we report their presence there as "references the freeze policy / role".
    """
    out: dict[str, dict] = {}
    for rc in plan.get("resource_changes", []):
        if rc.get("type") != "aws_budgets_budget_action":
            continue
        if rc.get("name") != "freeze":
            continue
        account_key = rc.get("index")
        after = rc.get("change", {}).get("after") or {}
        after_unknown = rc.get("change", {}).get("after_unknown") or {}

        target_ids = _dig_scp(after, "target_ids")
        # execution_role_arn lives on the action, not inside scp_action_definition.
        role_known = after.get("execution_role_arn") is not None
        role_unknown = bool(after_unknown.get("execution_role_arn"))

        policy_known = _dig_scp(after, "policy_id") is not None
        policy_unknown = _dig_scp_unknown(after_unknown, "policy_id")

        out[account_key] = {
            "target_ids": target_ids,
            "references_freeze_policy": policy_known or policy_unknown,
            "references_execution_role": role_known or role_unknown,
        }
    return out


def _extract_config_references(plan: dict) -> dict:
    """Pull the freeze action's config-level reference expressions from the plan.

    ``policy_id`` and ``execution_role_arn`` are known-after-apply, so the
    planned *values* can't prove WHICH policy/role they point at. The plan's
    ``configuration`` section records the reference expressions, so we assert the
    wiring there:

        {
          "policy_id_references":  [...],   # should include aws_organizations_policy.freeze
          "role_references":       [...],   # should include aws_iam_role.budgets_execution
          "target_ids_references": [...],   # should be ["each.key"]
        }

    These are per-resource (not per-instance) because ``for_each`` resources
    share one config block, which is exactly what Property 2 needs: the single
    block uses ``each.key`` and the freeze policy/role for every instance.
    """
    resources = (
        plan.get("configuration", {})
        .get("root_module", {})
        .get("resources", [])
    )
    for r in resources:
        if r.get("type") != "aws_budgets_budget_action" or r.get("name") != "freeze":
            continue
        expr = r.get("expressions", {})
        role_refs = (expr.get("execution_role_arn") or {}).get("references", [])
        definition = expr.get("definition") or [{}]
        scp = (definition[0].get("scp_action_definition") or [{}])[0]
        policy_refs = (scp.get("policy_id") or {}).get("references", [])
        target_refs = (scp.get("target_ids") or {}).get("references", [])
        return {
            "policy_id_references": policy_refs,
            "role_references": role_refs,
            "target_ids_references": target_refs,
        }
    return {
        "policy_id_references": [],
        "role_references": [],
        "target_ids_references": [],
    }


def _dig_scp(after: dict, field: str):
    """Return definition[0].scp_action_definition[0][field] from planned values."""
    definition = after.get("definition")
    if not definition:
        return None
    scp = definition[0].get("scp_action_definition")
    if not scp:
        return None
    return scp[0].get(field)


def _dig_scp_unknown(after_unknown: dict, field: str) -> bool:
    """True when definition[].scp_action_definition[][field] is known-after-apply."""
    definition = after_unknown.get("definition")
    if not definition or not isinstance(definition, list):
        return False
    scp = definition[0].get("scp_action_definition") if isinstance(definition[0], dict) else None
    if not scp or not isinstance(scp, list):
        return False
    return bool(scp[0].get(field))
