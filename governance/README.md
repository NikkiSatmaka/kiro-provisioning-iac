# Governance (step 4 of the flow) — a workshop's accounts under one OU, a guardrail, and auto-freeze budgets

> Phase link: this is **Step 4** of the root [`README.md`](../README.md) flow.
> Prerequisites: Step 1 (backend), Step 3 (governance-shared), and the
> workshop's member accounts already in the organization · Next: Step 5
> ([`subscription/README.md`](../subscription/README.md)).

## Do I need this step?

**Are you running against the AWS Organizations _management account_?** That is
the account that owns AWS Organizations. Which account your `AWS_PROFILE` points
at decides your answer.

- **Yes — organization mode:** **perform** this step (and Step 3,
  governance-shared, which comes first).
- **No — a child/member account (account mode):** **skip** this step and
  Step 3; go straight to Step 5 ([`subscription/README.md`](../subscription/README.md)).

Why: this stack creates and manages AWS Organizations resources — an
organizational unit (OU), a Service Control Policy (SCP) attachment, and
organization-wide budget actions — that only exist in the management account. A
child account has none of them.

## What it is

This is the per-workshop half of the Governance track. For **one** workshop it
creates **exactly one OU** (an *organizational unit* — a folder in AWS
Organizations that groups accounts), **attaches** the shared deny-by-default
Kiro guardrail SCP to that OU, and wires **per-account budgets** that
**automatically freeze** only the account that overruns its limit. An **SCP**
(Service Control Policy) is an organization-wide permission boundary: anything
not explicitly allowed is denied for every account under the OU.

It does **not** create the guardrail SCP, the freeze SCP, or the budgets
execution role. Those are once-per-management-account shared primitives owned by
Step 3 ([`governance-shared/README.md`](../governance-shared/README.md)) and
passed into this stack by id/ARN:

| From governance-shared        | Governance input                 | Used for                                     |
| ----------------------------- | -------------------------------- | -------------------------------------------- |
| `budgets_execution_role_arn`  | `var.budgets_execution_role_arn` | the role each budget's freeze action assumes |
| `kiro_guardrail_scp_id`       | `var.kiro_guardrail_scp_id`      | the policy id attached to this workshop's OU |
| `freeze_scp_id`               | `var.freeze_scp_id`              | the policy id Budgets attaches on breach     |

Running `governance-shared-apply` (Step 3) prints these three values as
`TF_VAR_*` export lines; export them before `governance-apply`. The
`governance-*` tasks fail closed if any is unset. The guardrail allowlist is
tuned **once**, in governance-shared — it is a single org-standard policy, not a
per-workshop knob.

Like every stack here it runs with **management-account** (or delegated
Organizations-admin) credentials. What is distinct is what it *targets*: the SCP
attachment and the budgets act on the **member accounts** moved into the
workshop OU, not on the management account itself.

**One OU, nothing else owned.** The OU is the only resource this stack owns. The
pre-existing accounts in `var.account_ids` are moved into it **out-of-band** (by
`governance-place-accounts`, below), not as Terraform resources — the stack
never creates, invites, closes, or owns an account. This is deliberate:
`hashicorp/aws` has no standalone "move account into an OU" resource, and the
only resource carrying account→OU placement is the *create-an-account* resource,
so expressing placement in Terraform would risk minting brand-new accounts.
Moving placement out-of-band makes that impossible.

**The guardrail attachment (deny-by-default).** The guardrail SCP is created in
governance-shared as a single allowlist. This stack **attaches** it to the
workshop OU, so every account in the OU is bounded to exactly the allowed
actions and everything else is implicitly denied.

**The automatic per-account budget freeze.** Each account in `var.account_ids`
gets its own `COST` budget scoped to just that account, with a tiered set of
actual-cost alerts to every address in `var.notification_emails`: one notify-only
alert per entry in `var.notify_threshold_percents` (default `[50, 75]`) plus a
required alert at `var.freeze_threshold_percent` (default `90`). On breach of the
freeze threshold, AWS Budgets assumes the shared execution role and attaches the
shared deny-all freeze SCP to the **single breaching account only — never the
OU**, so one account's overrun freezes that account and leaves the rest of the
workshop running. The freeze is **automatic** (no human in the loop); a breach
is never silent.

