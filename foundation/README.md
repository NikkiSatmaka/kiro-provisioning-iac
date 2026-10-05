# Foundation IdC service (the account-level Identity Center instance)

The one stack that **creates and owns** the account-level IAM Identity Center
(IdC) instance every workshop's `subscription/` stack consumes. Apply it
**once per account**, after the `backend/` bootstrap and before the
`subscription/` stack.

> ⚠️ **Nothing here runs automatically.** Every step is manual or driven by an
> explicit `mise run` task you invoke. [`RUNBOOK.md`](./RUNBOOK.md) is the
> end-to-end create-then-wire order, including the one-time management-account
> step AWS only exposes through the console.

**Scope of this doc.** This README explains the concepts behind the foundation
stack — the single owned resource, the decoupling boundary, and the shared
backend. For the step-by-step run order, use [`RUNBOOK.md`](./RUNBOOK.md). For
the overall repo journey (toolchain setup, the shared state backend, and
distributing the result), start at the [root `README.md`](../README.md).

## Why it exists

The `multi-workshop-provisioning` work changed the `subscription/` stack to
**consume** the IdC instance through two operator-supplied inputs
(`var.idc_instance_arn`, `var.identity_store_id`) instead of creating it. That
left the creation of the account instance without a home. This stack is that
home: a single, long-lived place that owns the shared instance so the
subscription stack is free to consume it.

The IdC instance is a shared foundation resource. It is applied **once and
reused across every workshop** — never per workshop. The foundation stack sits
outside the per-workshop provision/teardown loop entirely:

```
backend/        (run once; local state; S3 bucket + lock table)
    │
    ▼
foundation/     (run once; state key foundation/terraform.tfstate)
    creates ONE awscc_sso_instance "this"
    emits   instance_arn / identity_store_id / region / sign_in_url
    │  operator exports the two IDs (NOT remote state)
    ▼
subscription/   (per workshop; consumes var.idc_instance_arn + var.identity_store_id)
    │
    ▼
claim-service/  (per workshop; optional self-serve distribution)
```

## The single owned resource

This stack creates **exactly one** account-level IdC instance via
`awscc_sso_instance "this"` and **nothing else** from the Identity Center
surface — no users, groups, memberships, permission sets, or account
assignments. Those all stay in the `subscription/` stack.

The `awscc` (AWS Cloud Control) provider is the only provider that can CREATE an
IdC instance (`awscc_sso_instance` maps to the `AWS::SSO::Instance`
CloudFormation type). The `hashicorp/aws` provider is present only to resolve
the concrete region for the `region` output via `data.aws_region.current`.

AWS permits **one account instance per account across all regions**. If the
account already has one (created outside this stack's state), import it rather
than creating a second — see [`RUNBOOK.md`](./RUNBOOK.md).

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
├── RUNBOOK.md                ← create-then-wire run order + the mgmt-account step
└── terraform/
    ├── versions.tf           ← required providers (hashicorp/awscc + hashicorp/aws)
    ├── providers.tf          ← aws + awscc wired to the project profile/region
    ├── variables.tf          ← aws_region, aws_profile, default_tags, instance_name
    ├── identity_center.tf    ← the single awscc_sso_instance "this"
    ├── outputs.tf            ← instance_arn, identity_store_id, region, sign_in_url
    ├── backend.tf            ← tracked, value-free S3 backend block (partial config)
    └── backend.hcl.example   ← template for manual backend.hcl (normally auto-written)
```

## Running it

The step-by-step order — the management-account prerequisite, the
backend-bootstrap → foundation-apply → wire-forward sequence, idempotency and
import, and the guarded teardown — lives in [`RUNBOOK.md`](./RUNBOOK.md).

```bash
mise run foundation-plan     # DRY RUN: tofu init + plan, creates nothing
mise run foundation-apply    # apply AND print the TF_VAR_* export lines to wire forward
```
