# Governance stack (the workshop OU, guardrails, and budget freeze)

The management-account-scoped stack that governs a single workshop's accounts:
it creates **one OU per workshop**, attaches a **deny-by-default Kiro guardrail**
SCP to that OU, and wires **per-account budgets** that **automatically freeze**
only the account that overruns its limit. It runs against the Organizations
**management account** (or a delegated Org-admin), so it is distinct from the
member-account stacks (`foundation/`, `subscription/`, `claim-service/`).

> ⚠️ **Applying mutates the live Organizations management account — high blast
> radius.** SCP attachment and budget actions affect real accounts
> immediately. Nothing here runs on its own: every step is a `mise run` task you
> invoke. [`RUNBOOK.md`](./RUNBOOK.md) is the end-to-end run order, including the
> one-time management-account precondition AWS only exposes through the console.

**Scope of this doc.** This README explains the concepts behind the governance
stack — the single OU, the two SCPs, the automatic freeze, and the
management-account credential requirement. For the step-by-step run order
(preconditions, bootstrap, plan/apply, un-freeze, teardown), use
[`RUNBOOK.md`](./RUNBOOK.md). For the overall repo journey, start at the
[root `README.md`](../README.md).

## What it governs

Everything is keyed to one workshop, identified by `var.workshop_id`:

```
parent OU / org root (var.parent_id)
    │
    ▼
workshop-<workshop_id>  OU                    ← exactly one per run
    ├── Kiro guardrail SCP      (ATTACHED to the OU — deny-by-default)
    ├── pre-existing accounts   (PLACED from var.account_ids; never created)
    └── per-account budgets     (one COST budget per account)
            └── AUTOMATIC freeze action → attaches the freeze SCP to the
                single breaching account on breach

freeze SCP (deny-all)   ← CREATED but UNATTACHED; Budgets attaches it on breach
```

## One OU per workshop

The stack creates **exactly one** organizational unit —
`aws_organizations_organizational_unit "workshop"`, named
`workshop-<workshop_id>` under the caller-supplied `var.parent_id`. It is a
single resource, never a `for_each`, so a run always produces one OU and one
guardrail boundary for the workshop.

The pre-existing accounts in `var.account_ids` are **placed** into that OU
(keyed solely by `var.account_ids`, so no account outside that set is ever
moved). The stack **never creates, invites, or closes accounts** — account
creation is explicitly **out of scope**. Each placed account carries
`prevent_destroy = true`, so a destroy of this stack can never touch a
pre-existing account; the placement mechanism and the `moveAccount` fallback are
described in [`RUNBOOK.md`](./RUNBOOK.md).

## The Kiro guardrail SCP (deny-by-default)

The guardrail is a Service Control Policy attached to the workshop OU with
**allowlist semantics**: a single `Allow` of the actions in
`var.kiro_allowed_actions` on `*`. Because an SCP is a boundary, everything not
in the allowlist is implicitly denied — so every account in the OU is bounded to
exactly the listed actions.

`var.kiro_allowed_actions` ships a **conservative starter** default: Kiro / IAM
Identity Center sign-in plus read-only basics (`sso:*`, `sso-directory:*`,
`identitystore:*`, `signin:*`, `sts:GetCallerIdentity`, `codewhisperer:*`,
`q:*`). This default is a **TUNABLE starting point, not a finished policy** —
widen it to admit the services a given workshop needs, or narrow it to tighten
the blast radius, by overriding `var.kiro_allowed_actions` per workshop. Review
and adjust it deliberately for every workshop; the default is intentionally
tight and will block anything a workshop legitimately needs beyond sign-in.

## The automatic per-account budget freeze

Each account in `var.account_ids` gets its own `COST` budget
(`var.budget_limit_amount` / `var.budget_limit_unit`, default `USD`), scoped to
just that linked account. Each budget carries a **required notify-only**
notification to every address in `var.notification_emails` at
`var.freeze_threshold_percent` (default `100`), plus an optional softer
notify-only threshold when `var.notify_threshold_percent` is set.

Alongside each budget sits an **AUTOMATIC** budget action (no human in the
loop). On breach of `var.freeze_threshold_percent`, AWS Budgets assumes the
least-privilege execution role and attaches the deny-all **freeze SCP** to the
**single breaching account only — never the OU**. So one account's overrun
freezes that account and leaves the rest of the workshop running.

Two details follow from this design:

- The freeze SCP is **created but intentionally left unattached** at apply time.
  It exists only so Budgets can attach it to a breaching account; the stack
  declares no attachment resource for it.
