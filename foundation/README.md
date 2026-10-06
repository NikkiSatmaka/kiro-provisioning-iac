# Foundation stack (the once-per-management-account shared resources)

This is **Phase 2** of the root README journey.

- **Prerequisites:** Phase 1 backend bootstrap done
  ([`../backend/README.md`](../backend/README.md)), IAM Identity Center enabled
  in the management account, and the organization's SCP policy type enabled
  ([`RUNBOOK.md`](./RUNBOOK.md) Step 0).
- **Next:** Phase 3 — Provision ([`../subscription/README.md`](../subscription/README.md)).

The stack that owns everything defined **once per management account and reused
across every workshop**. Run it **once per management account**, after the
`backend/` bootstrap and before the per-workshop `subscription/` and
`governance/` stacks. Two kinds of thing live here:

- **Read-only adoption** — the management account's existing **organization**
  IAM Identity Center (IdC) instance that every workshop's `subscription/` stack
  consumes. The stack never creates or destroys it.
- **Shared created resources** — resources whose definition is identical for
  every workshop, so they belong here as singletons rather than being recreated
  per workshop by `governance/`:
  - the least-privilege **budgets execution role** AWS Budgets assumes to attach
    the freeze SCP,
  - the **Kiro guardrail SCP** policy (a single org-standard allowlist), and
  - the deny-all **freeze SCP** policy.

  `governance/` consumes these three by id/ARN (wired forward as variables) and
  only creates the **per-workshop** pieces: the OU, account placement, the
  guardrail SCP *attachment* to that OU, and the per-account budgets + freeze
  actions.

> ⚠️ **Nothing here runs automatically.** Every step is manual or driven by an
> explicit `mise run` task you invoke. [`RUNBOOK.md`](./RUNBOOK.md) is the
> end-to-end read-then-wire order, including the one-time management-account
> steps AWS only exposes through the console. Unlike the old pure-read design,
> `foundation-apply` now **creates** the shared budgets role and the two SCP
> policies, so its apply mutates the management account (a small, stable,
> once-per-account footprint — not per workshop).

**Scope of this doc.** This README explains the concepts behind the foundation
stack — the adopted IdC instance, the shared created resources (budgets role +
two SCP policies), the decoupling boundary, and the shared backend. For the
step-by-step run order, use [`RUNBOOK.md`](./RUNBOOK.md). For the overall repo
journey (toolchain setup, the shared state backend, and distributing the
result), start at the [root `README.md`](../README.md).

## Why it exists

Two jobs, one owning principle: **anything defined once per management account
and reused across every workshop lives here, so the per-workshop stacks never
recreate it.**

The `subscription/` stack **consumes** the IdC instance through two
operator-supplied inputs (`var.idc_instance_arn`, `var.identity_store_id`)
instead of creating it. This stack resolves those two IDs from the management
account's existing **organization** instance so the subscription stack is free
to consume them without each operator hunting the ARN down by hand.

The `governance/` stack likewise **consumes** three shared primitives this stack
creates — the budgets execution role, the Kiro guardrail SCP, and the freeze
SCP — through operator-supplied inputs, instead of recreating a near-identical
copy of each per workshop.

Every resource here is **created/read once and reused across every workshop** —
never per workshop. The foundation stack sits outside the per-workshop
provision/teardown loop entirely:

```
backend/        (run once; local state; S3 bucket + lock table)
    │
    ▼
foundation/     (run once; state key foundation/terraform.tfstate)
    reads  ONE org IdC instance (data "aws_ssoadmin_instances")
    creates budgets execution role  (shared; Budgets assumes it)
    creates Kiro guardrail SCP policy (shared org-standard allowlist)
    creates deny-all freeze SCP policy (shared; created unattached)
    emits   instance_arn / identity_store_id / region / sign_in_url
            budgets_execution_role_arn / kiro_guardrail_scp_id / freeze_scp_id
    │  operator exports the IDs forward (NOT remote state)
    ├──────────────▶ subscription/ (per workshop; consumes the two IdC IDs)
    └──────────────▶ governance/   (per workshop; consumes the three shared IDs:
                                     OU + guardrail ATTACHMENT + per-account budgets)
```

## The adopted IdC instance (read-only)

This stack **reads exactly one** organization-level IdC instance via
`data "aws_ssoadmin_instances" "this"` and touches **nothing else** from the
Identity Center surface — no users, groups, memberships, permission sets, or
account assignments. Those all stay in the `subscription/` stack. It never
creates or destroys the instance.

The `hashicorp/aws` provider is the only provider this stack needs; the
`data "aws_ssoadmin_instances"` data source returns the org instance ARN and
identity store id, and `data.aws_region.current` resolves the concrete region
for the `region` output.

Exactly **one organization instance exists per management account**. Enabling
IdC in the management account is a one-time console action (Step 0 in the
RUNBOOK). If IdC has never been enabled, the data source returns no instance and
plan fails — that is the missing Step 0, not something this stack repairs.

## The shared created resources

These three are defined once here and consumed by every workshop's
`governance/` stack. They were previously created per workshop inside
`governance/`; centralizing them removes the near-identical duplication and
makes their single definition the org standard.

- **Budgets execution role.** The least-privilege IAM role AWS Budgets assumes
  to attach/detach the freeze SCP. Its trust policy carries the confused-deputy
  guard `aws:SourceAccount == <this management account>` — a
  per-management-account fact — and its permissions are scoped to the
  Organizations attach/detach of the freeze SCP plus the minimal reads Budgets
  needs. Identical for every workshop, so it is a single shared role (no
  `workshop_id` in its name).

