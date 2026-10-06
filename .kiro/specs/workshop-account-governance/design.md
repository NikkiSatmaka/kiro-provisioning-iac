# Design Document

## Overview

The **Governance stack** is a new, standalone, **management-account-scoped**
OpenTofu stack at a new top-level `governance/` directory. It mirrors the
layout and conventions of the existing `foundation/`, `subscription/`, and
`claim-service/` stacks — a `terraform/` subdirectory plus `README.md` and
`RUNBOOK.md` — but differs in one defining way: it runs under
**management-account or delegated Organizations-admin credentials**, not the
member-account profile the other stacks use.

For a set of AWS accounts that are **already created and invited into the
organization externally**, the stack, per workshop:

1. creates exactly one Organizational Unit (OU), `workshop-<workshop_id>`, under
   a caller-supplied parent (`var.parent_id`);
2. places that workshop's pre-existing accounts into the OU;
3. attaches a **Kiro-only guardrail SCP** (a deny-by-default allowlist built from
   `var.kiro_allowed_actions`) to the OU;
4. creates a **deny-all freeze SCP** that is left **unattached** at apply time;
   and
5. attaches a **per-account budget** whose breach **automatically** attaches the
   freeze SCP to the breaching account, via an AWS Budgets execution role scoped
   to Organizations attach/detach.

The stack **never creates or invites accounts** (Requirement 1) and provides
**no un-freeze automation** — recovery is a documented manual detach in the
RUNBOOK (Requirement 15).

It reuses the shared S3 state backend created by the `backend/` stack, under the
workshop-namespaced key
`workshops/<WORKSHOP_ID>/governance/terraform.tfstate` (Requirement 9).

**Dominant language:** HCL / OpenTofu. All code examples below are HCL or the
POSIX shell used by the existing `mise` tasks.

**Verification constraint.** This is a planning / IaC-authoring exercise.
Verification is limited to `tofu fmt`, `tofu validate`, and `tofu plan`
(Requirement 16). Applying mutates the live AWS Organizations management account
(high blast radius) and happens only with the operator's explicit go-ahead.

### Scope

| In scope | Out of scope |
| --- | --- |
| `governance/terraform/` (new stack) | Any change to `foundation/`, `subscription/`, `claim-service/` resources |
| `governance/README.md`, `governance/RUNBOOK.md` | Account creation / invitation |
| `mise` tasks: `governance-plan`, `governance-apply`, `governance-destroy` | Un-freeze automation |
| `backend/terraform` output + bootstrap wiring for governance | Flipping Organizations all-features / SCP policy type (a platform Step 0) |
| `.gitignore` entries; root README index + layout rows | Applying to the live org |

## Architecture

```mermaid
flowchart TD
  subgraph OP["Operator (mise run)"]
    MISE["governance-plan / -apply / -destroy<br/>WORKSHOP_ID guard + backend.hcl checks"]
  end

  CREDS["Management-account /<br/>delegated Org-admin creds<br/>(var.aws_profile)"]
  PROV["aws provider<br/>region/profile fallback + default_tags"]
  CALLER["data.aws_caller_identity.current<br/>(mgmt account id)"]

  MISE -->|TF_VAR_workshop_id, init key| PROV
  CREDS --> PROV
  PROV --> CALLER

  subgraph ORG["AWS Organizations (management account)"]
    PARENT["var.parent_id<br/>(parent OU / root)"]
    OU["aws_organizations_organizational_unit.workshop<br/>name = workshop-&lt;workshop_id&gt;"]
    PARENT --> OU

    ACCTS["var.account_ids<br/>(pre-existing, already in org)"]
    ACCTS -.->|placed into OU<br/>(for_each)| OU

    GUARD["aws_organizations_policy.kiro_guardrail<br/>SERVICE_CONTROL_POLICY<br/>allowlist from var.kiro_allowed_actions"]
    GUARD -->|aws_organizations_policy_attachment| OU

    FREEZE["aws_organizations_policy.freeze<br/>SERVICE_CONTROL_POLICY: Deny * on *<br/>(created, NOT attached)"]
  end

  subgraph BUD["AWS Budgets (per account, for_each)"]
    ROLE["aws_iam_role.budgets_execution<br/>trust: budgets.amazonaws.com<br/>cond: aws:SourceAccount = caller id<br/>perms: Organizations Attach/Detach"]
    BUDGET["aws_budgets_budget[acct]<br/>COST, cost_filter LinkedAccount = acct<br/>notify-only emails (+ optional notify %)"]
    ACTION["aws_budgets_budget_action[acct]<br/>action_type=SCP, approval_model=AUTOMATIC<br/>threshold = freeze_threshold_percent<br/>definition: policy_id=freeze, target_ids=[acct]<br/>execution_role_arn = role"]
    BUDGET --> ACTION
  end

  CALLER --> ROLE
  ACTION -->|on breach: attach freeze SCP to acct| FREEZE
  ACTION -->|uses| ROLE
  ACTION -.->|targets a single account, never the OU| ACCTS
```

