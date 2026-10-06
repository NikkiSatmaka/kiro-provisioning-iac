# Foundation IdC service (adopts the organization Identity Center instance)

The one stack that **adopts (reads)** the management account's existing
**organization** IAM Identity Center (IdC) instance that every workshop's
`subscription/` stack consumes. Run it **once per management account**, after
the `backend/` bootstrap and before the `subscription/` stack. It creates
nothing and owns nothing — it is a pure read.

> ⚠️ **Nothing here runs automatically.** Every step is manual or driven by an
> explicit `mise run` task you invoke. [`RUNBOOK.md`](./RUNBOOK.md) is the
> end-to-end read-then-wire order, including the one-time management-account
> step AWS only exposes through the console.

**Scope of this doc.** This README explains the concepts behind the foundation
stack — the single adopted resource, the decoupling boundary, and the shared
backend. For the step-by-step run order, use [`RUNBOOK.md`](./RUNBOOK.md). For
the overall repo journey (toolchain setup, the shared state backend, and
distributing the result), start at the [root `README.md`](../README.md).

## Why it exists

The `subscription/` stack **consumes** the IdC instance through two
operator-supplied inputs (`var.idc_instance_arn`, `var.identity_store_id`)
instead of creating it. This stack resolves those two IDs from the management
account's existing **organization** instance so the subscription stack is free
to consume them without each operator hunting the ARN down by hand.

The org IdC instance is a shared foundation resource. It is read **once and
reused across every workshop** — never per workshop. The foundation stack sits
outside the per-workshop provision/teardown loop entirely:

```
backend/        (run once; local state; S3 bucket + lock table)
    │
    ▼
foundation/     (run once; state key foundation/terraform.tfstate)
    reads ONE org IdC instance (data "aws_ssoadmin_instances")
    emits   instance_arn / identity_store_id / region / sign_in_url
    │  operator exports the two IDs (NOT remote state)
    ▼
subscription/   (per workshop; consumes var.idc_instance_arn + var.identity_store_id)
    │
    ▼
claim-service/  (per workshop; optional self-serve distribution)
```

## The single adopted resource

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

## Decoupling via variables (not remote state)

The two stacks are wired together **by the operator through explicit
variables**, never by a remote-state reference. The foundation stack EMITS four
outputs; the operator copies/exports the two IDs into the subscription stack's
inputs:

| Foundation output   | Subscription input          |
| ------------------- | --------------------------- |
| `instance_arn`      | `TF_VAR_idc_instance_arn`   |
| `identity_store_id` | `TF_VAR_identity_store_id`  |
| `region`            | (informational)             |
| `sign_in_url`       | (informational)             |

Because the handoff is explicit:

- The foundation stack exposes the instance ARN and identity store id **only as
  outputs** — never anywhere the subscription stack reads via remote state.
- The subscription stack keeps reading `var.idc_instance_arn` /
  `var.identity_store_id`, exactly as it does today.
- Neither stack declares a `data "terraform_remote_state"` referencing the
  other. Either stack can be planned, applied, or destroyed on its own.

This preserves the decoupling boundary the subscription stack already
established.

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
├── RUNBOOK.md                ← read-then-wire run order + the mgmt-account step
└── terraform/
    ├── versions.tf           ← required providers (hashicorp/aws only)
    ├── providers.tf          ← aws provider wired to the management-account profile/region
    ├── variables.tf          ← aws_region, aws_profile, default_tags
    ├── identity_center.tf    ← data "aws_ssoadmin_instances" "this" (read-only adopt)
    ├── outputs.tf            ← instance_arn, identity_store_id, region, sign_in_url
    ├── backend.tf            ← tracked, value-free S3 backend block (partial config)
    └── backend.hcl.example   ← template for manual backend.hcl (normally auto-written)
```

This stack targets the AWS Organizations **management account**; `AWS_PROFILE`
must be a management-account profile.

## Running it

The step-by-step order — the management-account prerequisite, the
backend-bootstrap → foundation-apply → wire-forward sequence, idempotency, and
why there is nothing to tear down — lives in [`RUNBOOK.md`](./RUNBOOK.md).

```bash
mise run foundation-plan     # DRY RUN: tofu init + plan, a pure read (0 to add)
mise run foundation-apply    # resolve the IDs AND print the TF_VAR_* export lines to wire forward
```