**Un-freezing is manual, by design.** There is no un-freeze automation and no
`governance-unfreeze` task. To restore a frozen account you detach the freeze
SCP by hand (console: **AWS Organizations → the frozen account → Policies →
Service control policies → detach** the `freeze-<id>` policy; or
`aws organizations detach-policy --policy-id <freeze_scp_id> --target-id <account_id>`).
Detaching leaves the OU-level guardrail in place, so the account returns to its
normal Kiro-only boundary. Address the overrun (or raise the budget) first, or
the next breach re-attaches it.

> ⚠️ **High blast radius.** `governance-apply` mutates the live AWS Organizations
> management account — it creates the OU, attaches the guardrail SCP, and wires
> the automatic freeze actions. Approve only with an explicit go-ahead.

## Prerequisites

- **Step 1 — backend.** The shared S3 remote-state backend exists and
  `governance/terraform/backend.hcl` has been written (the `backend-bootstrap`
  task in [`backend/README.md`](../backend/README.md) writes every stack's
  file). The `governance-*` tasks fail closed without it.
- **Step 3 — governance-shared applied, in this management account.** This stack
  consumes its three outputs. Export the three `TF_VAR_*` values that
  `governance-shared-apply` prints before you run `governance-apply`
  (`TF_VAR_budgets_execution_role_arn`, `TF_VAR_kiro_guardrail_scp_id`,
  `TF_VAR_freeze_scp_id`).
- **All-features mode + the `SERVICE_CONTROL_POLICY` policy type enabled on the
  org root.** This one-time, console-only management-account action is handled
  in Step 3 (governance-shared creates the SCP policy objects, so it needs the
  precondition first). By the time you run governance, the policy type is live
  and this stack's attachment just works. If it is missing, the apply fails with
  an AWS Organizations authorization / policy-type error.
- **The workshop's member accounts already exist in the organization.** This
  stack never creates or invites accounts.
- **Required inputs**, set in the git-ignored `.env` or exported as `TF_VAR_*`:
  `WORKSHOP_ID` (the per-workshop slug; names the OU `workshop-<id>`),
  `TF_VAR_parent_id` (the parent OU / org root the workshop OU hangs under),
  `TF_VAR_account_ids` (the pre-existing, in-org 12-digit account ids),
  `TF_VAR_notification_emails` (**required**, non-empty — a breach must never be
  silent), and `TF_VAR_aws_profile` (the management / Org-admin credentials).

## How to run

Run these in order. The dry run reports the plan and changes nothing; apply
mutates the live management account and prompts you to approve.

1. **`mise run governance-plan`** — dry run. Runs `tofu init` + `plan` for this
   workshop's governance key and reports what would change; mutates nothing. A
   clean plan shows one OU (`workshop-<id>`), the guardrail SCP attached to it,
   one COST budget per account, and one `AUTOMATIC` freeze action per account.
   The accounts themselves are **not** in the plan — the stack owns no account
   resource.
2. **`mise run governance-apply`** — apply against the management account.
   Prompts to approve (no auto-approve), then echoes the stack outputs
   (`workshop_ou_id` and the per-account budget identifiers).
3. **`mise run governance-place-accounts`** — move the pre-existing accounts
   into the new OU. This is a real AWS Organizations mutation done out-of-band
   (`aws organizations move-account` once per id), not a Terraform apply. It
   reads the account ids from the stack's `account_ids` output — so
   `terraform.tfvars` is the single source of truth, nothing to retype — and is
   idempotent (an account already in the OU is skipped). Set `ACCOUNT_IDS` only
   to move a deliberate subset.

Authoring and reviewing the stack uses `tofu fmt` / `tofu validate` /
`tofu plan` only. Applying needs an operator's explicit go-ahead.

## Teardown

See the root [`TEARDOWN.md`](../TEARDOWN.md) for how to remove this stack — it is
a two-step, typed-phrase-guarded teardown (move the accounts out of the OU, then
destroy), and those detailed steps live there.
