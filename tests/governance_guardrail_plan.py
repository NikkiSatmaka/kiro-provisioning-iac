"""Drive the governance stack's Kiro guardrail SCP rendering offline.

Feature: workshop-account-governance, Property 1: Guardrail renders exactly the
supplied allowlist

This harness renders ``governance/terraform`` with ``tofu plan`` over a given
``kiro_allowed_actions`` list and returns the planned
``aws_organizations_policy.kiro_guardrail.content`` — the fully rendered SCP
JSON document — so Property 1 can assert the guardrail is a single ``Allow``
whose action set equals exactly the supplied allowlist and grants nothing
outside it (Requirements 4.3, 4.4).

Why a plan works fully offline here:
the guardrail is ``data.aws_iam_policy_document.kiro_guardrail`` feeding
``aws_organizations_policy.kiro_guardrail.content``. A policy document renders
entirely at plan time — ``content`` is a KNOWN value, not known-after-apply — so
there is nothing to wait for an apply to resolve. We read it straight off the
planned resource values.

Offline-ness mirrors the sibling Property 2 harness
(``governance_budget_action_plan``): the live ``providers.tf`` reads
``data.aws_caller_identity`` / ``data.aws_region`` and the account placements use
``aws_organizations_account`` — all needing credentials/network at plan. The
harness swaps ``providers.tf`` for a credential-free stub (static dummy creds +
skip_* flags) backed by an in-process mock STS, and drops ``organizations.tf``
so the plan never reads live data or imports real accounts. Nothing here is
copied back into the real stack; it is a throwaway rendering lens over the
committed ``scps.tf``.
"""

from __future__ import annotations

import atexit
import json
import shutil
import subprocess
import tempfile
import threading
import uuid
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GOVERNANCE_TF_DIR = REPO_ROOT / "governance" / "terraform"

# A fixed management-account id the mock STS returns for GetCallerIdentity. Its
# value is irrelevant to Property 1 (which is about the guardrail allowlist); it
# only has to be a well-formed 12-digit id so budgets.tf's trust-policy data
# source resolves offline.
_STUB_ACCOUNT_ID = "999999999999"

# Credential-free aws provider that points STS at a local mock. Replaces the
# real providers.tf for the plan. Static dummy creds plus the skip_* flags
# remove every network dependency EXCEPT the one data.aws_caller_identity read
# that budgets.tf's trust policy needs — served by the in-process mock STS at
# var._sts_endpoint. The STS endpoint is a VARIABLE so the harness dir can be
# initialized once and reused across many plans (each plan spins up a fresh mock
# on an ephemeral port). The real providers.tf's two data sources are redeclared
# so scps.tf/budgets.tf are used byte-for-byte unchanged.
_STUB_PROVIDER_TF = """\
variable "_sts_endpoint" {
  type = string
}

provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true

  endpoints {
    sts = var._sts_endpoint
  }
}

# Redeclared from the real providers.tf (removed in the harness) so budgets.tf's
# trust policy reference, data.aws_caller_identity.current.account_id, resolves.
# The mock STS answers GetCallerIdentity; data.aws_region reads from the static
# region above (no network).
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
"""

# Throwaway OU stand-in so scps.tf's guardrail attachment resolves after
# organizations.tf (account placement) is dropped. No account placement here, so
# planning touches nothing live. The attributes mirror the real OU resource;
# only its presence (not its values) matters to Property 1.
_HARNESS_OVERRIDES_TF = """\
resource "aws_organizations_organizational_unit" "workshop" {
  name      = "workshop-${var.workshop_id}"
  parent_id = var.parent_id
}
"""


class _MockSTS(BaseHTTPRequestHandler):
    """Answer the single GetCallerIdentity the plan makes with a canned id."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        body = (
            '<GetCallerIdentityResponse '
            'xmlns="https://sts.amazonaws.com/doc/2011-06-15/">'
            "<GetCallerIdentityResult>"
            f"<Arn>arn:aws:iam::{_STUB_ACCOUNT_ID}:root</Arn>"
            f"<UserId>{_STUB_ACCOUNT_ID}</UserId>"
            f"<Account>{_STUB_ACCOUNT_ID}</Account>"
            "</GetCallerIdentityResult>"
            "<ResponseMetadata><RequestId>stub</RequestId></ResponseMetadata>"
            "</GetCallerIdentityResponse>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence the handler's stderr logging
        pass


def _start_mock_sts() -> tuple[HTTPServer, str]:
    """Start the mock STS on an ephemeral localhost port; return (server, url)."""
    server = HTTPServer(("127.0.0.1", 0), _MockSTS)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def tofu_available() -> bool:
    """True when a ``tofu`` binary is on PATH (plan-backed tests skip if not)."""
    return shutil.which("tofu") is not None


@lru_cache(maxsize=1)
def _initialized_harness_dir() -> Path:
    """Build + init a throwaway, credential-free copy of the governance stack ONCE.

    Copies the committed ``*.tf``, drops the remote backend and the live-only
    bits (``organizations.tf`` account placement, the data-source-reading
    ``providers.tf``), and swaps in a static provider stub (STS endpoint supplied
    as a variable at plan time) plus a stub OU the guardrail attachment needs.
    The result plans fully offline while leaving ``scps.tf`` — the code under
    test — byte-for-byte unchanged.

    Cached for the test session: ``tofu init`` (the slow provider-link step)
    runs once, and each per-example plan reuses this directory's ``.terraform``
    with a different ``-var-file`` and STS endpoint. ``tofu plan`` does not
    mutate the directory, so reuse is safe across examples.
    """
    tmp = Path(tempfile.mkdtemp(prefix="gov-prop1-"))
    for tf in GOVERNANCE_TF_DIR.glob("*.tf"):
        shutil.copy(tf, tmp / tf.name)
    lock = GOVERNANCE_TF_DIR / ".terraform.lock.hcl"
    if lock.exists():
        shutil.copy(lock, tmp / lock.name)

    # Remote S3 backend -> local/offline init.
    (tmp / "backend.tf").unlink(missing_ok=True)
    # Account placement reads/imports live accounts; irrelevant to Property 1.
    (tmp / "organizations.tf").unlink(missing_ok=True)
    # The real providers.tf reads live data sources; replace with the static
    # stub (which redeclares those data sources and points STS at a var).
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


def _sample_tfvars(allowed_actions: list[str]) -> str:
    """Minimal valid tfvars for a plan over the given guardrail allowlist."""
    actions = ", ".join(f'"{a}"' for a in allowed_actions)
    return (
        'workshop_id          = "harness"\n'
        'parent_id            = "r-stub"\n'
        'account_ids          = ["111111111111"]\n'
        'notification_emails  = ["ops@example.com"]\n'
        "budget_limit_amount  = 100\n"
        f"kiro_allowed_actions = [{actions}]\n"
    )


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
    server, sts_endpoint = _start_mock_sts()
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
                f"-var=_sts_endpoint={sts_endpoint}",
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
        server.shutdown()
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
        "scps.tf may have changed."
    )