- There is **no un-freeze automation**. Recovery is a deliberate manual
  detach — the stack ships no `governance-unfreeze` task and nothing that
  detaches the freeze SCP. The detach procedure is in [`RUNBOOK.md`](./RUNBOOK.md).

## Management-account credentials via `var.aws_profile`

This stack targets the Organizations **management account** (or a delegated
Org-admin) — the only place that can manage OUs, SCPs, and organization-wide
budget actions. `var.aws_profile` selects those credentials and is therefore
**distinct from the member-account profile** the other stacks
(`foundation/`, `subscription/`, `claim-service/`) use.

Region and credential resolution mirror the sibling stacks: an explicit
`-var` / tfvars value wins; when `var.aws_region` / `var.aws_profile` are empty
(the defaults) the provider inherits `AWS_REGION` / `AWS_PROFILE` from the
environment (mise sources these from the git-ignored `.env` file).

## Step 0 — a precondition the stack cannot perform

Before the stack can apply, the organization's **root** must have:

1. **All-features mode** enabled on the organization, and
2. The **`SERVICE_CONTROL_POLICY` policy type** enabled on the root.

Both are **management-account, one-time, console-only** actions — **a Step 0
this stack cannot perform**. OpenTofu cannot flip all-features mode or enable a
policy type on the root. If either is missing, the apply fails with an
Organizations authorization / policy-type error; [`RUNBOOK.md`](./RUNBOOK.md)
names that error and the missing precondition.

## Inputs

| Variable                   | Purpose                                                                        |
| -------------------------- | ------------------------------------------------------------------------------ |
| `workshop_id`              | Workshop slug; names the OU (`workshop-<id>`) and keys the state.              |
| `parent_id`                | Parent OU / org-root id the workshop OU hangs under.                           |
| `account_ids`              | Pre-existing, in-org 12-digit account ids to place in the OU (never created). |
| `kiro_allowed_actions`     | Allowlist for the Kiro guardrail SCP — a **tunable** conservative default.     |
| `freeze_threshold_percent` | Percent of the limit at which the freeze fires and notifies (default `100`).   |
| `notification_emails`      | **Required**, non-empty notify-only recipients; a breach must never be silent. |
| `notify_threshold_percent` | Optional softer notify-only threshold; `null` means none.                      |
| `budget_limit_amount`      | Per-account COST budget limit amount.                                          |
| `budget_limit_unit`        | Currency unit for the budget limit (default `USD`).                            |
| `aws_region`               | Provider region; empty falls back to `AWS_REGION`.                             |
| `aws_profile`              | **Management-account / Org-admin** profile; empty falls back to the env.       |
| `default_tags`             | Tags applied to every taggable resource via the provider.                      |

## Outputs

`workshop_ou_id`, `workshop_ou_arn`, `workshop_ou_name`,
`kiro_guardrail_scp_id`, `freeze_scp_id`, `budgets_execution_role_arn`, and
`per_account_budgets` (a map keyed by account id → `{ budget_name, action_id }`).
These surface what an operator needs to verify the applied plan shape and to
drive the manual un-freeze path in [`RUNBOOK.md`](./RUNBOOK.md).

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
├── RUNBOOK.md                ← Step 0 precondition + run / un-freeze / teardown order
└── terraform/
    ├── versions.tf           ← required providers (hashicorp/aws; no awscc)
    ├── providers.tf          ← aws wired to the MANAGEMENT-account profile/region
    ├── variables.tf          ← workshop_id, parent_id, account_ids, kiro_allowed_actions, budgets, aws_profile …
    ├── organizations.tf      ← the single workshop OU + placement of pre-existing accounts
    ├── scps.tf               ← Kiro guardrail (attached) + freeze (unattached) SCPs
    ├── budgets.tf            ← execution role, per-account budgets, AUTOMATIC freeze actions
    ├── outputs.tf            ← OU / SCP / role / per-account budget identifiers
    ├── backend.tf            ← tracked, value-free S3 backend block (partial config)
    └── backend.hcl.example   ← template for the manual backend.hcl (normally auto-written)
```

## Running it

The step-by-step order — the Step 0 management-account precondition, the
backend-bootstrap → plan → apply sequence, the account-placement mechanism and
`moveAccount` fallback, the automatic freeze behavior, the manual un-freeze, and
the guarded teardown — lives in [`RUNBOOK.md`](./RUNBOOK.md).

```bash
mise run governance-plan     # DRY RUN: tofu init + plan, mutates nothing
mise run governance-apply    # apply against the management account (prompts; high blast radius)
```

Verification across the stack is `tofu fmt` / `tofu validate` / `tofu plan`
only. **Applying mutates the live management account and needs an operator's
explicit go-ahead.**
