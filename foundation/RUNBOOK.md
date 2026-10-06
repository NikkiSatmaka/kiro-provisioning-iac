# Runbook — Adopt the organization IdC instance and wire it forward

This is **Phase 2** of the journey (root [`README.md`](../README.md)).
**Prerequisites:** Phase 1 (the `../backend/` bootstrap) complete and IAM
Identity Center enabled in the management account (Step 0 below).

End-to-end order of operations for reading the shared, organization-level IAM
Identity Center (IdC) instance and wiring its IDs forward. Steps marked **(IaC)**
are automated here; steps marked **(mgmt account)** or **(console)** are AWS
platform actions you must do by hand. Nothing in this repo runs on its own — you
invoke each step.

> Legend: **(mgmt account)** = the AWS Organizations management account, which is
> where every stack in this repo now provisions · **(this account)** = the same
> management account · **(IaC)** = `tofu` · **(console)** = AWS web console.

This stack reads the org instance **once and reuses the result across every
workshop** — not per workshop. It sits between Phase 1 (the `backend/` bootstrap)
and Phase 2 (the per-workshop `subscription/` stack). Run it a single time, up
front; every workshop then consumes its outputs.

---

## Step 0 — (mgmt account, one-time) Enable IAM Identity Center

This repo adopts the management account's existing **organization** IdC
instance; it does not create one. If IdC has never been enabled in the
management account, there is no instance to read and plan fails.

1. Sign in to the **management account** (your AWS Organizations management
   account).
2. Open **IAM Identity Center** in the console.
3. **Enable** IAM Identity Center. This creates the single organization
   instance for the account.

Verify (from the management account):
- IAM Identity Center is enabled and shows an organization instance.

If you skip this, Step 2's `tofu plan`/`apply` **finds no instance** and the
`data "aws_ssoadmin_instances"` lookup returns an empty list. That empty result
*is* the missing enablement — enable IdC in the management account, then re-run.

Docs (rephrased for compliance):
[Enable IAM Identity Center](https://docs.aws.amazon.com/singlesignon/latest/userguide/get-set-up-for-idc.html).

> ℹ️ Exactly one organization instance exists per management account.

---

## Step 1 — (this account) Confirm credentials & region

Assumes the toolchain + AWS auth are already set up (root README, Phase 0).

```bash
# From repo root; mise exports AWS_PROFILE / AWS_REGION automatically.
mise run verify          # aws sts get-caller-identity
```

Confirm the account is the intended **management** account and the region is one
Kiro supports for IdC. Profile and region come from the git-ignored `.env`
(default region `us-east-1`); change the region there (`cp .env.example .env`)
rather than editing committed files. `AWS_PROFILE` must be a management-account
profile.

---

## Step 1b — (IaC, one-time) Set up the shared remote S3 state backend (required)

**This step is mandatory. Do it before Step 2** — the foundation tasks fail
closed without it. The `../backend/` stack creates the shared S3 bucket + lock
table and writes `foundation/terraform/backend.hcl` for you. The **same**
bootstrap also writes the subscription and claim-service `backend.hcl` files, so
you run it once for every stack.

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
  missing, and also if `backend.hcl` carries a residual `key` line, since the
  key is supplied at init time).

---

## Step 2 — (IaC) Read the organization IdC instance

The read-then-wire order is: **backend-bootstrap → foundation-apply → capture
the two IDs → export them for the subscription stack.** You did the bootstrap in
Step 1b; this step resolves the IDs.

```bash
mise run foundation-plan      # DRY RUN: tofu init + plan, a pure read (0 to add)
mise run foundation-apply     # resolve the IDs (creates nothing)
```

Both tasks run `tofu init -backend-config=backend.hcl` with the foundation key
for you (`-backend-config="key=foundation/terraform.tfstate"`) and **require**
it — they fail closed if Step 1b was skipped.

Prefer raw tofu? The equivalent by hand:

```bash
cd foundation/terraform
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=foundation/terraform.tfstate"
tofu plan       # review: a pure read, 0 to add
tofu apply      # resolves the data source; creates nothing
```

What this reads:
- The **one** IAM Identity Center **organization instance** in the management
  account.
- **No** users, groups, memberships, permission sets, or account assignments —
  those are the `subscription/` stack's job. This stack creates nothing.

> If `tofu plan` reports no instance (the `data "aws_ssoadmin_instances"` lookup
> is empty), the IdC enablement from Step 0 is missing. Enable IdC in the
> management account, then re-run.

---

## Step 3 — (IaC) Wire the outputs into the subscription stack

After a clean apply, `mise run foundation-apply` prints the exact export lines.
Capture the `instance_arn` and `identity_store_id` outputs and export them so
the subscription stack consumes them through its existing variables:

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

The two stacks are wired **by you, through variables** — never a remote-state
reference. From here, follow [`../subscription/RUNBOOK.md`](../subscription/RUNBOOK.md)
for the per-workshop steps. Because the foundation instance is read once and
reused across every workshop, you do this wiring once per management account and
reuse the same two IDs for every subsequent workshop.

> **Next:** Phase 3 — Provision ([`../subscription/RUNBOOK.md`](../subscription/RUNBOOK.md)).

---

## Idempotency — re-running is a safe no-op read

This stack only **reads** the org instance, so re-running it never changes
anything in AWS. There is nothing to import: the data source resolves the single
organization instance on every run. `mise run foundation-plan` reports **0 to
add, 0 to change, 0 to destroy**.

---

## Teardown — nothing to destroy here

Foundation **does not own a destroyable resource** and **never deletes** the
organization IdC instance. That instance belongs to the management account, not
to this stack's state, so there is nothing for a `destroy` to remove. **Disabling IAM Identity Center is a
console action in the management account**, never a per-workshop task, and must
only be done deliberately when no workshop depends on the directory.

Because this stack owns nothing:

- `foundation-destroy` is a documented no-op (see `mise.toml`). It deletes
  nothing and exists only to make that explicit.
- The subscription teardown tasks never touch the shared org instance — they
  remove only users / groups / memberships (and, when enabled, the flag-gated
  permission set / assignments).
- Tear down the per-workshop `subscription/` (and `claim-service/`) stacks when
  a workshop is done; the shared org instance stays put for the next workshop.

---

## Quick reference — what is / isn't automated

| Step | Automated here? | Why |
| ---- | --------------- | --- |
| Enable IAM Identity Center (Step 0) | ❌ (mgmt account console) | Org-level, one-time console action |
| Shared backend bucket + `backend.hcl` (Step 1b) | ✅ (IaC, `backend-bootstrap`) | — |
| Read the org IdC instance (Step 2) | ✅ (IaC, `data "aws_ssoadmin_instances"`) | Pure read; creates nothing |
| Wire outputs into the subscription stack (Step 3) | ⚠️ operator exports `TF_VAR_*` | Explicit variables, not remote state |
| Destroy the foundation instance | ❌ (nothing owned) | Org instance is not managed here; `foundation-destroy` is a no-op |