### Key architectural decisions

- **One OU per workshop, keyed by `var.workshop_id`** — a single
  `aws_organizations_organizational_unit` resource (not `for_each`), so there is
  always exactly one OU per run (Requirement 2).
- **Guardrail at the OU, freeze at the account.** The Kiro allowlist is an
  OU-level boundary applying to every account in the OU; the freeze is targeted
  at a single breaching account so one account's overrun never freezes the
  whole workshop (Requirements 4, 7.4).
- **Freeze created but unattached.** The deny-all SCP exists ready for AWS
  Budgets to attach it on breach; the stack declares **no attachment resource**
  for it (Requirement 5).
- **Automatic, not approval-gated, budget action.** `approval_model = AUTOMATIC`
  so a breach freezes without a human in the loop (Requirement 7).
- **Confused-deputy guard on the execution role.** The role trusts
  `budgets.amazonaws.com` but only when `aws:SourceAccount` equals this
  management account, and its permissions are scoped to Organizations
  attach/detach of the freeze policy (Requirement 6).
- **Fail-closed guards reused verbatim.** The `mise` tasks reuse the exact
  `WORKSHOP_ID` strip/slug/`--`/`backend.hcl`/`key` guard snippet from the
  subscription and claim tasks (Requirement 13).

## Components and Files

All stack code lives under `governance/terraform/`. File responsibilities:

| File | Responsibility | Requirements |
| --- | --- | --- |
| `versions.tf` | `required_version >= 1.6`; `hashicorp/aws >= 5.56.0`; **no awscc** | 11.2, 11.3 |
| `providers.tf` | aws provider with region/profile fallback + `default_tags`; `data aws_region`; `data aws_caller_identity` | 11.4-11.6, 6.2, 14.3 |
| `backend.tf` | tracked, value-free `backend "s3" {}` | 9.1, 9.2, 11.8 |
| `backend.hcl.example` | keyless example mirroring foundation | 9.2 |
| `variables.tf` | all inputs + validations | 1.2-1.3, 4.3-4.4, 8.1-8.2, 13.2, 14.3 |
| `organizations.tf` | OU + account placement | 2, 3 |
| `scps.tf` | guardrail SCP + attachment; freeze SCP (unattached) | 4, 5 |
| `budgets.tf` | execution role + per-account budgets + SCP actions | 6, 7, 8 |
| `outputs.tf` | OU ids, SCP ids, role arn, per-account budget/action map | — |

### `versions.tf` (Requirements 11.2, 11.3)

```hcl
terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.56.0"
    }
    # NOTE: NO hashicorp/awscc. Organizations, SCPs, Budgets, and the budget
    # action are all first-class hashicorp/aws resources; the awscc provider
    # the foundation stack needs (for the IdC instance) has no role here.
  }

  # Remote S3 state (REQUIRED). The partial `backend "s3" {}` lives in the
  # tracked backend.tf; account-specific values come from the git-ignored,
  # keyless backend.hcl, with the governance state key supplied at init time.
}
```

### `providers.tf` (Requirements 11.4-11.6, 6.2, 14.3)

```hcl
# Region/credentials come from the environment so the same config is reusable.
# IMPORTANT: this stack targets the ORGANIZATIONS MANAGEMENT account (or a
# delegated Org-admin). var.aws_profile selects those creds — distinct from the
# member-account profile the other stacks use.

provider "aws" {
  region  = var.aws_region != "" ? var.aws_region : null
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = var.default_tags
  }
}

data "aws_region" "current" {}

# The management account id — used for the budget-action target scope and, more
# importantly, the aws:SourceAccount confused-deputy guard on the budgets role.
data "aws_caller_identity" "current" {}
```

### `backend.tf` and `backend.hcl.example` (Requirements 9.1, 9.2, 11.8)

`backend.tf` is tracked and value-free, identical in shape to foundation:

```hcl
terraform {
  backend "s3" {}
}
```

`backend.hcl.example` mirrors foundation's keyless template (bucket, region,
`dynamodb_table`, `encrypt = true`), with comments stating the governance state
key `workshops/<WORKSHOP_ID>/governance/terraform.tfstate` is supplied at init
time and is **not** in this file.

