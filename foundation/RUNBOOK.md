# Runbook — Read the org IdC instance, create the shared primitives, and wire them forward

This is **Phase 2** of the journey (root [`README.md`](../README.md)).
**Prerequisites:** Phase 1 (the `../backend/` bootstrap) complete and IAM
Identity Center enabled in the management account (Step 0 below).

End-to-end order of operations for reading the shared, organization-level IAM
Identity Center (IdC) instance, creating the shared budgets role + two SCP
policies, and wiring all of these forward. Steps marked **(IaC)** are automated
here; steps marked **(mgmt account)** or **(console)** are AWS platform actions
you must do by hand. Nothing in this repo runs on its own — you invoke each step.

> Legend: **(mgmt account)** = the AWS Organizations management account, which is
> where every stack in this repo now provisions · **(this account)** = the same
> management account · **(IaC)** = `tofu` · **(console)** = AWS web console.

This stack reads the org instance and creates the shared primitives **once and
reuses the result across every workshop** — not per workshop. It sits between
Phase 1 (the `backend/` bootstrap) and the per-workshop `subscription/` and
`governance/` stacks. Run it a single time, up front; every workshop then
consumes its outputs.

---

## Step 0 — (mgmt account, one-time) Enable IAM Identity Center AND the SCP policy type

Two one-time, console-only, management-account enablements this stack cannot
perform. Both must be done before Step 2's apply.

### 0a — Enable IAM Identity Center

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

### 0b — Enable all-features mode + the SCP policy type on the org root

Because foundation now **creates the shared Kiro guardrail and freeze SCP
policies** (previously created per workshop in `governance/`), the organization
must have:

1. **All-features mode** enabled on the organization, and
2. The **`SERVICE_CONTROL_POLICY` policy type** enabled on the root.

Both are **management-account, one-time, console-only** actions — OpenTofu
cannot flip all-features mode or enable a policy type on the root. If either is
missing, `foundation-apply` fails with an Organizations authorization /
policy-type error when it tries to create the SCP policies.

> This precondition moved here from `governance/RUNBOOK.md`: the SCP *policies*
> are created by foundation now, so the policy type must be live before
> foundation applies. `governance/` only *attaches* the shared guardrail to each
> workshop OU, which also requires the policy type — satisfied once here.

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

## Step 2 — (IaC) Read the IdC instance and create the shared primitives

The order is: **backend-bootstrap → foundation-apply → capture the IDs → export
them for the subscription and governance stacks.** You did the bootstrap in
Step 1b; this step resolves the IdC IDs and creates the shared budgets role +
two SCP policies.

```bash
mise run foundation-plan      # DRY RUN: tofu init + plan (reads IdC; shows the role + 2 SCPs to add)
mise run foundation-apply     # read IdC AND create the shared role + SCP policies
```

Both tasks run `tofu init -backend-config=backend.hcl` with the foundation key
for you (`-backend-config="key=foundation/terraform.tfstate"`) and **require**
it — they fail closed if Step 1b was skipped.

Prefer raw tofu? The equivalent by hand:

```bash
cd foundation/terraform
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=foundation/terraform.tfstate"
tofu plan       # review: reads IdC; adds the shared budgets role + 2 SCP policies
tofu apply      # resolves the data source AND creates the shared primitives
```

What this does:
- **Reads** the **one** IAM Identity Center **organization instance** in the
  management account. **No** users, groups, memberships, permission sets, or
  account assignments — those are the `subscription/` stack's job.
- **Creates** the shared budgets execution role and the two SCP *policy objects*
  (Kiro guardrail + deny-all freeze). The freeze SCP is created **unattached**;
  the guardrail is **not** attached here either — `governance/` attaches it to
  each workshop OU. These are the once-per-management-account primitives every
  workshop's `governance/` stack consumes.

> If `tofu plan` reports no instance (the `data "aws_ssoadmin_instances"` lookup
> is empty), the IdC enablement from Step 0 is missing. Enable IdC in the
> management account, then re-run.

---

## Step 3 — (IaC) Wire the outputs into the subscription and governance stacks

After a clean apply, `mise run foundation-apply` prints the exact export lines.
Capture the outputs and export them so the consuming stacks pick them up through
their existing variables.

Into the **subscription** stack (the IdC handoff):

```bash
cd foundation/terraform
export TF_VAR_idc_instance_arn="$(tofu output -raw instance_arn)"
export TF_VAR_identity_store_id="$(tofu output -raw identity_store_id)"

# Informational:
tofu output -raw sign_in_url     # https://<identity-store-id>.awsapps.com/start
tofu output -raw region
```

