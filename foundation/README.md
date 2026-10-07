# Foundation stack (adopt the IdC instance — dual-mode, read-only)

This is **Phase 2** of the root README journey.

- **Prerequisites:** Phase 1 backend bootstrap done
  ([`../backend/README.md`](../backend/README.md)) and IAM Identity Center
  **enabled in the credentialed account** — the management account in
  organization mode, or the child/member account in account mode
  ([`RUNBOOK.md`](./RUNBOOK.md) Step 0).
- **Next:** Phase 3 — Provision ([`../subscription/README.md`](../subscription/README.md)).

The stack that **adopts (reads) the IAM Identity Center instance once per
account and hands its IDs forward** to every workshop's `subscription/` stack.
It is **dual-mode** and **account-safe**: it creates nothing, so it runs equally
in the management account or a child account.

- **organization mode** (default) — run under a management-account profile; it
  adopts the single **organization** instance (today's behavior).
- **account mode** — run under a **child/member account**'s profile; it adopts
  that account's **own IdC account instance**.

The same `data "aws_ssoadmin_instances"` data source resolves per-account, so
there is no `instance_mode` input here — the credentialed account decides which
instance is adopted.

> ⚠️ **Nothing here runs automatically.** Every step is manual or driven by an
> explicit `mise run` task you invoke. [`RUNBOOK.md`](./RUNBOOK.md) is the
> end-to-end read-then-wire order. `foundation-apply` is a **pure read** — it
> adopts the instance and prints the two IDs to wire forward; it mutates
> nothing.

> **What moved out.** Foundation used to also create the shared budgets
> execution role and the two SCP policy objects (Kiro guardrail + deny-all
> freeze). Those are AWS Organizations / management-account resources that
> **fail in a child account**, so they moved to the new management-only
> [`../governance-shared/`](../governance-shared/README.md) stack. Foundation is
> now purely read-only IdC adoption, which is what lets it run in a child
> account.

**Scope of this doc.** This README explains the concepts behind the foundation
stack — the adopted IdC instance, the dual-mode behavior, the decoupling
boundary, and the shared backend. For the step-by-step run order, use
[`RUNBOOK.md`](./RUNBOOK.md). For the overall repo journey, start at the
[root `README.md`](../README.md).

## Why it exists

One job: **adopt the IdC instance once per account and expose its IDs so the
per-workshop subscription stack never has to hunt them down.**

The `subscription/` stack **consumes** the IdC instance through two
operator-supplied inputs (`var.idc_instance_arn`, `var.identity_store_id`)
instead of creating it. This stack resolves those two IDs from whichever
instance the credentialed account exposes (the organization instance in the
management account, or the account instance in a child account) so the
subscription stack is free to consume them.

The adopted instance is **read/reused across every workshop** — never per
workshop. The foundation stack sits outside the per-workshop provision/teardown
loop entirely:

```
backend/        (run once; local state; S3 bucket + lock table)
    │
    ▼
foundation/     (run once per account; state key foundation/terraform.tfstate)
    reads  ONE IdC instance (data "aws_ssoadmin_instances")
           - organization instance   (management account), or
           - account instance         (child/member account)
    emits   instance_arn / identity_store_id / region / sign_in_url
    │  operator exports the IDs forward (NOT remote state)
    └──────────────▶ subscription/ (per workshop; consumes the two IdC IDs)
```

## Dual-mode: organization vs account instance

Foundation adopts whichever instance the credentialed account exposes — no
input selects the mode:

| | organization mode (default) | account mode |
| --- | --- | --- |
| `AWS_PROFILE` | management-account profile | **child/member account's** profile |
| Adopted instance | the org instance | the child's own account instance |
| Downstream subscription | run in management account | run in the same child account (`instance_mode = "account"`) |

**Caution (R-2).** If you run foundation with a **management-account** profile
while intending account mode, the data source silently resolves the
**organization** instance and you will wire the wrong IDs forward. Confirm the
profile points at the intended account (`mise run verify`) before applying.

## The adopted IdC instance (read-only)

This stack **reads exactly one** IdC instance via
`data "aws_ssoadmin_instances" "this"` and touches **nothing else** from the
Identity Center surface — no users, groups, memberships, permission sets, or
account assignments. Those all stay in the `subscription/` stack. It never
creates or destroys the instance.

The `hashicorp/aws` provider is the only provider this stack needs; the
`data "aws_ssoadmin_instances"` data source returns the adopted instance's ARN
and identity store id, and `data.aws_region.current` resolves the concrete
region for the `region` output.

Exactly **one instance is exposed per account** (one organization instance in
the management account, or one account instance in a child account). Enabling
IdC in that account is a one-time console action (Step 0 in the RUNBOOK). If IdC
has never been enabled, the data source returns no instance and plan fails —
that is the missing Step 0 (now applicable per-account), not something this
stack repairs.

## Decoupling via variables (not remote state)

The stacks are wired together **by the operator through explicit variables**,
never by a remote-state reference. The foundation stack EMITS outputs; the
operator copies/exports the IDs into the subscription stack's inputs.

Into the **subscription** stack (the IdC handoff):

| Foundation output   | Subscription input          |
| ------------------- | --------------------------- |
| `instance_arn`      | `TF_VAR_idc_instance_arn`   |
| `identity_store_id` | `TF_VAR_identity_store_id`  |
| `region`            | (informational)             |
| `sign_in_url`       | (informational)             |

The three shared-primitive IDs the `governance/` stack consumes
(`budgets_execution_role_arn`, `kiro_guardrail_scp_id`, `freeze_scp_id`) are
**no longer emitted here** — they come from
[`../governance-shared/`](../governance-shared/README.md).

Because the handoff is explicit:

- The foundation stack exposes its values **only as outputs** — never anywhere
  the consuming stack reads via remote state.
- The subscription stack keeps reading `var.idc_instance_arn` /
  `var.identity_store_id`, exactly as it does today.
- No stack declares a `data "terraform_remote_state"` referencing another. Each
  stack can be planned, applied, or destroyed on its own.

## Shared backend with a foundation-scoped key

The foundation stack uses the **same shared S3 backend** as the other stacks:
a tracked, value-free `backend "s3" {}` block (`backend.tf`) plus a git-ignored,
keyless `backend.hcl` whose values are supplied at `tofu init` time. The
`backend-bootstrap` task writes that `backend.hcl` for you (same bucket + lock
table as the other stacks).

The one difference from the per-workshop stacks is the state **key**. Because
the adopted IdC instance is a single per-account resource — not workshop-scoped
— the key is the bare `foundation/terraform.tfstate`, with **no
`workshops/<id>/` prefix**:

```
foundation/terraform.tfstate                      ← this stack (no workshop prefix)
governance-shared/terraform.tfstate               ← management-account singletons
workshops/<id>/subscription/terraform.tfstate
workshops/<id>/claim-service/terraform.tfstate
```

The `backend.hcl` body is byte-identical across every stack (keyless); isolation
comes entirely from the init-time key, not from the file. See
[`../backend/README.md`](../backend/README.md) for how the bootstrap renders and
writes each stack's `backend.hcl`.

## Repo layout

```
foundation/
├── README.md                 ← you are here (concepts)
├── RUNBOOK.md                ← read-then-wire run order + the per-account IdC step
└── terraform/
    ├── versions.tf           ← required providers (hashicorp/aws only)
    ├── providers.tf          ← aws provider (dual-mode: management or child account profile/region)
    ├── variables.tf          ← aws_region, aws_profile, default_tags
    ├── identity_center.tf    ← data "aws_ssoadmin_instances" "this" (read-only adopt)
    ├── outputs.tf            ← instance_arn, identity_store_id, region, sign_in_url
    ├── backend.tf            ← tracked, value-free S3 backend block (partial config)
    └── backend.hcl.example   ← template for manual backend.hcl (normally auto-written)
```

This stack is dual-mode: `AWS_PROFILE` is a management-account profile in
organization mode, or the child account's profile in account mode.

## Inputs

| Variable       | Purpose                                                        |
| -------------- | -------------------------------------------------------------- |
| `aws_region`   | Provider region; empty falls back to `AWS_REGION`.             |
| `aws_profile`  | Management-account profile (org mode) or the child account's profile (account mode); empty falls back to the env. |
| `default_tags` | Tags applied to every taggable resource via the provider.      |

## Outputs

Read-only IdC handoff: `instance_arn`, `identity_store_id`, `region`,
`sign_in_url`.

## Running it

The step-by-step order — the per-account IdC prerequisite, the
backend-bootstrap → foundation-apply → wire-forward sequence, idempotency, and
why there is nothing to tear down — lives in [`RUNBOOK.md`](./RUNBOOK.md).

```bash
mise run foundation-plan     # DRY RUN: tofu init + plan, a pure read (0 to add)
mise run foundation-apply    # adopt the IdC instance AND print the TF_VAR_* export lines
```