### `variables.tf`

| Variable | Type | Default | Validation | Requirements |
| --- | --- | --- | --- | --- |
| `workshop_id` | string | — | slug `^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$` **and** no `--` | 2.2, 13.2-13.3 |
| `parent_id` | string | — | — (parent OU/root the workshop OU hangs under) | 2.4 |
| `account_ids` | list(string) | — | each `^\d{12}$`, message naming the bad value | 1.2, 1.3 |
| `aws_region` | string | `""` | — | 11.4 |
| `aws_profile` | string | `""` | — | 11.5, 14.3 |
| `default_tags` | map(string) | sensible default | — | 11.6 |
| `kiro_allowed_actions` | list(string) | conservative starter allowlist | — | 4.3, 4.4 |
| `freeze_threshold_percent` | number | `100` | — | 7.2 |
| `notification_emails` | list(string) | **no default (required)** | `length > 0` | 8.1, 8.2 |
| `notify_threshold_percent` | number | `null` | — | 8.4, 8.5 |
| `budget_limit_amount` | number/string | — | — | 7.1 |
| `budget_limit_unit` | string | `"USD"` | — | 7.1 |

```hcl
variable "workshop_id" {
  description = "Per-workshop slug; names the OU (workshop-<id>) and keys the state."
  type        = string
  validation {
    condition = (
      can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", var.workshop_id))
      && !can(regex("--", var.workshop_id))
    )
    error_message = "workshop_id must be 1-63 lowercase alphanumerics/hyphens, begin/end alphanumeric, no consecutive hyphens."
  }
}

variable "account_ids" {
  description = "Pre-existing, in-org 12-digit account ids to place in the workshop OU. The stack never CREATES accounts."
  type        = list(string)
  validation {
    # Fails naming the first offending value (Requirement 1.3).
    condition     = alltrue([for a in var.account_ids : can(regex("^\\d{12}$", a))])
    error_message = "Every account id must be a 12-digit string. Offending values: ${join(", ", [for a in var.account_ids : a if !can(regex("^\\d{12}$", a))])}."
  }
}

variable "kiro_allowed_actions" {
  description = <<-EOT
    Allowlist of IAM actions the Kiro guardrail SCP permits (deny-by-default).
    The default is a CONSERVATIVE STARTER permitting Kiro + IAM Identity Center
    sign-in plus read-only basics; it is a TUNABLE starting point — widen or
    narrow it per workshop (see README).
  EOT
  type        = list(string)
  default = [
    "sso:*", "sso-directory:*", "identitystore:*",
    "signin:*", "sts:GetCallerIdentity",
    "codewhisperer:*", "q:*",
  ]
}

variable "notification_emails" {
  description = "REQUIRED budget-notification recipients (notify-only). No default; empty list fails validation."
  type        = list(string)
  validation {
    condition     = length(var.notification_emails) > 0
    error_message = "notification_emails must contain at least one address; a breach must never be silent."
  }
}

variable "notify_threshold_percent" {
  description = "Optional softer notify-only threshold (%). When null, no extra notify-only threshold is created."
  type        = number
  default     = null
}
```

> The `kiro_allowed_actions` default is illustrative. The execution agent
> validates concrete action names against current Kiro/IdC guidance when
> authoring; the design intent is a deny-by-default allowlist, not the exact
> strings.

### `organizations.tf` — OU and account placement (Requirements 2, 3)

**The OU** is a single resource:

```hcl
resource "aws_organizations_organizational_unit" "workshop" {
  name      = "workshop-${var.workshop_id}"
  parent_id = var.parent_id
}
```

**Account placement — the provider nuance.** `hashicorp/aws` historically
offered **no standalone "move an existing account into an OU" resource**: the
`aws_organizations_account` resource both *creates* and *places* accounts, and
using it on an account the provider did not create risks the provider trying to
manage (or on destroy, close) that account — which this stack must never do
(Requirement 1).

The design therefore makes placement an **execution-time decision validated
against the installed provider version**, with a documented leading candidate
and fallbacks:

