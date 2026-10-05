# Runbook — Create the Foundation IdC instance and wire it forward

End-to-end order of operations for the shared, account-level IAM Identity Center
(IdC) instance. Steps marked **(IaC)** are automated here; steps marked
**(mgmt account)** or **(console)** are AWS platform limits you must do by hand.
Nothing in this repo runs on its own — you invoke each step.

> Legend: **(mgmt account)** = AWS Organizations management account ·
> **(this account)** = the child/member account where Kiro lives ·
> **(IaC)** = `tofu` · **(console)** = AWS web console.

This stack is applied **once and reused across every workshop** — not per
workshop. It sits between Phase 1 (the `backend/` bootstrap) and Phase 2 (the
per-workshop `subscription/` stack). Run it a single time, up front; every
workshop then consumes its outputs.

---

## Step 0 — (mgmt account, one-time) Permit member-account IdC instances

An account instance can only be created in a member account if the AWS
Organizations **management account** has enabled member-account IdC instances.
This is a **one-time, irreversible** toggle.

1. Sign in to the **management account** (your AWS Organizations management
   account).
2. Open **IAM Identity Center** in the console.
3. **Settings → Management → Account instances of IAM Identity Center → Enable.**
   Confirm. (You can later constrain this with an SCP; see the AWS docs.)

Verify (from the management account):
- The setting shows account instances are allowed.

If you skip this, Step 2's `tofu apply` **fails with an authorization error on
the `awscc_sso_instance` resource**. That authorization error *is* the missing
management-account enablement — nothing in this repo can flip the toggle for
you, because it lives in the management account.

Docs (rephrased for compliance):
[Permit account instance creation](https://docs.aws.amazon.com/singlesignon/latest/userguide/enable-account-instance-console.html).

> ℹ️ One account instance per account, across **all** regions. If this account
> already has an account instance, import it instead of creating a new one (see
> Step 3).

---

## Step 1 — (this account) Confirm credentials & region

Assumes the toolchain + AWS auth are already set up (root README, Phase 0).

```bash
# From repo root; mise exports AWS_PROFILE / AWS_REGION automatically.
mise run verify          # aws sts get-caller-identity
```

Confirm the account is the intended **child** account and the region is one
Kiro supports for IdC. Profile and region come from the git-ignored `.env`
(default region `us-east-1`); change the region there (`cp .env.example .env`)
rather than editing committed files.

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

## Step 2 — (IaC) Create the Foundation IdC instance

The create-then-wire order is: **backend-bootstrap → foundation-apply → capture
the two IDs → export them for the subscription stack.** You did the bootstrap in
Step 1b; this step is the apply.

```bash
# Optional: pin a name via tfvars or env (defaults to "kiro-login").
# export TF_VAR_instance_name="kiro-login"

mise run foundation-plan      # DRY RUN: tofu init + plan (1 instance), creates nothing
mise run foundation-apply     # apply — creates the instance (prompts to approve)
```

Both tasks run `tofu init -backend-config=backend.hcl` with the foundation key
for you (`-backend-config="key=foundation/terraform.tfstate"`) and **require**
it — they fail closed if Step 1b was skipped.

Prefer raw tofu? The equivalent by hand:

```bash
cd foundation/terraform
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=foundation/terraform.tfstate"
tofu plan       # review: 1 awscc_sso_instance "this"
tofu apply      # creates it
```

What this creates:
- **One** IAM Identity Center **account instance** in this account.
- **No** users, groups, memberships, permission sets, or account assignments —
  those are the `subscription/` stack's job.

> If `tofu apply` fails with an **authorization error on `awscc_sso_instance`**,
> the management-account enablement from Step 0 is missing. Fix Step 0, then
> re-apply.

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
for the per-workshop steps. Because the foundation instance is applied once and
reused across every workshop, you do this wiring once per account and reuse the
same two IDs for every subsequent workshop.

---

## Idempotency and importing an existing instance

Re-applying this stack after a successful apply makes **no changes** to the
existing IdC instance absent a configuration change — a re-apply is safe.

AWS permits **one IdC account instance per account across all regions**. If an
account instance already exists (for example, created before this stack owned
it) and is not yet in this stack's state, do **not** apply a second one — import
the existing one into state first:

```bash
cd foundation/terraform
tofu import awscc_sso_instance.this <instance_arn>
```

Then `mise run foundation-plan` should report no changes, confirming the stack
now owns the existing instance.

---

## Teardown

Destroying the foundation instance is a **deliberate, guarded** action — it is
the shared resource every workshop depends on, so a routine per-workshop
teardown must never remove it by accident. The foundation stack is excluded from
every `provision*`, `teardown*`, and `claim-*` task; **the subscription teardown
tasks never delete the Foundation IdC instance.** Only the dedicated task below
can reach it.

```bash
mise run foundation-destroy
```

That task puts two gates in front of the delete:

1. It prompts you to type exactly `destroy-foundation`. Any other string
   (including empty or whitespace) exits non-zero and **deletes nothing**.
2. On a match, it still requires `tofu`'s **own** apply/destroy approval prompt
   before anything is deleted.

Caveats:
- **Deleting the IdC account instance is destructive and irreversible.** Every
  workshop consuming it loses its identity source.
- The management-account enablement of account instances (Step 0) is a
  **one-time, irreversible toggle** and **cannot be reversed** — destroying the
  instance does not undo it.
- Tear down the per-workshop `subscription/` (and `claim-service/`) stacks
  first; destroy this shared foundation last, and only when no workshop needs
  it.

---

## Quick reference — what is / isn't automated

| Step | Automated here? | Why |
| ---- | --------------- | --- |
| Permit member-account instances (Step 0) | ❌ (mgmt account console) | Org-level, one-time, irreversible toggle |
| Shared backend bucket + `backend.hcl` (Step 1b) | ✅ (IaC, `backend-bootstrap`) | — |
| Create the IdC account instance (Step 2) | ✅ (IaC, `awscc_sso_instance`) | — |
| Wire outputs into the subscription stack (Step 3) | ⚠️ operator exports `TF_VAR_*` | Explicit variables, not remote state |
| Import a pre-existing instance | ✅ (`tofu import awscc_sso_instance.this`) | One account instance per account, all regions |
| Destroy the foundation instance | ✅ (`foundation-destroy`, typed-phrase guarded) | Destructive; excluded from per-workshop teardown |
