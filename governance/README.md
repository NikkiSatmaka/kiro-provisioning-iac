# Governance stack (the workshop OU, guardrails, and budget freeze)

This is the **optional Governance track** of the repo (see the journey table in
the root [`README.md`](../README.md)). It is **not a step in the linear**
Phase 0→4 provisioning flow — run it when you want to put a workshop's **member
accounts** under an OU + guardrail SCP + auto-freeze budgets.

- **Prerequisites:** Phase 0 (toolchain + management-account auth), Phase 1
  (shared backend), and Phase 2 (`foundation/`) done — foundation creates the
  shared budgets role and the two SCP policies this stack consumes (see
  [`../foundation/README.md`](../foundation/README.md)) — and the member
  accounts already exist in the organization.
- **Next:** teardown is the guarded `mise run governance-destroy` (see
  [`RUNBOOK.md`](./RUNBOOK.md)).

The management-account-scoped stack that governs a single workshop's accounts:
it creates **one OU per workshop**, **attaches** the shared deny-by-default Kiro
guardrail SCP to that OU, and wires **per-account budgets** that **automatically
freeze** only the account that overruns its limit. It does **not** create the
guardrail SCP, the freeze SCP, or the budgets execution role — those are
once-per-management-account shared primitives owned by `foundation/` and passed
in by id/ARN (see "Consuming the shared primitives" below). Like every other
stack it runs against the Organizations **management account** (or a delegated
Org-admin). What is distinct here is not where it runs but what it *targets*:
its SCP attachment and budgets act on the **member accounts** in the workshop OU.
Workloads provisioned by the other stacks live in the management account and are
therefore intentionally outside SCP/budget scope (SCPs never restrict the
management account, and budgets filter by member `LinkedAccount`).

> ⚠️ **Applying mutates the live Organizations management account — high blast
> radius.** SCP attachment and budget actions affect real accounts
> immediately. Nothing here runs on its own: every step is a `mise run` task you
> invoke. [`RUNBOOK.md`](./RUNBOOK.md) is the end-to-end run order, including the
> one-time management-account precondition AWS only exposes through the console.

**Scope of this doc.** This README explains the concepts behind the governance
stack — the single OU, the guardrail *attachment*, the automatic freeze, the
shared primitives it consumes, and the management-account credential
requirement. For the step-by-step run order (preconditions, bootstrap,
plan/apply, un-freeze, teardown), use [`RUNBOOK.md`](./RUNBOOK.md). For the
overall repo journey, start at the [root `README.md`](../README.md).

## Consuming the shared primitives (from `foundation/`)

Three resources that used to be created here are now **once-per-management-account
singletons owned by `foundation/`** and consumed by this stack as inputs — the
same explicit variable handoff the subscription stack uses for the IdC IDs:

| Foundation output            | Governance input                   | Used for                                   |
| ---------------------------- | ---------------------------------- | ------------------------------------------ |
| `budgets_execution_role_arn` | `var.budgets_execution_role_arn`   | the role each budget's freeze action assumes |
| `kiro_guardrail_scp_id`      | `var.kiro_guardrail_scp_id`        | the policy id attached to this workshop's OU |
| `freeze_scp_id`              | `var.freeze_scp_id`                | the policy id Budgets attaches on breach     |

Run `foundation-apply` once per management account and export the three
`TF_VAR_*` values (it prints them) before `governance-apply`. The guardrail
allowlist (`var.kiro_allowed_actions`) is defined **once, in foundation** — it is
now a single org-standard policy shared by every workshop, not a per-workshop
knob.

## What it governs

Everything the stack *owns* is keyed to one workshop, identified by
`var.workshop_id`; the SCP policy objects and budgets role it references are
shared (owned by `foundation/`):

```
parent OU / org root (var.parent_id)
    │
    ▼
workshop-<workshop_id>  OU                    ← exactly one per run (the ONLY thing this stack owns)
    ├── guardrail SCP ATTACHMENT  (attaches the SHARED guardrail SCP to the OU)
    ├── pre-existing accounts     (MOVED IN out-of-band from var.account_ids; never created by this stack)
    └── per-account budgets       (one COST budget per account)
            └── AUTOMATIC freeze action → attaches the SHARED freeze SCP to the
                single breaching account on breach, assuming the SHARED role

shared, from foundation/:  guardrail SCP · freeze SCP (deny-all) · budgets role
```

## One OU per workshop

The stack creates **exactly one** organizational unit —
`aws_organizations_organizational_unit "workshop"`, named
`workshop-<workshop_id>` under the caller-supplied `var.parent_id`. It is a
single resource, never a `for_each`, so a run always produces one OU and one
guardrail boundary for the workshop.