- **Leading candidate (preferred): the OU resource plus an import-based
  adoption of each pre-existing account under the OU.** Declare each account via
  the account resource scoped so it is adopted (imported) into state with
  `parent_id` set to the workshop OU — i.e. the resource exists only to express
  the *desired placement* of an account the provider did **not** create, and is
  imported, never created. Guard it so a destroy detaches/leaves the account
  rather than closing it (`lifecycle`/`close_on_deletion`-style protection as
  the provider version supports).

  ```hcl
  # Candidate shape — one placement per supplied account, keyed by id.
  # Adopted via `tofu import` (NOT created); parent_id expresses the move.
  resource "aws_organizations_account" "placed" {
    for_each  = toset(var.account_ids)
    name      = each.key            # existing account; set to match on import
    email     = "placeholder+${each.key}@example.invalid" # overwritten on import
    parent_id = aws_organizations_organizational_unit.workshop.id

    lifecycle {
      # Never let a destroy of this stack CLOSE a pre-existing account.
      prevent_destroy = true
      ignore_changes  = [name, email, role_name]
    }
  }
  ```

- **Fallback A — operator `moveAccount`.** If the installed provider version has
  no clean, import-safe placement resource, placement is a documented operator
  step: `aws organizations move-account --account-id <id>
  --source-parent-id <root/parent> --destination-parent-id <OU id>` (or console
  move), performed once per account. The stack still owns the OU and the SCP
  attachment; the move is recorded in the RUNBOOK.
- **Fallback B — import of whatever placement primitive the provider exposes.**
  If a dedicated placement/membership resource exists in the pinned provider
  version, prefer it and import existing membership.

The RUNBOOK documents the chosen mechanism, the `prevent_destroy` guard, and the
`moveAccount` fallback. The invariant across all options: **accounts are placed,
never created or closed** (Requirements 1.1, 3.1-3.3). Placement is keyed solely
by `var.account_ids`, so no account outside that set is ever moved
(Requirement 3.3).

### `scps.tf` — guardrail and freeze SCPs (Requirements 4, 5)

```hcl
# --- Kiro guardrail: deny-by-default allowlist, attached to the OU ----------
data "aws_iam_policy_document" "kiro_guardrail" {
  # Allowlist semantics for an SCP: a single Allow of the permitted actions.
  # Everything not listed is implicitly denied by the SCP boundary.
  statement {
    sid       = "KiroAllowlist"
    effect    = "Allow"
    actions   = var.kiro_allowed_actions
    resources = ["*"]
  }
}

resource "aws_organizations_policy" "kiro_guardrail" {
  name        = "kiro-guardrail-${var.workshop_id}"
  description = "Kiro-only allowlist for workshop ${var.workshop_id}."
  type        = "SERVICE_CONTROL_POLICY"
  content     = data.aws_iam_policy_document.kiro_guardrail.json
}

resource "aws_organizations_policy_attachment" "kiro_guardrail" {
  policy_id = aws_organizations_policy.kiro_guardrail.id
  target_id = aws_organizations_organizational_unit.workshop.id
}

# --- Freeze: deny-all, CREATED BUT NOT ATTACHED (no attachment resource) ----
data "aws_iam_policy_document" "freeze" {
  statement {
    sid       = "DenyAll"
    effect    = "Deny"
    actions   = ["*"]
    resources = ["*"]
  }
}

resource "aws_organizations_policy" "freeze" {
  name        = "freeze-${var.workshop_id}"
  description = "Deny-all freeze; attached to a single account automatically on budget breach."
  type        = "SERVICE_CONTROL_POLICY"
  content     = data.aws_iam_policy_document.freeze.json
}
# INTENTIONALLY no aws_organizations_policy_attachment for the freeze policy.
```

### `budgets.tf` — execution role, budgets, and SCP actions (Requirements 6, 7, 8)

