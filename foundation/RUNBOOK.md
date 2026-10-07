# Runbook — Adopt the IdC instance (dual-mode) and wire it forward

This is **Phase 2** of the journey (root [`README.md`](../README.md)).
**Prerequisites:** Phase 1 (the `../backend/` bootstrap) complete and IAM
Identity Center enabled in the credentialed account (Step 0 below).

End-to-end order of operations for **reading** whichever IAM Identity Center
(IdC) instance the credentialed account exposes and wiring its IDs forward.
Steps marked **(IaC)** are automated here; steps marked **(target account)** or
**(console)** are AWS platform actions you must do by hand. Nothing in this repo
runs on its own — you invoke each step.

> **Dual-mode.** Foundation is account-safe: run it under a **management-account**
> profile to adopt the **organization** instance (default), or under a
> **child/member account**'s profile to adopt that account's **own account
> instance**. The same data source resolves per-account; no input selects the
> mode. Below, "the target account" means the management account in organization
> mode, or the child account in account mode.

> Legend: **(target account)** = the account whose IdC instance you are adopting
> (management in org mode, child in account mode) · **(IaC)** = `tofu` ·
> **(console)** = AWS web console.

This stack reads the instance **once and reuses the result across every
workshop** — not per workshop. It sits between Phase 1 (the `backend/`
bootstrap) and the per-workshop `subscription/` stack. Run it a single time per
account, up front; every workshop then consumes its outputs.

> **What moved out.** Foundation used to also create the shared budgets
> execution role and the two SCP policy objects. Those are AWS Organizations /
> management-account resources and now live in the management-only
> [`../governance-shared/`](../governance-shared/RUNBOOK.md) stack, so foundation
> is pure read-only IdC adoption and runs in a child account too.

---

## Step 0 — (target account, one-time) Enable IAM Identity Center

This repo **adopts** the credentialed account's existing IdC instance; it does
not create one. If IdC has never been enabled in that account, there is no
instance to read and plan fails.

1. Sign in to the **target account** — your AWS Organizations management account
   (organization mode) or the child/member account (account mode).
2. Open **IAM Identity Center** in the console.
3. **Enable** IAM Identity Center. This creates the account's instance (an
   organization instance in the management account, an account instance in a
   child account).

Verify (from the target account):
- IAM Identity Center is enabled and shows an instance.

If you skip this, Step 2's `tofu plan`/`apply` **finds no instance** and the
`data "aws_ssoadmin_instances"` lookup returns an empty list. That empty result
*is* the missing enablement — enable IdC in the target account, then re-run.