The OU is the **only** thing this stack owns. The pre-existing accounts in
`var.account_ids` are moved into it **out-of-band** — not as Terraform
resources — by `mise run governance-place-accounts`, which reads the account ids
from the stack's own `account_ids` output (so `terraform.tfvars` is the single
source of truth — no need to retype them) and runs
`aws organizations move-account` once per id (keyed solely by `var.account_ids`,
so no account outside that set is ever moved). The stack **never creates,
invites, closes, or owns an account**. This is deliberate: `hashicorp/aws`
v6.67.0 has no non-create resource that can place an account into an OU — the
only resource carrying account→OU placement is `aws_organizations_account`,
AWS's CREATE-an-account resource, so expressing placement in Terraform risks
minting brand-new accounts on an apply with no prior state. Moving placement
out-of-band makes that structurally impossible. The run order and the exact
command are in [`RUNBOOK.md`](./RUNBOOK.md).

## The Kiro guardrail SCP attachment (deny-by-default)

The guardrail SCP itself — allowlist semantics, a single `Allow` of
`var.kiro_allowed_actions` on `*` — is **created in `foundation/`** as a single
org-standard policy. This stack **attaches** that shared policy (by
`var.kiro_guardrail_scp_id`) to the workshop OU. Because an SCP is a boundary,
everything not in the allowlist is implicitly denied, so every account in the OU
is bounded to exactly the listed actions.

The allowlist contents are **tuned once, in foundation**
(`var.kiro_allowed_actions` there) — a single org-standard policy, no longer a
per-workshop knob. If a workshop genuinely needs a different boundary, that is a
foundation-level decision affecting every workshop; adjust it deliberately.

## The automatic per-account budget freeze

Each account in `var.account_ids` gets its own `COST` budget
(`var.budget_limit_amount` / `var.budget_limit_unit`, default `USD`), scoped to
just that linked account. Each budget carries a **tiered set of ACTUAL-cost
alerts** to every address in `var.notification_emails`: one notify-only alert
per entry in `var.notify_threshold_percents` (default `[50, 75]`), plus a
**required** alert at `var.freeze_threshold_percent` (default `90`) that
accompanies the automatic freeze. With the defaults that is three tiers — alert
at 50%, alert at 75%, and alert + freeze at 90% — so a breach is never silent.
Every notify tier must sit strictly below the freeze level (validated).

Alongside each budget sits an **AUTOMATIC** budget action (no human in the
loop). On breach of `var.freeze_threshold_percent`, AWS Budgets assumes the
**shared least-privilege execution role** (`var.budgets_execution_role_arn`,
from foundation) and attaches the **shared deny-all freeze SCP**
(`var.freeze_scp_id`, from foundation) to the **single breaching account only —
never the OU**. So one account's overrun freezes that account and leaves the
rest of the workshop running.

Two details follow from this design:

- The freeze SCP lives in `foundation/`, **created but intentionally left
  unattached**. It exists only so Budgets can attach it to a breaching account;
  neither stack declares a static attachment resource for it. Because it is a
  shared singleton, a per-workshop `governance-destroy` never deletes it.
- There is **no un-freeze automation**. Recovery is a deliberate manual
  detach — the stack ships no `governance-unfreeze` task and nothing that
  detaches the freeze SCP. The detach procedure is in [`RUNBOOK.md`](./RUNBOOK.md).

## Management-account credentials via `var.aws_profile`

This stack targets the Organizations **management account** (or a delegated
Org-admin) — the only place that can manage OUs, SCPs, and organization-wide
budget actions. `var.aws_profile` selects those credentials. Every stack in this
repo now uses a management-account profile, so this is the same account the other
stacks (`foundation/`, `subscription/`, `claim-service/`) run under; the SCPs and
budgets this stack manages still *target* the member accounts in the workshop OU.

Region and credential resolution mirror the sibling stacks: an explicit
`-var` / tfvars value wins; when `var.aws_region` / `var.aws_profile` are empty
(the defaults) the provider inherits `AWS_REGION` / `AWS_PROFILE` from the
environment (mise sources these from the git-ignored `.env` file).

## Step 0 — a precondition satisfied by `foundation/`

Before any SCP can be created or attached, the organization's **root** must have
**all-features mode** and the **`SERVICE_CONTROL_POLICY` policy type** enabled —
both **management-account, one-time, console-only** actions OpenTofu cannot
perform.

Because `foundation/` is now the stack that **creates** the SCP policies, this
precondition is handled there (see
[`../foundation/RUNBOOK.md`](../foundation/RUNBOOK.md) Step 0b) and must be done
before `foundation-apply`. By the time you run `governance/`, the policy type is
already live, so this stack's guardrail *attachment* just works. If the policy
type is somehow missing, the attachment fails with an Organizations
authorization / policy-type error; [`RUNBOOK.md`](./RUNBOOK.md) names that error.

## Inputs