- **Kiro guardrail SCP (policy object).** A deny-by-default allowlist: a single
  `Allow` of the actions in `var.kiro_allowed_actions` on `*`. It is a single
  **org-standard** policy shared by every workshop — `governance/` attaches it
  to each workshop's OU but no longer defines its contents. `var.kiro_allowed_actions`
  ships the same conservative starter default as before (`sso:*`,
  `sso-directory:*`, `identitystore:*`, `signin:*`, `sts:GetCallerIdentity`,
  `codewhisperer:*`, `q:*`); widen or narrow it here, once, for the whole
  management account.

- **Freeze SCP (policy object).** A static deny-all policy, **created but left
  unattached**. AWS Budgets attaches it to a single breaching account
  automatically on budget breach (the per-account budget actions live in
  `governance/`). Because its document never varies, it is a singleton here.

> **Teardown note for the shared resources.** Because these three are shared
> across every workshop, a per-workshop `governance-destroy` **never** deletes
> them — it only removes that workshop's OU, attachment, and budgets. The shared
> role and policies are torn down only when the whole management account is
> decommissioned (see [`RUNBOOK.md`](./RUNBOOK.md) teardown).

## Decoupling via variables (not remote state)

The stacks are wired together **by the operator through explicit variables**,
never by a remote-state reference. The foundation stack EMITS outputs; the
operator copies/exports the IDs into the consuming stack's inputs.

Into the **subscription** stack (the IdC handoff):

| Foundation output   | Subscription input          |
| ------------------- | --------------------------- |
| `instance_arn`      | `TF_VAR_idc_instance_arn`   |
| `identity_store_id` | `TF_VAR_identity_store_id`  |
| `region`            | (informational)             |
| `sign_in_url`       | (informational)             |

Into the **governance** stack (the shared-primitives handoff):

| Foundation output            | Governance input                   |
| ---------------------------- | ---------------------------------- |
| `budgets_execution_role_arn` | `TF_VAR_budgets_execution_role_arn`|
| `kiro_guardrail_scp_id`      | `TF_VAR_kiro_guardrail_scp_id`     |
| `freeze_scp_id`              | `TF_VAR_freeze_scp_id`             |

Because the handoff is explicit:

- The foundation stack exposes these values **only as outputs** — never anywhere
  the consuming stacks read via remote state.
- The subscription stack keeps reading `var.idc_instance_arn` /
  `var.identity_store_id`, exactly as it does today; the governance stack now
  reads the three shared IDs as variables.
- No stack declares a `data "terraform_remote_state"` referencing another. Each
  stack can be planned, applied, or destroyed on its own.

This preserves the decoupling boundary the subscription stack already
established, and extends the same pattern to governance.

## Shared backend with a foundation-scoped key

The foundation stack uses the **same shared S3 backend** as the other stacks:
a tracked, value-free `backend "s3" {}` block (`backend.tf`) plus a git-ignored,
keyless `backend.hcl` whose values are supplied at `tofu init` time. The
`backend-bootstrap` task writes that `backend.hcl` for you (same bucket + lock
table as the subscription and claim-service stacks).

The one difference from the sibling stacks is the state **key**. Because the IdC
instance is a single shared foundation resource — not workshop-scoped — the key
is the bare `foundation/terraform.tfstate`, with **no `workshops/<id>/`
prefix**:

```
foundation/terraform.tfstate                      ← this stack (no workshop prefix)
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
├── RUNBOOK.md                ← read-then-wire run order + the mgmt-account steps
└── terraform/
    ├── versions.tf           ← required providers (hashicorp/aws only)
    ├── providers.tf          ← aws provider wired to the management-account profile/region
    ├── variables.tf          ← aws_region, aws_profile, default_tags, kiro_allowed_actions
    ├── identity_center.tf    ← data "aws_ssoadmin_instances" "this" (read-only adopt)
    ├── budgets_role.tf       ← shared budgets execution role (trust + least-privilege policy)
    ├── scps.tf               ← shared Kiro guardrail SCP + deny-all freeze SCP (policy objects)
    ├── outputs.tf            ← instance_arn, identity_store_id, region, sign_in_url,
    │                           budgets_execution_role_arn, kiro_guardrail_scp_id, freeze_scp_id
    ├── backend.tf            ← tracked, value-free S3 backend block (partial config)
    └── backend.hcl.example   ← template for manual backend.hcl (normally auto-written)
```

This stack targets the AWS Organizations **management account**; `AWS_PROFILE`
must be a management-account profile.

## Inputs

| Variable               | Purpose                                                                     |
| ---------------------- | --------------------------------------------------------------------------- |
| `kiro_allowed_actions` | Allowlist for the shared Kiro guardrail SCP — a **tunable** conservative default (org-wide, not per workshop). |
| `aws_region`           | Provider region; empty falls back to `AWS_REGION`.                          |
| `aws_profile`          | **Management-account** profile; empty falls back to the env.                |
| `default_tags`         | Tags applied to every taggable resource via the provider.                   |

## Outputs

Read-only IdC handoff: `instance_arn`, `identity_store_id`, `region`,
`sign_in_url`.

Shared-primitive handoff into `governance/`: `budgets_execution_role_arn`,
`kiro_guardrail_scp_id`, `freeze_scp_id`.

## Running it

The step-by-step order — the management-account prerequisite, the
backend-bootstrap → foundation-apply → wire-forward sequence, idempotency, and
why there is nothing to tear down — lives in [`RUNBOOK.md`](./RUNBOOK.md).

```bash
mise run foundation-plan     # DRY RUN: tofu init + plan (reads IdC; shows the shared role + 2 SCPs to add)
mise run foundation-apply    # read IdC, create the shared role + SCPs, AND print the TF_VAR_* export lines
```