Docs (rephrased for compliance):
[Enable IAM Identity Center](https://docs.aws.amazon.com/singlesignon/latest/userguide/get-set-up-for-idc.html).

> ℹ️ Exactly one instance is exposed per account (one organization instance in
> the management account, one account instance in a child account).

> **Note (SCP policy type).** The all-features-mode + `SERVICE_CONTROL_POLICY`
> policy-type enablement is **not** a foundation prerequisite anymore — the SCPs
> moved to `governance-shared/`. See
> [`../governance-shared/RUNBOOK.md`](../governance-shared/RUNBOOK.md) if you use
> the optional governance track.

---

## Step 1 — (target account) Confirm credentials & region

Assumes the toolchain + AWS auth are already set up (root README, Phase 0).

```bash
# From repo root; mise exports AWS_PROFILE / AWS_REGION automatically.
mise run verify          # aws sts get-caller-identity
```

Confirm the account is the intended one — the **management** account in
organization mode, or the **child/member** account in account mode — and the
region is one Kiro supports for IdC. Profile and region come from the
git-ignored `.env` (default region `us-east-1`); change the region there
(`cp .env.example .env`) rather than editing committed files. `AWS_PROFILE` must
match the chosen mode's account.

> ⚠️ **R-2:** in account mode a management-account profile silently adopts the
> **organization** instance. Verify `mise run verify` shows the **child**
> account before applying, or you will wire the wrong IDs forward.

---

## Step 1b — (IaC, one-time) Set up the shared remote S3 state backend (required)

**This step is mandatory. Do it before Step 2** — the foundation tasks fail
closed without it. The `../backend/` stack creates the shared S3 bucket + lock
table and writes `foundation/terraform/backend.hcl` for you. The **same**
bootstrap also writes every other stack's `backend.hcl`, so you run it once.

```bash
mise run backend-bootstrap-plan      # DRY RUN: what the bucket + lock table bootstrap would create
mise run backend-bootstrap           # create them AND write every stack's backend.hcl (prompts)
```

The foundation stack reuses that one shared bucket under its own distinct state
key `foundation/terraform.tfstate` (no `workshops/<id>/` prefix), so its state
stays isolated from every workshop. The mechanics — why the backend keeps its
own local state and the derived bucket name — are in
[`../backend/README.md`](../backend/README.md).

Verify:
- `foundation/terraform/backend.hcl` exists (git-ignored; `backend.tf` is
  tracked and already present).
- `mise run foundation-plan` runs `tofu init -backend-config=backend.hcl` and
  reports the S3 backend is initialized (it fails closed if `backend.hcl` is
  missing, and also if `backend.hcl` carries a residual `key` line).

---

## Step 2 — (IaC) Adopt (read) the IdC instance

The order is: **backend-bootstrap → foundation-apply → capture the IDs → export
them for the subscription stack.** You did the bootstrap in Step 1b; this step
resolves the IdC IDs. It is a **pure read** — it creates nothing.

```bash
mise run foundation-plan      # DRY RUN: tofu init + plan, a pure read (0 to add)
mise run foundation-apply     # adopt the IdC instance (resolve the IDs)
```

Both tasks run `tofu init -backend-config=backend.hcl` with the foundation key
for you (`-backend-config="key=foundation/terraform.tfstate"`) and **require**
it — they fail closed if Step 1b was skipped.

Prefer raw tofu? The equivalent by hand:

```bash
cd foundation/terraform
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=foundation/terraform.tfstate"
tofu plan       # review: a pure read of the IdC instance (0 to add)
tofu apply      # resolves the data source; creates nothing
```

What this does:
- **Reads** the **one** IAM Identity Center instance the credentialed account
  exposes (organization instance in management, account instance in a child).
  **No** users, groups, memberships, permission sets, or account assignments —
  those are the `subscription/` stack's job. **No** SCPs or budgets role — those
  are the `governance-shared/` stack's job.

> If `tofu plan` reports no instance (the `data "aws_ssoadmin_instances"` lookup
> is empty), the IdC enablement from Step 0 is missing. Enable IdC in the target
> account, then re-run.

---

## Step 3 — (IaC) Wire the outputs into the subscription stack

After a clean apply, `mise run foundation-apply` prints the exact export lines.
Capture the outputs and export them so the subscription stack picks them up
through its existing variables.

Into the **subscription** stack (the IdC handoff):

```bash
cd foundation/terraform
export TF_VAR_idc_instance_arn="$(tofu output -raw instance_arn)"
export TF_VAR_identity_store_id="$(tofu output -raw identity_store_id)"

# Informational:
tofu output -raw sign_in_url     # https://<identity-store-id>.awsapps.com/start
tofu output -raw region
```

The outputs are plain strings, so `tofu output -raw` emits a bare value with no
surrounding quotes — assignable straight to a `TF_VAR_*` variable. Prefer a
file? Write them into the subscription stack's `terraform.tfvars` instead:

```hcl
# subscription/terraform/terraform.tfvars
idc_instance_arn  = "arn:aws:sso:::instance/ssoins-xxxxxxxxxxxx"
identity_store_id = "d-xxxxxxxxxx"
```

The three shared-primitive IDs the `governance/` stack needs
(`budgets_execution_role_arn`, `kiro_guardrail_scp_id`, `freeze_scp_id`) are
**not** emitted here anymore — get them from
[`../governance-shared/RUNBOOK.md`](../governance-shared/RUNBOOK.md).

The stacks are wired **by you, through variables** — never a remote-state
reference. From here, follow
[`../subscription/RUNBOOK.md`](../subscription/RUNBOOK.md) for the per-workshop
steps. Because foundation runs once and is reused across every workshop, you do
this wiring once per account and reuse the same IDs for every subsequent
workshop.

> **Next:** Phase 3 — Provision ([`../subscription/RUNBOOK.md`](../subscription/RUNBOOK.md)).

---

## Idempotency — re-running is safe

The IdC read never changes anything in AWS: the data source resolves the single
instance on every run. Foundation owns no managed resources, so a re-run is
always a no-op (the plan converges to **0 to change**).

---

## Teardown — nothing to destroy

Foundation **owns nothing to destroy**: it adopts the IdC instance read-only, so
that instance is **never in this stack's state** and no foundation task deletes
it. `foundation-destroy` is a documented **no-op**. **Disabling IAM Identity
Center is a console action in the target account**, never a repo task, and must
only be done deliberately when no workshop depends on the directory.

The shared budgets role and the two SCP policies that used to live here are now
owned by [`../governance-shared/`](../governance-shared/RUNBOOK.md) — see that
stack's RUNBOOK for their lifecycle, the one-time `tofu state mv` migration out
of foundation's state, and when (if ever) they are destroyed.

---

## Quick reference — what is / isn't automated

| Step | Automated here? | Why |
| ---- | --------------- | --- |
| Enable IAM Identity Center (Step 0) | ❌ (target-account console) | Per-account, one-time console action |
| Shared backend bucket + `backend.hcl` (Step 1b) | ✅ (IaC, `backend-bootstrap`) | — |
| Adopt (read) the IdC instance (Step 2) | ✅ (IaC, `data "aws_ssoadmin_instances"`) | Pure read |
| Wire outputs into subscription (Step 3) | ⚠️ operator exports `TF_VAR_*` | Explicit variables, not remote state |
| Destroy the IdC instance | ❌ (nothing owned) | Instance is not managed here; disabling IdC is a console action |