Into the **governance** stack (the shared-primitives handoff):

```bash
cd foundation/terraform
export TF_VAR_budgets_execution_role_arn="$(tofu output -raw budgets_execution_role_arn)"
export TF_VAR_kiro_guardrail_scp_id="$(tofu output -raw kiro_guardrail_scp_id)"
export TF_VAR_freeze_scp_id="$(tofu output -raw freeze_scp_id)"
```

The outputs are plain strings, so `tofu output -raw` emits a bare value with no
surrounding quotes — assignable straight to a `TF_VAR_*` variable. Prefer a
file? Write them into each stack's `terraform.tfvars` instead:

```hcl
# subscription/terraform/terraform.tfvars
idc_instance_arn  = "arn:aws:sso:::instance/ssoins-xxxxxxxxxxxx"
identity_store_id = "d-xxxxxxxxxx"

# governance/terraform/terraform.tfvars
budgets_execution_role_arn = "arn:aws:iam::<mgmt-account-id>:role/governance-budgets-exec"
kiro_guardrail_scp_id      = "p-xxxxxxxx"
freeze_scp_id              = "p-xxxxxxxx"
```

The stacks are wired **by you, through variables** — never a remote-state
reference. From here, follow [`../subscription/RUNBOOK.md`](../subscription/RUNBOOK.md)
and [`../governance/RUNBOOK.md`](../governance/RUNBOOK.md) for the per-workshop
steps. Because foundation runs once and is reused across every workshop, you do
this wiring once per management account and reuse the same IDs for every
subsequent workshop.

> **Next:** Phase 3 — Provision ([`../subscription/RUNBOOK.md`](../subscription/RUNBOOK.md)).

---

## Idempotency — re-running is safe

The IdC read never changes anything in AWS: the data source resolves the single
organization instance on every run. The shared budgets role and the two SCP
policies are ordinary managed resources, so once applied a re-run is a no-op for
them too (the plan converges to **0 to change** unless you edited
`var.kiro_allowed_actions` or a role/policy definition). There is nothing to
import for the created resources — a first apply creates them; subsequent runs
reconcile.

---

## Teardown — the shared primitives are long-lived; destroy only at decommission

Foundation **never deletes** the organization IdC instance — that instance
belongs to the management account, not to this stack's state. **Disabling IAM
Identity Center is a console action in the management account**, never a repo
task, and must only be done deliberately when no workshop depends on the
directory.

The shared budgets role and the two SCP policies this stack now owns are
**long-lived, shared primitives**. A per-workshop `governance-destroy` **never**
touches them — it removes only that workshop's OU, guardrail attachment, account
placement, and budgets. The shared role and policies are torn down only when the
**whole management account is being decommissioned** and no workshop remains:

- `foundation-destroy` is a **guarded** destroy of the shared budgets role + the
  two SCP policies (it does **not**, and cannot, remove the org IdC instance).
  Run it only after every workshop's `governance/` and `subscription/` state has
  been torn down — destroying the shared freeze/guardrail policies while a live
  workshop's governance stack still references them will break that workshop's
  attachment and freeze automation.
- The subscription teardown tasks never touch the shared org instance — they
  remove only users / groups / memberships (and, when enabled, the flag-gated
  permission set / assignments).
- Tear down the per-workshop `subscription/`, `governance/`, and
  `claim-service/` stacks when a workshop is done; the shared foundation
  resources stay put for the next workshop.

---

## Quick reference — what is / isn't automated

| Step | Automated here? | Why |
| ---- | --------------- | --- |
| Enable IAM Identity Center (Step 0a) | ❌ (mgmt account console) | Org-level, one-time console action |
| Enable all-features + SCP policy type (Step 0b) | ❌ (mgmt account console) | Org-root, one-time; required before SCP policies can be created |
| Shared backend bucket + `backend.hcl` (Step 1b) | ✅ (IaC, `backend-bootstrap`) | — |
| Read the org IdC instance (Step 2) | ✅ (IaC, `data "aws_ssoadmin_instances"`) | Pure read |
| Create the shared budgets role + 2 SCP policies (Step 2) | ✅ (IaC, `foundation-apply`) | Once-per-mgmt-account singletons every workshop consumes |
| Wire outputs into subscription + governance (Step 3) | ⚠️ operator exports `TF_VAR_*` | Explicit variables, not remote state |
| Destroy the org IdC instance | ❌ (nothing owned) | Org instance is not managed here; disabling IdC is a console action |
| Destroy the shared budgets role + SCP policies | ✅ (IaC, guarded `foundation-destroy`) | Only at mgmt-account decommission, after every workshop is torn down |