```hcl
# --- Budgets execution role (least privilege + confused-deputy guard) -------
data "aws_iam_policy_document" "budgets_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id] # Requirement 6.2
    }
  }
}

data "aws_iam_policy_document" "budgets_permissions" {
  statement {
    sid     = "AttachDetachFreezeSCP"
    effect  = "Allow"
    actions = [
      "organizations:AttachPolicy",
      "organizations:DetachPolicy",
      # Minimal reads Budgets needs to resolve the policy/targets:
      "organizations:ListPolicies",
      "organizations:DescribePolicy",
      "organizations:ListTargetsForPolicy",
    ]
    resources = ["*"] # scoped by action set; no org-wide admin (Requirement 6.4)
  }
}

resource "aws_iam_role" "budgets_execution" {
  name                = "governance-budgets-exec-${var.workshop_id}"
  assume_role_policy  = data.aws_iam_policy_document.budgets_trust.json
}

resource "aws_iam_role_policy" "budgets_execution" {
  name   = "attach-detach-freeze"
  role   = aws_iam_role.budgets_execution.id
  policy = data.aws_iam_policy_document.budgets_permissions.json
}

# --- One COST budget per account --------------------------------------------
resource "aws_budgets_budget" "account" {
  for_each = toset(var.account_ids)

  name         = "governance-${var.workshop_id}-${each.key}"
  budget_type  = "COST"
  limit_amount = var.budget_limit_amount
  limit_unit   = var.budget_limit_unit
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "LinkedAccount"
    values = [each.key] # scope to just this account (Requirement 7.1)
  }

  # Required notify-only recipients at the freeze threshold (Requirement 8.3).
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.freeze_threshold_percent
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = var.notification_emails
  }

  # Optional softer notify-only threshold (Requirements 8.4, 8.5).
  dynamic "notification" {
    for_each = var.notify_threshold_percent != null ? [var.notify_threshold_percent] : []
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = var.notification_emails
    }
  }
}

# --- One AUTOMATIC SCP freeze action per budget -----------------------------
resource "aws_budgets_budget_action" "freeze" {
  for_each = toset(var.account_ids)

  budget_name        = aws_budgets_budget.account[each.key].name
  action_type        = "APPLY_SCP_POLICY"
  approval_model     = "AUTOMATIC" # Requirement 7.2
  execution_role_arn = aws_iam_role.budgets_execution.arn # Requirement 7.5

  action_threshold {
    action_threshold_type  = "PERCENTAGE"
    action_threshold_value = var.freeze_threshold_percent
  }

  definition {
    scp_action_definition {
      policy_id  = aws_organizations_policy.freeze.id
      target_ids = [each.key] # the breaching account, NEVER the OU (Requirement 7.4)
    }
  }

  subscriber {
    subscription_type = "EMAIL"
    address           = var.notification_emails[0]
  }
  # Additional EMAIL subscribers rendered for the remaining notification_emails
  # via a dynamic "subscriber" block at implementation time.
}
```

> The exact budget-action `action_type` enum (`APPLY_SCP_POLICY`) and the
> `scp_action_definition` nesting are confirmed against the installed
> `hashicorp/aws` provider version during execution; the design intent — an
> `AUTOMATIC` SCP action attaching the freeze policy to the single breaching
> account via the execution role — is fixed.

### `outputs.tf`

```hcl
output "workshop_ou_id"   { value = aws_organizations_organizational_unit.workshop.id }
output "workshop_ou_arn"  { value = aws_organizations_organizational_unit.workshop.arn }
output "workshop_ou_name" { value = aws_organizations_organizational_unit.workshop.name }

output "kiro_guardrail_scp_id" { value = aws_organizations_policy.kiro_guardrail.id }
output "freeze_scp_id"         { value = aws_organizations_policy.freeze.id }

output "budgets_execution_role_arn" { value = aws_iam_role.budgets_execution.arn }

# Per-account map keyed by account id: { budget_name, action_id }.
output "per_account_budgets" {
  value = {
    for a in var.account_ids : a => {
      budget_name = aws_budgets_budget.account[a].name
      action_id   = aws_budgets_budget_action.freeze[a].id
    }
  }
}
```

## mise tasks (Requirements 12, 13)

Three tasks added to `mise.toml` under a new `=== governance/ stack ===`
section. Each reuses the **exact** `WORKSHOP_ID` guard from the subscription /
claim tasks: strip whitespace → fail if empty → slug regex via `grep -Eq` →
reject `--` via `grep -q -- '--'` → `backend.hcl` must exist → `backend.hcl`
must not carry a `key` line. All run `dir = "governance/terraform"` and
`export TF_VAR_workshop_id="$WID"`.

