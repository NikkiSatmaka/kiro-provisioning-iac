# governance-shared stack (the management-account singleton primitives)

This is the **shared** half of the optional Governance track (see the journey
table in the root [`README.md`](../README.md)). It is **management-account
only** — it creates AWS Organizations resources that cannot exist in a child
account — and it is **not** part of the linear Phase 0→4 provisioning flow.

- **Prerequisites:** Phase 0 (toolchain + management-account auth), Phase 1
  (shared backend), and the organization's **all-features mode** +
  `SERVICE_CONTROL_POLICY` policy type enabled on the root
  ([`RUNBOOK.md`](./RUNBOOK.md) Step 0).
- **Next:** per-workshop [`../governance/RUNBOOK.md`](../governance/RUNBOOK.md),
  which consumes this stack's three outputs as `TF_VAR_*`.

The stack that owns the **once-per-management-account singletons** every
workshop's `governance/` stack consumes:

- the least-privilege **budgets execution role** AWS Budgets assumes to attach
  the freeze SCP (`governance-budgets-exec`),
- the **Kiro guardrail SCP** policy object (a single org-standard allowlist,
  `kiro-guardrail`), and
- the deny-all **freeze SCP** policy object (`freeze`).

It creates the policy OBJECTS and the role only; it attaches nothing. Per-workshop
`governance/` attaches the guardrail to each workshop OU, and AWS Budgets
attaches the freeze SCP to a breaching account automatically.

## Why these left `foundation/`

These three resources used to live in `foundation/`. But `foundation/` is now
**dual-mode and account-safe**: it must run in a child/member account too (to
adopt that account's own IdC instance — see
[`../foundation/README.md`](../foundation/README.md)). AWS Organizations SCPs and
the Organizations-scoped budgets role **cannot be created in a child account**,
so keeping them in `foundation/` would break account mode.

They could not move into per-workshop `governance/` either: their names are
**unsuffixed singletons** (`kiro-guardrail`, `freeze`, `governance-budgets-exec`),
so two workshops both applying `governance/` would collide on those names. The
resolution is this dedicated **management-only, run-once** stack that owns them
as singletons, mirroring how `foundation/` owns its single IdC adoption.

## The wire-forward into per-workshop governance

`governance/` **consumes** these three by id/ARN as required variables (no
defaults — a missing wire-forward fails closed), exactly as it did when they came
from `foundation/`. Only the source changed:

| governance-shared output     | governance input                  | Used for                                     |
| ---------------------------- | --------------------------------- | -------------------------------------------- |
| `budgets_execution_role_arn` | `var.budgets_execution_role_arn`  | the role each budget's freeze action assumes |
| `kiro_guardrail_scp_id`      | `var.kiro_guardrail_scp_id`       | the policy id attached to each workshop OU   |
| `freeze_scp_id`              | `var.freeze_scp_id`               | the policy id Budgets attaches on breach     |

Run `governance-shared-apply` **once per management account** and export the
three `TF_VAR_*` values it prints before any `governance-apply`.

The guardrail allowlist (`var.kiro_allowed_actions`) is defined **once here** —
a single org-standard policy shared by every workshop, not a per-workshop knob.
Widen or narrow it here, deliberately, for the whole management account.

## Resources this stack owns

- **Budgets execution role** (`governance-budgets-exec`). Least-privilege IAM
  role AWS Budgets assumes to attach/detach the freeze SCP. Its trust policy
  carries the confused-deputy guard `aws:SourceAccount == <this management
  account>` (resolved via `data.aws_caller_identity.current`, which — because
  this stack runs management-only — is the management account id). Permissions
  are scoped to the Organizations attach/detach of the freeze SCP plus the
  minimal reads Budgets needs; no org-wide admin.
- **Kiro guardrail SCP** (`kiro-guardrail`). A deny-by-default allowlist: a
  single `Allow` of `var.kiro_allowed_actions` on `*`. Created here, attached by
  `governance/`.
- **Freeze SCP** (`freeze`). A static deny-all policy, created **unattached**.
  AWS Budgets attaches it to a single breaching account on budget breach.

## Shared backend with a singleton key

This stack uses the **same shared S3 backend** as the other stacks: a tracked,
value-free `backend "s3" {}` block (`backend.tf`) plus a git-ignored, keyless
`backend.hcl` supplied at `tofu init` time. The `backend-bootstrap` task writes
that `backend.hcl` for you.

Its state **key** is the bare `governance-shared/terraform.tfstate` — **no
`workshops/<id>/` prefix**, because these are management-account singletons,
mirroring `foundation/terraform.tfstate`:

```
governance-shared/terraform.tfstate                ← this stack (no workshop prefix)
foundation/terraform.tfstate                        ← no workshop prefix
workshops/<id>/governance/terraform.tfstate
workshops/<id>/subscription/terraform.tfstate
workshops/<id>/claim-service/terraform.tfstate
```

## State migration from `foundation/` (existing deployments)

If you already applied `foundation/` before this refactor, the three resources
(plus their policy documents) are **live in `foundation/`'s tfstate** and the
guardrail SCP is **attached to live workshop OUs**. Moving the HCL here does
**not** move the state — you must migrate it with `tofu state mv`. The exact,
non-destructive operator procedure (and the live-resource warning) is in
[`RUNBOOK.md`](./RUNBOOK.md#state-migration-from-foundation-non-destructive). Do
not re-create the resources from scratch on a live environment.

## Repo layout

```
governance-shared/
├── README.md                 ← you are here (concepts)
├── RUNBOOK.md                ← run order + the one-time state migration from foundation
└── terraform/
    ├── versions.tf           ← required providers (hashicorp/aws only)
    ├── providers.tf          ← aws wired to the MANAGEMENT-account profile/region (not dual-mode)
    ├── variables.tf          ← aws_region, aws_profile, default_tags, kiro_allowed_actions
    ├── scps.tf               ← Kiro guardrail SCP + deny-all freeze SCP (policy objects)
    ├── budgets_role.tf       ← shared budgets execution role (trust + least-privilege policy)
    ├── outputs.tf            ← budgets_execution_role_arn, kiro_guardrail_scp_id, freeze_scp_id
    ├── backend.tf            ← tracked, value-free S3 backend block (partial config)
    └── backend.hcl.example   ← template for the manual backend.hcl (normally auto-written)
```

This stack targets the AWS Organizations **management account**; `AWS_PROFILE`
must be a management-account (or delegated Org-admin) profile. It is **not**
dual-mode and never runs in a child account.

## Inputs

| Variable               | Purpose                                                                     |
| ---------------------- | --------------------------------------------------------------------------- |
| `kiro_allowed_actions` | Allowlist for the shared Kiro guardrail SCP — a **tunable** conservative default (org-wide, not per workshop). |
| `aws_region`           | Provider region; empty falls back to `AWS_REGION`.                          |
| `aws_profile`          | **Management-account / Org-admin** profile; empty falls back to the env.    |
| `default_tags`         | Tags applied to every taggable resource via the provider.                   |

## Outputs

`budgets_execution_role_arn`, `kiro_guardrail_scp_id`, `freeze_scp_id` — the
three the per-workshop `governance/` stack consumes.

## Running it

```bash
mise run governance-shared-plan     # DRY RUN: tofu init + plan (shows the role + 2 SCPs to add)
mise run governance-shared-apply    # create them AND print the TF_VAR_* export lines
```

The full run order (Step 0 precondition, backend bootstrap, apply, the
wire-forward, and the one-time state migration) lives in
[`RUNBOOK.md`](./RUNBOOK.md).
