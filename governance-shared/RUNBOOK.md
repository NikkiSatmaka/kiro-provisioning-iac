# Runbook — Create the shared governance singletons and wire them forward

This is the **shared** half of the optional Governance track (root
[`README.md`](../README.md)), run **once per management account**. It is **not**
part of the linear Phase 0→4 flow.

**Prerequisites:** Phase 0 auth (a management-account / Org-admin profile),
Phase 1 backend, and the organization's all-features mode + SCP policy type
enabled (Step 0 below).

End-to-end order of operations for creating the once-per-management-account
singletons (the budgets execution role + the two SCP policy objects) and wiring
them forward into every workshop's `governance/` stack. Steps marked **(IaC)**
are automated here; steps marked **(mgmt account)** or **(console)** are AWS
platform actions you do by hand.

> **Management-account only.** This stack creates AWS Organizations SCPs and the
> Organizations-scoped budgets role; it is **not** dual-mode and must never run
> in a child account. `AWS_PROFILE` must be a management-account (or delegated
> Org-admin) profile.

> Legend: **(mgmt account)** = AWS Organizations management account (or a
> delegated Organizations administrator) · **(IaC)** = `tofu` ·
> **(console)** = AWS web console.

---

## Step 0 — (mgmt account, one-time) Enable all-features + the SCP policy type

Service Control Policies only work when AWS Organizations is in **"all
features"** mode **and** the `SERVICE_CONTROL_POLICY` policy type is **enabled on
the organization root**. This is a **platform precondition this stack cannot
perform**.

1. Sign in to the **management account** (or your delegated Organizations
   administrator account).
2. Open **AWS Organizations** in the console.
3. Confirm the org is in **all features** mode (**Settings** → enable all
   features if it still shows consolidated-billing-only). One-time, irreversible.
4. Enable the **Service control policies** policy type on the **root**
   (**Policies → Service control policies → Enable**).

Verify:
- Organizations reports **all features** enabled.
- The **Service control policies** policy type shows **enabled** on the root.

If you skip this, Step 2's `tofu apply` **fails** with an Organizations
authorization / policy-type error (typically `AccessDeniedException` or
`PolicyTypeNotEnabledException`) on the `aws_organizations_policy` resources.
That error *is* the missing precondition.

> This precondition previously lived in `foundation/RUNBOOK.md` (back when
> foundation created the SCPs). It belongs here now, because this is the stack
> that creates the policy objects. Per-workshop `governance/` only *attaches*
> the guardrail, which needs the same policy type — satisfied once here.

Docs (rephrased for compliance):
[Enabling all features](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_org_support-all-features.html)
and
[Enabling a policy type](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_enable-disable.html).

---

## Step 1 — (mgmt account) Confirm credentials & region

```bash
# From repo root; mise exports AWS_PROFILE / AWS_REGION automatically.
mise run verify          # aws sts get-caller-identity
```

Confirm you are authenticated as the **management-account** (or Org-admin)
principal. `AWS_PROFILE` comes from the git-ignored `.env`; this stack is **not**
dual-mode, so it is always a management-account profile — never a child
account's.

---

## Step 1b — (IaC, one-time) Set up the shared remote S3 state backend (required)

