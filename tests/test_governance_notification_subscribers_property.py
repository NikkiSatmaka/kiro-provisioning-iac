"""Property 3: every notification email is subscribed notify-only on every budget.

Feature: workshop-account-governance, Property 3: every notification email is
subscribed notify-only on every budget
Validates: Requirements 8.3

Property 3: *For any* non-empty ``var.notification_emails`` list and any supplied
account, that account's ``aws_budgets_budget`` renders a **notify-only**
notification whose email-subscriber set equals the full ``notification_emails``
list — so no configured recipient is omitted from any per-account budget, and
the breach notification carries no action of its own (the freeze is the separate
``aws_budgets_budget_action``, not a subscriber on the notification).

Why a rendered plan, not a text scan. The subscriber set is produced by the
provider from ``subscriber_email_addresses = var.notification_emails`` under a
``for_each`` over the account set; the only way to assert the *rendered*
per-instance result over varied inputs is to plan the stack and read
``tofu show -json``. A regression that sliced the list (e.g. ``[0]``), rendered
the notification per-provider-default, or dropped the required notification on
some account instance fails here.

Offline harness. The governance stack targets the live Organizations management
account, so a real plan needs credentials and network. This suite stays offline
and non-mutating:

  * the stack is copied to a throwaway dir with ``backend.tf`` dropped, so
    ``tofu init -backend=false`` initializes locally from the committed lock;
  * ``providers.tf`` is replaced with a mock-credential, skip-everything aws
    provider so no STS/SSO/metadata call happens at plan time. The real
    ``providers.tf`` declares ``data.aws_region.current`` for region reporting,
    but no resource in the current stack references it (the SCP policy objects
    and the budgets execution role, which once read ``data.aws_caller_identity``,
    now live in foundation/ and are consumed here by variable), so the stub
    needs to redeclare nothing. The rendered budget notifications are therefore
    identical to a real plan's.

No ``tofu apply`` ever runs: the property reads a saved plan file only.

The tofu-backed test skips cleanly when no ``tofu`` binary is on PATH.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parent.parent
GOVERNANCE_TF_DIR = REPO_ROOT / "governance" / "terraform"

# The mock-credential, skip-everything provider. This REPLACES the real
# providers.tf in the throwaway copy only. No resource in the current governance
# stack reads a data source (the SCP policy objects + budgets role that once
# read data.aws_caller_identity now live in foundation/ and are consumed here by
# variable), so the stub redeclares nothing beyond the provider itself.
_TEST_PROVIDERS_TF = """\
# TEST-ONLY provider override (offline plan harness) — not the real stack.
provider "aws" {
  region                      = "us-east-1"
  access_key                  = "mock_access_key_id"
  secret_key                  = "mock_secret_access_key"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true

  default_tags {
    tags = var.default_tags
  }
}
"""


def _tofu_available() -> bool:
    return shutil.which("tofu") is not None


requires_tofu = pytest.mark.skipif(
    not _tofu_available(), reason="tofu binary not on PATH"
)


@lru_cache(maxsize=1)
def _initialized_tf_dir() -> Path:
    """Copy the governance stack to a temp dir and init it offline, once.

    Drops the S3 backend so ``tofu init -backend=false`` stays local and swaps
    in the mock provider. Cached for the session so every planned example reuses
    the one init (plan is the per-example cost).
    """
    tmp = Path(tempfile.mkdtemp(prefix="governance-prop3-"))
    for tf in GOVERNANCE_TF_DIR.glob("*.tf"):
        shutil.copy(tf, tmp / tf.name)
    lock = GOVERNANCE_TF_DIR / ".terraform.lock.hcl"
    if lock.exists():
        shutil.copy(lock, tmp / lock.name)

    # Local, offline init: no remote backend.
    (tmp / "backend.tf").unlink(missing_ok=True)

    # Mock provider in place of the real providers.tf. The current stack reads
    # no data source, so there is nothing to repoint — the mutated copy differs
    # from the real stack only by the provider override above.
    (tmp / "providers.tf").write_text(_TEST_PROVIDERS_TF)

    subprocess.run(
        ["tofu", "init", "-backend=false", "-input=false", "-no-color"],
        cwd=tmp,
        check=True,
        capture_output=True,
        text=True,
    )
    return tmp


# AWS env vars are cleared for the plan so a developer's ambient profile / SSO
# session is never consulted — the mock provider is the only credential source.
_CLEAN_AWS_ENV = {
    "AWS_PROFILE": None,
    "AWS_REGION": None,
    "AWS_DEFAULT_REGION": None,
    "AWS_ACCESS_KEY_ID": None,
    "AWS_SECRET_ACCESS_KEY": None,
    "AWS_SESSION_TOKEN": None,
    "AWS_SDK_LOAD_CONFIG": None,
    "AWS_CONFIG_FILE": None,
    "AWS_SHARED_CREDENTIALS_FILE": None,
}


def _plan_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    for k in _CLEAN_AWS_ENV:
        env.pop(k, None)
    return env


def _hcl_list(values: list[str]) -> str:
    inner = ", ".join('"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"' for v in values)
    return "[" + inner + "]"


def _plan_budgets(account_ids: list[str], notification_emails: list[str]) -> dict:
    """Plan the stack over the given inputs offline; return planned budgets.

    Writes a tfvars file, runs ``tofu plan -out`` with no refresh/lock, then
    ``tofu show -json`` and extracts every planned ``aws_budgets_budget.account``
    instance keyed by its account id. No apply, ever.
    """
    tf_dir = _initialized_tf_dir()
    tfvars = (
        'workshop_id         = "demo"\n'
        'parent_id           = "r-abcd"\n'
        f"account_ids         = {_hcl_list(account_ids)}\n"
        f"notification_emails = {_hcl_list(notification_emails)}\n"
        "budget_limit_amount = 100\n"
    )
    var_path = tf_dir / "prop3.auto.tfvars"
    plan_path = tf_dir / "prop3.plan.bin"
    var_path.write_text(tfvars)
    try:
        plan = subprocess.run(
            [
                "tofu", "plan", "-input=false", "-no-color",
                "-lock=false", "-refresh=false",
                f"-var-file={var_path.name}", f"-out={plan_path.name}",
            ],
            cwd=tf_dir, env=_plan_env(), capture_output=True, text=True, check=False,
        )
        assert plan.returncode == 0, (
            f"tofu plan failed for emails={notification_emails} "
            f"accounts={account_ids}:\n{plan.stdout}\n{plan.stderr}"
        )
        show = subprocess.run(
            ["tofu", "show", "-json", plan_path.name],
            cwd=tf_dir, env=_plan_env(), capture_output=True, text=True, check=False,
        )
        assert show.returncode == 0, f"tofu show -json failed:\n{show.stderr}"
        doc = json.loads(show.stdout)
    finally:
        var_path.unlink(missing_ok=True)
        plan_path.unlink(missing_ok=True)

    budgets: dict[str, dict] = {}
    resources = (
        doc.get("planned_values", {})
        .get("root_module", {})
        .get("resources", [])
    )
    for rc in resources:
        if rc.get("type") == "aws_budgets_budget" and rc.get("name") == "account":
            budgets[rc["index"]] = rc["values"]
    return budgets


# --- Strategies -------------------------------------------------------------

# 12-digit AWS account ids, drawn unique per set so each budget instance is
# distinguishable and a per-account omission would be unambiguous.
_account_ids = st.text(alphabet="0123456789", min_size=12, max_size=12)
_account_set = st.lists(_account_ids, min_size=1, max_size=3, unique=True)

# Notification emails: simple local@domain shapes over a safe alphabet. The
# property is about set equality of the rendered subscribers, so the exact
# address text matters only in that it round-trips; drawn unique and non-empty
# to match the ``length > 0`` variable validation.
_email_local = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789.-_",
    min_size=1, max_size=12,
).filter(lambda s: s.strip() != "")
_emails = st.lists(
    st.builds(lambda u: f"{u}@example.com", _email_local),
    min_size=1, max_size=4, unique=True,
)


@requires_tofu
@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
# Representative shapes always exercised: a single email, several emails, a
# single account, and a multi-account set.
@example(account_ids=["111111111111"], notification_emails=["only@example.com"])
@example(
    account_ids=["111111111111", "222222222222", "333333333333"],
    notification_emails=["a@example.com", "b@example.com", "c@example.com"],
)
@given(account_ids=_account_set, notification_emails=_emails)
def test_every_email_subscribed_notify_only_on_every_budget(account_ids, notification_emails):
    """Each account's budget renders a notify-only notification whose email
    subscriber set equals the full notification_emails list.

    Feature: workshop-account-governance, Property 3: every notification email
    is subscribed notify-only on every budget
    Validates: Requirements 8.3
    """
    assume(len(set(notification_emails)) == len(notification_emails))

    budgets = _plan_budgets(account_ids, notification_emails)

    # Every supplied account yields exactly one budget instance (no account is
    # left without one, no extra instances appear).
    assert set(budgets.keys()) == set(account_ids), (
        f"planned budget instances {sorted(budgets)} != supplied accounts "
        f"{sorted(account_ids)}"
    )

    expected = set(notification_emails)
    for account_id, values in budgets.items():
        notifications = values.get("notification") or []
        assert notifications, (
            f"account {account_id}: budget has no notification block; a breach "
            f"must never be silent (Requirement 8.3)"
        )

        # The required notify-only notification at the freeze threshold must be
        # present: its email-subscriber set equals the full list.
        matching = [
            n for n in notifications
            if set(n.get("subscriber_email_addresses") or []) == expected
        ]
        assert matching, (
            f"account {account_id}: no notification subscribes the full email "
            f"set {sorted(expected)}; rendered notifications="
            f"{json.dumps(notifications)}"
        )

        # Notify-only: EVERY notification on the budget is a plain notification
        # with no SNS escalation and no action embedded — the freeze is a
        # separate aws_budgets_budget_action, never a subscriber here.
        for n in notifications:
            assert not (n.get("subscriber_sns_topic_arns") or []), (
                f"account {account_id}: notification carries an SNS subscriber; "
                f"the budget notification must be notify-only (email only)"
            )
            # No notification key names an action/linked SCP — the schema has no
            # such field, so its presence would signal a non-notify-only block.
            assert "action" not in n and "scp" not in json.dumps(n).lower(), (
                f"account {account_id}: notification appears to embed an action; "
                f"it must be notify-only"
            )
            # Soundness: the subscriber set is exactly the configured list for
            # every notification on the budget (no stray/omitted recipient on an
            # extra threshold either).
            assert set(n.get("subscriber_email_addresses") or []) == expected, (
                f"account {account_id}: a notification's subscribers "
                f"{sorted(n.get('subscriber_email_addresses') or [])} != the full "
                f"configured list {sorted(expected)}"
            )