| Task | Behavior | Requirements |
| --- | --- | --- |
| `governance-plan` | guards → `tofu init -reconfigure -backend-config=backend.hcl -backend-config="key=workshops/${WID}/governance/terraform.tfstate"` → `tofu plan`; mutates nothing | 12.1, 13.* |
| `governance-apply` | same guards + init → `tofu apply` (prompts; no `-auto-approve`) → echo outputs | 12.2, 12.5, 13.* |
| `governance-destroy` | typed-phrase guard reading exactly `destroy-governance` (mirrors `foundation-destroy`'s `read -r CONFIRM`) → same backend init → `tofu destroy` (its own prompt) | 12.3, 12.4, 12.5 |

```bash
# governance-plan — the shared guard, then a non-mutating plan.
set -eu
WID="$(printf '%s' "${WORKSHOP_ID:-}" | tr -d '[:space:]')"
if [ -z "$WID" ]; then
  echo "ERROR: WORKSHOP_ID is required (unset or whitespace-only)." >&2
  exit 1
fi
if ! printf '%s' "$WID" | grep -Eq '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$' \
   || printf '%s' "$WID" | grep -q -- '--'; then
  echo "ERROR: WORKSHOP_ID '$WID' is not a valid slug." >&2
  exit 1
fi
if [ ! -f backend.hcl ]; then
  echo "ERROR: governance/terraform/backend.hcl not found (run: mise run backend-bootstrap)." >&2
  exit 1
fi
if grep -Eq '^[[:space:]]*key[[:space:]]*=' backend.hcl; then
  echo "ERROR: remove the 'key' line from backend.hcl; it is supplied at init time." >&2
  exit 1
fi
export TF_VAR_workshop_id="$WID"
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=workshops/${WID}/governance/terraform.tfstate" \
  || { echo "ERROR: backend init failed; not planning." >&2; exit 1; }
tofu plan
```

`governance-destroy` prepends the typed-phrase gate before the shared guard:

```bash
printf 'This mutates the LIVE Organizations management account (OU + SCPs + budgets).\n'
printf 'Type exactly "destroy-governance" to proceed: '
read -r CONFIRM
if [ "$CONFIRM" != "destroy-governance" ]; then
  echo "ERROR: confirmation phrase did not match 'destroy-governance'; destroying nothing." >&2
  exit 1
fi
```

> **No `governance-unfreeze` task exists** (Requirement 15.2), and no task
> detaches the freeze SCP (Requirement 15.3).

## backend/ bootstrap extension (Requirement 10)

Mirror the existing `backend_hcl_foundation` wiring:

1. **`backend/terraform/outputs.tf`** — add `governance` to the
   `_backend_hcl_for` map and a new output:

   ```hcl
   locals {
     _backend_hcl_for = {
       subscription  = local._backend_hcl_body
       claim_service = local._backend_hcl_body
       foundation    = local._backend_hcl_body
       governance    = local._backend_hcl_body # NEW
     }
   }

   output "backend_hcl_governance" {
     description = "The full governance/terraform/backend.hcl body (mise writes it; tofu init -backend-config=backend.hcl reads it)."
     value       = local._backend_hcl_for["governance"]
   }
   ```

2. **`backend-bootstrap` task** — append, after the foundation write:

   ```bash
   tofu output -raw backend_hcl_governance > ../../governance/terraform/backend.hcl
   echo "wrote governance/terraform/backend.hcl"
   cat ../../governance/terraform/backend.hcl
   ```

3. **`.gitignore`** — add:

   ```gitignore
   # Governance stack local-only backend config + tfvars (per-account/state + inputs).
   governance/terraform/backend.hcl
   governance/terraform/*.tfvars
   ```

## Documentation

### `governance/README.md` (concepts) — Requirements 4.5, 14.1-14.2, 16.2

Concepts: one OU per workshop; the Kiro guardrail SCP (deny-by-default
allowlist, `var.kiro_allowed_actions` documented as a **tunable** starting
point, Requirement 4.5); the automatic per-account budget freeze; the
management-account / delegated Org-admin credential requirement selected via
`var.aws_profile` (distinct from the member-account profile the other stacks
use). **Preconditions:** Organizations in all-features mode with the
`SERVICE_CONTROL_POLICY` policy type enabled on the root — a **Step 0 the stack
cannot perform** (Requirement 14.1). Account creation is explicitly out of
scope. States that applying mutates the live management account with high blast
radius (Requirement 16.2).

### `governance/RUNBOOK.md` (run order) — Requirements 14, 15, 16

Mirrors foundation's legend `(mgmt account)` / `(this account)` / `(IaC)` /
`(console)`. Sections:

- **Step 0 — (mgmt account, one-time) precondition:** enable all-features +
  `SERVICE_CONTROL_POLICY` policy type on the root. If missing, the apply fails
  with an **Organizations authorization / policy-type error**, which the RUNBOOK
  names as the missing precondition (Requirement 14.4).
- **Step 1 — backend bootstrap** writes `governance/terraform/backend.hcl`.
- **Step 2 — plan / apply** with management-account creds (`var.aws_profile`),
  noting the account-placement mechanism chosen and the `moveAccount` fallback.
- **Automatic freeze behavior:** a breach attaches the freeze SCP to the single
  breaching account; notifications go to `notification_emails`.
- **Manual un-freeze (no automation):** detach the freeze SCP from the account
  via console or `aws organizations detach-policy --policy-id <freeze>
  --target-id <account>`. The stack provides **no** recovery automation
  (Requirement 15).
- **Teardown:** `governance-destroy` typed-phrase (`destroy-governance`) + tofu's
  own prompt; the OU must be empty (accounts moved out) and SCPs detach before
  the OU can be removed.
- States verification is `validate` / `fmt` / `plan` only and apply needs
  explicit operator go-ahead (Requirement 16.3).

### Root `README.md`

- **Documentation index:** add a row for
  [`governance/README.md`](./governance/README.md) and
  [`governance/RUNBOOK.md`](./governance/RUNBOOK.md).
- **Repo layout tree:** add a `governance/` entry describing the OU + guardrail
  SCP + freeze SCP + per-account budgets, and note it runs with
  management-account creds and reuses the shared backend under
  `workshops/<id>/governance/terraform.tfstate`.

## Data Models

### Inputs

```
workshop_id              : string (slug)
parent_id                : string (parent OU / root id)
account_ids              : list(string)  # each ^\d{12}$, pre-existing in-org
kiro_allowed_actions     : list(string)  # allowlist, tunable default
freeze_threshold_percent : number        # default 100
notification_emails      : list(string)  # REQUIRED, non-empty
notify_threshold_percent : number | null # optional notify-only threshold
budget_limit_amount      : number/string
budget_limit_unit        : string        # default "USD"
aws_region / aws_profile : string        # "" => env fallback
default_tags             : map(string)
```

### Derived resource shape (per apply)

```
1 x aws_organizations_organizational_unit.workshop
N x account placements (for_each over account_ids; adopted, never created)
1 x aws_organizations_policy.kiro_guardrail (+ 1 attachment -> OU)
1 x aws_organizations_policy.freeze        (0 attachments)
1 x aws_iam_role.budgets_execution (+ 1 inline policy)
N x aws_budgets_budget.account[acct]       (cost_filter LinkedAccount = acct)
N x aws_budgets_budget_action.freeze[acct] (SCP, AUTOMATIC, target_ids=[acct])
```

### Governance state key

```
workshops/<WORKSHOP_ID>/governance/terraform.tfstate
```

## Error Handling (fail-closed)

| Condition | Where | Behavior | Requirements |
| --- | --- | --- | --- |
| `WORKSHOP_ID` unset / whitespace-only | mise guard | non-zero exit, no tofu run | 13.1 |
| `WORKSHOP_ID` bad slug | mise guard + TF validation | non-zero exit, change nothing | 13.2 |
| `WORKSHOP_ID` consecutive hyphens | mise guard | non-zero exit | 13.3 |
| `backend.hcl` missing | mise guard | non-zero exit naming the file | 13.4 |
| `backend.hcl` has a `key` line | mise guard | non-zero exit (key supplied at init) | 13.5 |
| `account_ids` entry not 12 digits | TF variable validation | fail naming the offending value | 1.3 |
| `notification_emails` empty | TF variable validation | fail; apply nothing | 8.2 |
| destroy typed-phrase mismatch | mise guard | non-zero exit, destroy nothing | 12.4 |
| all-features / SCP-type precondition missing | AWS on apply | Organizations auth / policy-type error (documented in RUNBOOK as the missing Step 0) | 14.4 |

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all
valid executions of a system — essentially, a formal statement about what the
system should do. Properties serve as the bridge between human-readable
specifications and machine-verifiable correctness guarantees.*

This stack is Infrastructure-as-Code: most acceptance criteria are structural
plan-shape assertions, variable-validation edge cases, or documentation/process
checks (verified by `tofu plan` shape assertions, negative `tofu validate`
cases, and doc/layout review — see Testing Strategy), not universally-quantified
pure-function properties. Three criteria describe genuine input-varying
transformations and are stated as properties below.

### Property 1: Guardrail renders exactly the supplied allowlist

*For any* non-empty list of actions supplied as `var.kiro_allowed_actions`, the
rendered Kiro guardrail SCP document contains a single `Allow` statement whose
action set equals that list (deny-by-default allowlist semantics), and no
action outside the list is granted.

**Validates: Requirements 4.3, 4.4**

### Property 2: Each budget action freezes only its own account

*For any* set of supplied `account_ids`, every generated budget action's
`scp_action_definition.target_ids` equals exactly the singleton list of its own
account id — never the workshop OU id and never another account's id — and every
action references the freeze policy and the budgets execution role.

**Validates: Requirements 7.4, 7.5**

### Property 3: Every notification email is subscribed notify-only on every budget

*For any* non-empty `var.notification_emails` list and any supplied account,
that account's budget renders a notify-only notification whose email subscriber
set equals the full `notification_emails` list, so no configured recipient is
omitted from any per-account budget.

**Validates: Requirements 8.3**

## Testing Strategy

Verification is **non-mutating only** — no apply — because the blast radius on
the live management account is high; apply happens solely with explicit operator
go-ahead (Requirements 16.1, 16.3).

### Static and plan-shape verification

1. **`tofu fmt -check`** — formatting gate.
2. **`tofu validate`** (with `-backend=false` where init is not wired) — config
   and variable-schema validity.
3. **`tofu plan` against a sample tfvars** — placeholder `parent_id`, two
   12-digit `account_ids`, and `notification_emails`. Assert the expected plan
   shape:
   - exactly **1** OU, named `workshop-<id>` under `parent_id`;
   - **N** account placements, each into the single OU, set == supplied ids
     (no extras);
   - **2** SCPs with **only the guardrail attached** (freeze has no attachment);
   - **1** budgets execution role (trust = `budgets.amazonaws.com`,
     `aws:SourceAccount` condition; scoped attach/detach permissions);
   - **N** budgets (one per account, `LinkedAccount` filter);
   - **N** AUTOMATIC SCP actions, each `target_ids = [its own account]`.

### Negative variable-validation tests

- bad slug `workshop_id` (e.g. `Bad_ID`, `a--b`) → validation failure;
- `account_ids` containing a non-12-digit value → failure naming the value;
- empty `notification_emails` → failure.

### Property tests (where meaningfully input-varying)

Properties 1-3 are exercised by rendering the plan (or the
`data.aws_iam_policy_document` / `for_each` output) over a **representative and
varied** set of inputs — e.g. several allowlist shapes for Property 1, and a
multi-account set for Properties 2-3 — asserting the universal relationship
holds for each generated case. These complement, not replace, the structural
plan-shape assertions above.

**Property test configuration (where a harness is used):** minimum 100
iterations per property; each test tagged **Feature: workshop-account-governance,
Property {number}: {property_text}**. In this IaC stack the practical harness is
plan-output assertion over varied tfvars rather than a general-purpose PBT
library.

### Guard / task tests (shell)

- `WORKSHOP_ID` unset/whitespace/bad-slug/`--` → non-zero exit, no tofu run;
- missing `backend.hcl` → non-zero naming the file; `key` line present →
  non-zero;
- `governance-destroy` with a wrong phrase → non-zero exit, nothing destroyed;
  tasks never pass `-auto-approve`.

### Not applied

No `tofu apply` / `destroy` runs during verification. Apply-time behaviors —
account placement against the live org, breach-triggered SCP attach, and the
all-features / SCP-type precondition error — are documented in the RUNBOOK and
confirmed only during an operator-approved apply (Requirements 1.4, 7.3, 14.4,
16.3).

## Requirements Coverage Map

| Requirement | Design section(s) |
| --- | --- |
| 1 — pre-existing in-org accounts only | `organizations.tf` (placement, never create); `variables.tf` `account_ids` validation; Error Handling; Testing (no apply) |
| 2 — one OU per workshop | `organizations.tf` (single OU resource, `workshop-<id>`, `parent_id`) |
| 3 — place accounts into the OU | `organizations.tf` (for_each placement keyed by `account_ids`) |
| 4 — Kiro guardrail SCP on OU | `scps.tf` guardrail + attachment; `variables.tf` `kiro_allowed_actions`; README tunable note; Property 1 |
| 5 — freeze SCP unattached | `scps.tf` freeze (no attachment) |
| 6 — budgets execution role + confused-deputy guard | `providers.tf` caller identity; `budgets.tf` role/trust/permissions |
| 7 — per-account budget + AUTOMATIC SCP action | `budgets.tf` budgets + actions; Property 2 |
| 8 — required emails + optional notify threshold | `variables.tf`; `budgets.tf` notifications; Property 3 |
| 9 — workshop-namespaced shared backend | `backend.tf`, `backend.hcl.example`; mise init key |
| 10 — backend bootstrap extension | backend/ outputs + bootstrap task; `.gitignore` |
| 11 — stack layout + file conventions | Components and Files; `versions.tf`; `providers.tf`; `backend.tf` |
| 12 — mise lifecycle tasks | mise tasks section |
| 13 — WORKSHOP_ID guard + init key | mise tasks (shared guard); Error Handling |
| 14 — documented preconditions | README/RUNBOOK; `providers.tf`/`variables.tf` `aws_profile` |
| 15 — manual un-freeze | RUNBOOK un-freeze; no `governance-unfreeze`; no detach automation |
| 16 — verify without applying | Testing Strategy; README/RUNBOOK blast-radius note |
