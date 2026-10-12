# Governance-shared (step 3 of the flow) — the management-account singleton primitives

> Phase link: this is **Step 3** of the root [`README.md`](../README.md) flow.
> Prerequisites: Step 1 (backend) and Step 2 (foundation) · Next: Step 4,
> [`../governance/README.md`](../governance/README.md).

## Do I need this step?

**Are you running against the AWS Organizations _management account_?**

- **Yes — organization mode (the management account):** perform this step, then
  perform step 4 ([`governance`](../governance/README.md)).
- **No — a child/member account (account mode):** **skip** this step and step 4.
  Go straight to step 5, [`subscription`](../subscription/README.md).

Why: this stack creates AWS Organizations resources — Service Control Policies
(SCPs) and an Organizations-scoped IAM role — that **only exist in the
management account**. A child/member account cannot create them, so the whole
governance track does not apply in account mode.

Here, **organization mode** means you are signed in to the AWS Organizations
**management account** (the account that owns the organization). **Account mode**
means you are signed in to a **child/member account** that only manages itself.

## What it is

This stack owns the **once-per-management-account singletons** that every
workshop's `governance/` stack (step 4) consumes. It creates three things, and
attaches nothing:

- The **budgets execution role** (`governance-budgets-exec`) — a least-privilege
  IAM role that AWS Budgets assumes to attach the "freeze" policy to a breaching
  account.
- The **Kiro guardrail SCP** (`kiro-guardrail`) — a Service Control Policy, which
  is an organization-wide allowlist of permitted actions. One org-standard policy
  shared by every workshop, not a per-workshop knob.
- The deny-all **freeze SCP** (`freeze`) — a policy that denies everything,
  created **unattached**. AWS Budgets attaches it to a single breaching account
  automatically when that account blows its budget.

It creates the policy **objects** and the role only. Per-workshop `governance/`
(step 4) attaches the guardrail to each workshop's organizational unit (OU) — an
OU is a folder in AWS Organizations that groups accounts — and AWS Budgets
attaches the freeze policy on a breach.

### Why this is a separate, run-once stack

These three resources used to live in `foundation/` (step 2). But `foundation/`
is now **dual-mode and account-safe** — it must also run in a child/member
account to adopt that account's own Identity Center instance. AWS Organizations
SCPs and the Organizations-scoped budgets role **cannot be created in a child
account**, so keeping them in `foundation/` would break account mode.

They could not move into per-workshop `governance/` either: their names are
**unsuffixed singletons** (`kiro-guardrail`, `freeze`, `governance-budgets-exec`),
so two workshops both applying `governance/` would collide on those names. The
resolution is this dedicated management-only, run-once stack that owns them as
singletons — mirroring how `foundation/` owns its single Identity Center
adoption.

The guardrail allowlist (`var.kiro_allowed_actions`) is defined **once here** —
a single org-standard policy shared by every workshop. Widen or narrow it here,
deliberately, for the whole management account.

## Prerequisites

Before running this stack:

1. **Step 1 (backend) is applied.** The shared S3 remote-state backend must
   exist and this stack's `backend.hcl` must be written. The `backend-bootstrap`
   task writes it for you (it writes every stack's `backend.hcl` in one run).
   The `governance-shared-*` tasks fail closed without it.
2. **Step 2 (foundation) is applied** for the account in use.
3. **You are authenticated as the management account** (or a delegated
   Organizations administrator). `AWS_PROFILE` comes from the git-ignored `.env`;
   this stack is **not** dual-mode and never runs in a child account.
4. **One-time platform precondition: all-features mode + the SCP policy type is
   enabled.** Service Control Policies only work when AWS Organizations is in
   **"all features"** mode **and** the `SERVICE_CONTROL_POLICY` policy type is
   **enabled on the organization root**. This is a management-account console
   action that this stack **cannot perform**:
   - Sign in to the management account and open **AWS Organizations** in the
     console.
   - Confirm the org is in **all features** mode (**Settings** → enable all
     features if it still shows consolidated-billing-only). This is one-time and
     irreversible.
   - Enable the **Service control policies** policy type on the **root**
     (**Policies → Service control policies → Enable**).

   If you skip this, the apply **fails** with an Organizations authorization /
   policy-type error (typically `AccessDeniedException` or
   `PolicyTypeNotEnabledException`) on the policy resources. That error *is* the
   missing precondition.

   Docs (rephrased for compliance):
   [Enabling all features](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_org_support-all-features.html)
   and
   [Enabling a policy type](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_enable-disable.html).

> **Existing deployment where `foundation/` already created these?** Do the
> [state migration](#state-migration-existing-deployments-only) **first**, so the
> apply adopts the live resources instead of trying to create duplicates that
> collide on the fixed names.

## How to run

Run from the repo root; mise exports `AWS_PROFILE` / `AWS_REGION` automatically.
You run this stack **once per management account** — there is nothing per
workshop here.

1. **Dry run — see what would be created, change nothing:**

   ```bash
   mise run governance-shared-plan
   ```

   Reports the budgets role + the two SCP policy objects it would add. Creates
   nothing.

2. **Apply — create the three singletons and print the wire-forward:**

   ```bash
   mise run governance-shared-apply
   ```

   Creates the budgets execution role and the two SCP policy objects (the freeze
   SCP unattached; the guardrail not attached here either — `governance/`
   attaches it per workshop). On success it prints the exact `TF_VAR_*` export
   lines you need in the next step.

3. **Wire the three outputs forward into every workshop's `governance/` stack.**
   `governance/` consumes these by id/ARN as **required** variables (no defaults
   — a missing wire-forward fails closed):

   | governance-shared output     | governance input                 | Used for                                     |
   | ---------------------------- | -------------------------------- | -------------------------------------------- |
   | `budgets_execution_role_arn` | `var.budgets_execution_role_arn` | the role each budget's freeze action assumes |
   | `kiro_guardrail_scp_id`      | `var.kiro_guardrail_scp_id`      | the policy id attached to each workshop OU   |
   | `freeze_scp_id`              | `var.freeze_scp_id`              | the policy id Budgets attaches on breach     |

   Export them (the apply prints these exact lines):

   ```bash
   cd governance-shared/terraform
   export TF_VAR_budgets_execution_role_arn="$(tofu output -raw budgets_execution_role_arn)"
   export TF_VAR_kiro_guardrail_scp_id="$(tofu output -raw kiro_guardrail_scp_id)"
   export TF_VAR_freeze_scp_id="$(tofu output -raw freeze_scp_id)"
   ```

   Prefer a file? Put them in each `governance/terraform/terraform.tfvars`
   instead:

   ```hcl
   budgets_execution_role_arn = "arn:aws:iam::<mgmt-account-id>:role/governance-budgets-exec"
   kiro_guardrail_scp_id      = "p-xxxxxxxx"
   freeze_scp_id              = "p-xxxxxxxx"
   ```

   You do this wiring **once per management account** and reuse the same three
   IDs for every workshop. The `governance-*` tasks fail closed if any of the
   three `TF_VAR_*` is unset. From here, follow step 4,
   [`../governance/README.md`](../governance/README.md).

### Idempotency

A re-run after a clean apply converges to **0 to change** unless you edited
`var.kiro_allowed_actions` or a role/policy definition. The three resources are
singletons with fixed names; every workshop reuses the same three outputs.

## State migration (existing deployments only)

> **Run guidance for an EXISTING deployment only — not teardown, and not for a
> fresh install.** On a brand-new deployment there is nothing to migrate; just
> run the apply above. This section applies **only** if you already applied
> `foundation/` before these resources were extracted into this stack.

Moving the HCL from `foundation/` into `governance-shared/` moves the *code*, not
the *state*. The resource instances are **live in `foundation/`'s tfstate**, and
the guardrail SCP is **attached to live workshop OUs**. If you simply apply this
stack, OpenTofu will try to **create** new resources with the fixed names
`kiro-guardrail`, `freeze`, and `governance-budgets-exec`, which **collide** with
the live ones. You must `tofu state mv` the existing instances into this stack's
state first, so this stack **adopts** them rather than recreating them.

### Warnings — read before touching state

- **Do not destroy/recreate.** Destroying the guardrail SCP while it is attached
  to live workshop OUs fails or requires detaching first, and destroying the
  budgets role / freeze SCP breaks live budget-freeze automation. **High blast
  radius.** `tofu state mv` is non-destructive to the live AWS resources — it
  only relocates their tracking between state files; prefer it.
- **Back up both state files first** (`tofu state pull > backup.tfstate` for
  each, or rely on S3 versioning).
- Run against a **quiet** change window; account for the state lock.
- After the move, a `foundation-plan` should show **0 changes** (the HCL was
  removed, and the state is now moved out).

### Addresses to migrate (4 resources + their policy docs)

Move these resource addresses from `foundation/terraform.tfstate` into
`governance-shared/terraform.tfstate`:

```
aws_organizations_policy.kiro_guardrail
aws_organizations_policy.freeze
aws_iam_role.budgets_execution
aws_iam_role_policy.budgets_execution
```

`data.aws_caller_identity.current` and the `data.aws_iam_policy_document.*`
blocks are **data sources**, not managed resources — they are re-read on every
plan and do **not** need migrating. (If your OpenTofu version tracks data sources
in state, moving them is harmless but unnecessary.)

### Procedure (backend-aware; adjust bucket/region to your `backend.hcl`)

Both stacks share one S3 bucket and differ only by state key. Pull each remote
state to a local file, move between the local files, then push the results back.

```bash
# 0. From repo root; make sure backend.hcl exists for BOTH stacks
#    (mise run backend-bootstrap writes them). Back up first.

# 1. Pull both remote states to local working files.
cd foundation/terraform
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=foundation/terraform.tfstate"
tofu state pull > /tmp/foundation.tfstate
cp /tmp/foundation.tfstate /tmp/foundation.backup.tfstate   # backup

cd ../../governance-shared/terraform
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=governance-shared/terraform.tfstate"
tofu state pull > /tmp/governance-shared.tfstate
cp /tmp/governance-shared.tfstate /tmp/governance-shared.backup.tfstate

# 2. Move each address from the foundation state file INTO the
#    governance-shared state file (non-destructive to live AWS).
cd ../../foundation/terraform
for ADDR in \
  aws_organizations_policy.kiro_guardrail \
  aws_organizations_policy.freeze \
  aws_iam_role.budgets_execution \
  aws_iam_role_policy.budgets_execution; do
  tofu state mv \
    -state=/tmp/foundation.tfstate \
    -state-out=/tmp/governance-shared.tfstate \
    "$ADDR" "$ADDR"
done

# 3. Push the updated states back to their respective keys.
#    (Push governance-shared FIRST so the resources are tracked somewhere
#    before you remove them from foundation's remote state.)
cd ../../governance-shared/terraform
tofu state push /tmp/governance-shared.tfstate

cd ../../foundation/terraform
tofu state push /tmp/foundation.tfstate
```

Verify after migration — both plans should show **no changes**:

```bash
cd governance-shared/terraform
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=governance-shared/terraform.tfstate"
tofu plan        # expect: No changes (the live resources are now adopted here)

cd ../../foundation/terraform
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=foundation/terraform.tfstate"
tofu plan        # expect: No changes
```

If `governance-shared` still shows resources **to add**, the move did not land —
restore from the backups (`tofu state push /tmp/<stack>.backup.tfstate`) and
retry. Only after both plans are clean should you run `governance-apply` for any
workshop.

## Reference

### Resources this stack owns

- **Budgets execution role** (`governance-budgets-exec`). Least-privilege IAM
  role AWS Budgets assumes to attach/detach the freeze SCP. Its trust policy
  carries the confused-deputy guard `aws:SourceAccount == <this management
  account>`. Permissions are scoped to the Organizations attach/detach of the
  freeze SCP plus the minimal reads Budgets needs; no org-wide admin.
- **Kiro guardrail SCP** (`kiro-guardrail`). A deny-by-default allowlist: a
  single `Allow` of `var.kiro_allowed_actions` on `*`. Created here, attached by
  `governance/`.
- **Freeze SCP** (`freeze`). A static deny-all policy, created **unattached**.
  AWS Budgets attaches it to a single breaching account on budget breach.

### Shared backend with a singleton key

This stack uses the **same shared S3 backend** as the other stacks: a tracked,
value-free `backend "s3" {}` block (`backend.tf`) plus a git-ignored, keyless
`backend.hcl` supplied at `tofu init` time. The `backend-bootstrap` task writes
that `backend.hcl` for you.

Its state **key** is the bare `governance-shared/terraform.tfstate` — **no
`workshops/<id>/` prefix** — because these are management-account singletons,
mirroring `foundation/terraform.tfstate`:

```
governance-shared/terraform.tfstate                ← this stack (no workshop prefix)
foundation/terraform.tfstate                        ← no workshop prefix
workshops/<id>/governance/terraform.tfstate
workshops/<id>/subscription/terraform.tfstate
workshops/<id>/claim-service/terraform.tfstate
```

### Repo layout

```
governance-shared/
├── README.md                 ← you are here (concept + how to run + state migration)
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

### Inputs

| Variable               | Purpose                                                                     |
| ---------------------- | --------------------------------------------------------------------------- |
| `kiro_allowed_actions` | Allowlist for the shared Kiro guardrail SCP — a **tunable** conservative default (org-wide, not per workshop). |
| `aws_region`           | Provider region; empty falls back to `AWS_REGION`.                          |
| `aws_profile`          | **Management-account / Org-admin** profile; empty falls back to the env.    |
| `default_tags`         | Tags applied to every taggable resource via the provider.                   |

### Outputs

`budgets_execution_role_arn`, `kiro_guardrail_scp_id`, `freeze_scp_id` — the
three the per-workshop `governance/` stack (step 4) consumes.

## Teardown

These are long-lived shared singletons. To remove them, see the root
[`TEARDOWN.md`](../TEARDOWN.md).