| Variable                       | Purpose                                                                        |
| ------------------------------ | ------------------------------------------------------------------------------ |
| `workshop_id`                  | Workshop slug; names the OU (`workshop-<id>`) and keys the state.             |
| `parent_id`                    | Parent OU / org-root id the workshop OU hangs under.                          |
| `account_ids`                  | Pre-existing, in-org 12-digit account ids moved into the OU out-of-band (keys the per-account budgets; never created). |
| `budgets_execution_role_arn`   | **From `foundation/`.** ARN of the shared role each freeze action assumes.    |
| `kiro_guardrail_scp_id`        | **From `foundation/`.** Id of the shared guardrail SCP attached to the OU.     |
| `freeze_scp_id`                | **From `foundation/`.** Id of the shared freeze SCP Budgets attaches on breach.|
| `freeze_threshold_percent`     | Percent of the limit at which the freeze fires AND an alert is sent (default `90`). |
| `notification_emails`          | **Required**, non-empty notify-only recipients; a breach must never be silent. |
| `notify_threshold_percents`    | Notify-only alert tiers below the freeze level (default `[50, 75]`); each must be `> 0` and `<` the freeze threshold. |
| `budget_limit_amount`          | Per-account COST budget limit amount.                                          |
| `budget_limit_unit`            | Currency unit for the budget limit (default `USD`).                            |
| `aws_region`                   | Provider region; empty falls back to `AWS_REGION`.                             |
| `aws_profile`                  | **Management-account / Org-admin** profile; empty falls back to the env.       |
| `default_tags`                 | Tags applied to every taggable resource via the provider.                      |

The allowlist (`kiro_allowed_actions`) is no longer a governance input — it is
defined once in `foundation/`.

## Outputs

`workshop_ou_id`, `workshop_ou_arn`, `workshop_ou_name`, and
`per_account_budgets` (a map keyed by account id → `{ budget_name, action_id }`).
These are the per-workshop resources this stack **owns**. The guardrail/freeze
SCP ids and the budgets role ARN are now **inputs** (from `foundation/`), not
outputs this stack owns; it may echo them for convenience but does not create
them. These outputs surface what an operator needs to verify the applied plan
shape and to drive the manual un-freeze path in [`RUNBOOK.md`](./RUNBOOK.md).

## Shared backend with a governance-scoped key

The governance stack uses the **same shared S3 backend** as the other stacks: a
tracked, value-free `backend "s3" {}` block (`backend.tf`) plus a git-ignored,
keyless `backend.hcl` whose values are supplied at `tofu init` time. The
`backend-bootstrap` task writes that `backend.hcl` for you (same bucket + lock
table as the sibling stacks). The state **key** is workshop-scoped:

```
workshops/<id>/governance/terraform.tfstate       ← this stack
workshops/<id>/subscription/terraform.tfstate
workshops/<id>/claim-service/terraform.tfstate
foundation/terraform.tfstate                       ← no workshop prefix
```

See [`../backend/README.md`](../backend/README.md) for how the bootstrap renders
and writes each stack's `backend.hcl`.

## Repo layout

```
governance/
├── README.md                 ← you are here (concepts)
├── RUNBOOK.md                ← Step 0 precondition (in foundation) + run / un-freeze / teardown order
└── terraform/
    ├── versions.tf           ← required providers (hashicorp/aws; no awscc)
    ├── providers.tf          ← aws wired to the MANAGEMENT-account profile/region
    ├── variables.tf          ← workshop_id, parent_id, account_ids, the three shared ids, budgets, aws_profile …
    ├── organizations.tf      ← the single workshop OU (accounts are moved in out-of-band)
    ├── scps.tf               ← guardrail SCP ATTACHMENT to the OU (policy object is in foundation/)
    ├── budgets.tf            ← per-account budgets + AUTOMATIC freeze actions (role + freeze SCP from foundation/)
    ├── outputs.tf            ← OU + per-account budget identifiers
    ├── backend.tf            ← tracked, value-free S3 backend block (partial config)
    └── backend.hcl.example   ← template for the manual backend.hcl (normally auto-written)
```

## Running it

The step-by-step order — the Step 0 management-account precondition, the
backend-bootstrap → plan → apply sequence, the out-of-band account move, the
automatic freeze behavior, the manual un-freeze, and the guarded teardown —
lives in [`RUNBOOK.md`](./RUNBOOK.md).

```bash
mise run governance-plan     # DRY RUN: tofu init + plan, mutates nothing
mise run governance-apply    # apply against the management account (prompts; high blast radius)
# then move the existing accounts into the new OU (real Organizations mutation).
# Reads account_ids from the stack output — terraform.tfvars is the source of truth:
mise run governance-place-accounts
```

Verification across the stack is `tofu fmt` / `tofu validate` / `tofu plan`
only. **Applying mutates the live management account and needs an operator's
explicit go-ahead.**