**Mandatory. Do it before Step 2** — the governance-shared tasks fail closed
without it. The `../backend/` stack creates the shared S3 bucket + lock table and
writes `governance-shared/terraform/backend.hcl` for you (the same bootstrap
writes every other stack's `backend.hcl` too, so you run it once).

```bash
mise run backend-bootstrap-plan      # DRY RUN: what the bucket + lock table bootstrap would create
mise run backend-bootstrap           # create them AND write every stack's backend.hcl (prompts)
```

This stack reuses that one shared bucket under its own distinct state key
`governance-shared/terraform.tfstate` (no `workshops/<id>/` prefix — a
management-account singleton, mirroring `foundation/terraform.tfstate`).

---

## Step 2 — (IaC) Create the shared singletons

> **Already running an older deployment where `foundation/` created these?** Do
> the [state migration](#state-migration-from-foundation-non-destructive) FIRST,
> so this apply adopts the existing live resources instead of trying to create
> duplicates (which would collide on the fixed names `kiro-guardrail`, `freeze`,
> `governance-budgets-exec`).

```bash
mise run governance-shared-plan      # DRY RUN: tofu init + plan (shows the role + 2 SCPs to add)
mise run governance-shared-apply     # create them AND print the TF_VAR_* export lines
```

Both tasks run `tofu init -backend-config=backend.hcl` with the singleton key
for you (`-backend-config="key=governance-shared/terraform.tfstate"`) and
**require** it — they fail closed if Step 1b was skipped.

What this does:
- **Creates** the budgets execution role and the two SCP *policy objects* (Kiro
  guardrail + deny-all freeze). The freeze SCP is created **unattached**; the
  guardrail is **not** attached here either (`governance/` attaches it per
  workshop). These are the once-per-management-account singletons every
  workshop's `governance/` stack consumes.

---

## Step 3 — (IaC) Wire the outputs into every workshop's governance stack

After a clean apply, `mise run governance-shared-apply` prints the exact export
lines. Export them so each `governance/` run picks them up through its existing
variables:

```bash
cd governance-shared/terraform
export TF_VAR_budgets_execution_role_arn="$(tofu output -raw budgets_execution_role_arn)"
export TF_VAR_kiro_guardrail_scp_id="$(tofu output -raw kiro_guardrail_scp_id)"
export TF_VAR_freeze_scp_id="$(tofu output -raw freeze_scp_id)"
```

Prefer a file? Put them in each `governance/terraform/terraform.tfvars` instead:

```hcl
budgets_execution_role_arn = "arn:aws:iam::<mgmt-account-id>:role/governance-budgets-exec"
kiro_guardrail_scp_id      = "p-xxxxxxxx"
freeze_scp_id              = "p-xxxxxxxx"
```

The `governance-*` tasks fail closed if any of the three `TF_VAR_*` is unset.
You do this wiring **once per management account** and reuse the same three IDs
for every workshop. From here, follow
[`../governance/RUNBOOK.md`](../governance/RUNBOOK.md).

---

## Idempotency and the one-time nature

Run this stack **once per management account**. The three resources are
singletons with fixed names; a re-run after a clean apply converges to **0 to
change** unless you edited `var.kiro_allowed_actions` or a role/policy
definition. There is nothing per workshop here — every workshop reuses the same
three outputs.

---

## State migration from `foundation/` (non-destructive)

> **DOCS ONLY — do not run blindly.** This is an operator procedure for an
> EXISTING deployment where `foundation/` already created these resources before
> they were extracted into this stack. On a brand-new deployment there is
> nothing to migrate — just run Step 2.

### Why a migration is needed

Moving the HCL from `foundation/` into `governance-shared/` moves the *code*,
not the *state*. The five resource instances below are **live in
`foundation/`'s tfstate** (state key `foundation/terraform.tfstate`). If you
simply `governance-shared-apply`, OpenTofu will try to **create** new resources
with the fixed names `kiro-guardrail`, `freeze`, and `governance-budgets-exec`,
which **collide** with the live ones (and the guardrail SCP is **attached to
live workshop OUs**). You must `tofu state mv` the existing instances into this
stack's state first, so this stack **adopts** them rather than recreating them.

### ⚠️ Warnings — read before touching state

- **Do NOT destroy/recreate.** Destroying the Kiro guardrail SCP while it is
  **attached to live workshop OUs** (via `governance/`'s
  `aws_organizations_policy_attachment`) fails or requires detaching first, and
  destroying the budgets role / freeze SCP breaks live budget freeze automation.
  **High blast radius.** `tofu state mv` is non-destructive to the live AWS
  resources — it only relocates their tracking between state files; prefer it.
- **Back up both state files first** (`tofu state pull > backup.tfstate` for
  each, or rely on S3 versioning).
- Run against a **quiet** change window; take the state lock into account.
- After the move, `foundation/` must no longer reference these resources (it
  does not — the HCL was removed), so a `foundation-plan` should show **0
  changes** (the resources are simply gone from its config AND its state).

### Addresses to migrate (4 resources + their policy docs)

Move these resource addresses from `foundation/terraform.tfstate` into
`governance-shared/terraform.tfstate`:

```
aws_organizations_policy.kiro_guardrail
aws_organizations_policy.freeze
aws_iam_role.budgets_execution
aws_iam_role_policy.budgets_execution
```

`data.aws_caller_identity.current` is a **data source**, not a managed resource —
it is re-read on every plan and does **not** need migrating. The
`data.aws_iam_policy_document.*` blocks are likewise data sources and are not
migrated. (If your OpenTofu version tracks data sources in state, moving them is
harmless but unnecessary.)

### Procedure (backend-aware; adjust bucket/region to your `backend.hcl`)

Both stacks share one S3 bucket and differ only by state key. The cleanest
backend-aware approach is to pull each remote state to a local file, move
between the local files, then push the results back — or use `tofu state mv`
with `-state`/`-state-out` against the pulled files.

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

### Verify after migration

```bash
# governance-shared now OWNS the three resources: plan should show 0 to add/change.
cd governance-shared/terraform
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=governance-shared/terraform.tfstate"
tofu plan        # expect: No changes (the live resources are now adopted here)

# foundation no longer references OR tracks them: plan should also show 0 changes.
cd ../../foundation/terraform
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=foundation/terraform.tfstate"
tofu plan        # expect: No changes
```

If `governance-shared` still shows resources **to add**, the move did not land —
restore from the backups (`tofu state push /tmp/<stack>.backup.tfstate`) and
retry. Only after both plans are clean should you run `governance-apply` for any
workshop.

---

## Teardown — long-lived; destroy only at decommission

These three are **long-lived shared singletons**. A per-workshop
`governance-destroy` **never** touches them (it removes only that workshop's OU,
guardrail attachment, and budgets). Destroy them **only when the whole
management account is being decommissioned and no workshop remains**:

```bash
cd governance-shared/terraform
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=governance-shared/terraform.tfstate"
tofu destroy
```

⚠️ Destroying the guardrail or freeze SCP while **any** workshop's `governance/`
stack still references them breaks that workshop's attachment and freeze
automation. Tear down every workshop's `governance/` first. There is
intentionally no `governance-shared-destroy` mise task — this is a deliberate,
rare, manual action.
