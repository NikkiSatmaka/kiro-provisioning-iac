# Foundation (step 2 of the flow) — adopt the IAM Identity Center instance, read-only

> Phase link: this is **Step 2** of the [root README](../README.md) flow.
> Prerequisites: Step 1 — Backend ([`../backend/README.md`](../backend/README.md)) · Next: Step 5 — Subscription ([`../subscription/README.md`](../subscription/README.md))

> ⚠️ **Nothing here runs automatically.** Every step is a command you invoke
> yourself with `mise run`. `foundation-apply` is a **pure read**: it adopts the
> Identity Center instance, prints the two IDs to carry forward, and changes
> nothing in AWS.

## What it is

**IAM Identity Center (IdC)** is the AWS service that holds the users, groups,
and sign-in portal a workshop's people log in through. This stack has one job:
**adopt (read) the IdC instance once per account and hand its two IDs forward**
so every workshop's `subscription/` stack can consume them without hunting them
down.

It is **read-only and account-safe**: it creates nothing, so it runs the same
way whether you point it at an organization's management account or at a single
child account.

- **Organization mode** (default) — run under a management-account profile; it
  adopts the one shared **organization** instance.
- **Account mode** — run under a **child/member account**'s profile; it adopts
  that account's **own account instance**.

The same `data "aws_ssoadmin_instances"` lookup resolves per account, so there
is no `instance_mode` input here — the credentialed account decides which
instance is adopted. The adopted instance is read and **reused across every
workshop**, never created per workshop, so this stack sits outside the
per-workshop provision/teardown loop:

```
backend/        (step 1; shared S3 bucket + lock table)
    │
    ▼
foundation/     (step 2; run once per account; state key foundation/terraform.tfstate)
    reads  ONE IdC instance (data "aws_ssoadmin_instances")
           - organization instance   (management account), or
           - account instance         (child/member account)
    emits   instance_arn / identity_store_id / region / sign_in_url
    │  you export the IDs forward (NOT remote state)
    └──────────────▶ subscription/ (step 5; per workshop; consumes the two IdC IDs)
```

The stack reads **exactly one** IdC instance and touches **nothing else** on the
Identity Center surface — no users, groups, memberships, permission sets, or
account assignments. Those all belong to the `subscription/` stack. The shared
budgets execution role and the two Service Control Policy (SCP) objects — an SCP
is an organization-wide permission boundary — that it used to create are now
owned by the management-only [`../governance-shared/`](../governance-shared/README.md)
stack; moving them out is what lets foundation run read-only in a child account.

### Dual-mode caution

Foundation adopts whichever instance the credentialed account exposes — no input
selects the mode.

| | Organization mode (default) | Account mode |
| --- | --- | --- |
| `AWS_PROFILE` | management-account profile | **child/member account's** profile |
| Adopted instance | the organization instance | the child's own account instance |
| Downstream subscription | run in the management account | run in the same child account (`instance_mode = "account"`) |

> ⚠️ **Confirm the account before you apply.** If you run foundation with a
> **management-account** profile while intending account mode, the lookup
> silently resolves the **organization** instance and you carry the wrong IDs
> forward. Run `mise run verify` and confirm it reports the account you intend
> before applying.

## Prerequisites

1. **Phase 0 setup done** — toolchain installed and AWS sign-in complete (see
   the [root README](../README.md) Phase 0 section).
2. **Step 1 backend bootstrap done** ([`../backend/README.md`](../backend/README.md)).
   The bootstrap creates the shared S3 bucket and lock table and writes
   `foundation/terraform/backend.hcl` for you. Foundation reuses that one shared
   bucket under its own state key `foundation/terraform.tfstate` (no
   `workshops/<id>/` prefix, because the adopted instance is a single per-account
   resource). The foundation tasks fail closed if this is missing.
3. **Step 0 — IAM Identity Center enabled in the credentialed account**
   (one-time console action; see below).

### Step 0 — enable IAM Identity Center (one-time, console)

This repo **adopts** an existing IdC instance; it does not create one. If IdC has
never been enabled in the account, there is no instance to read and the plan
fails.

1. Sign in to the **target account** — your AWS Organizations management account
   (organization mode) or the child/member account (account mode).
2. Open **IAM Identity Center** in the AWS console.
3. **Enable** IAM Identity Center. This creates the account's instance — an
   organization instance in the management account, or an account instance in a
   child account.

Expected result: IAM Identity Center shows one enabled instance. If you skip
this, `mise run foundation-plan` finds no instance (the
`data "aws_ssoadmin_instances"` lookup returns an empty list) and fails — that
empty result *is* the missing Step 0. Enable IdC, then re-run.

Reference (rephrased for compliance):
[Enable IAM Identity Center](https://docs.aws.amazon.com/singlesignon/latest/userguide/get-set-up-for-idc.html).
Exactly one instance is exposed per account.

> **Note (SCP policy type).** The all-features-mode + `SERVICE_CONTROL_POLICY`
> enablement is **not** a foundation prerequisite — the SCPs moved to
> `governance-shared/`. See [`../governance-shared/README.md`](../governance-shared/README.md)
> if you use the governance track.

## How to run

Run from the repo root; mise exports `AWS_PROFILE` / `AWS_REGION` from your
`.env` automatically. The order is: **plan → apply → wire the IDs forward.**

1. **Confirm the account.** Run `mise run verify` (it calls
   `aws sts get-caller-identity`) and confirm it reports the account you intend —
   the management account in organization mode, or the child/member account in
   account mode. This guards against the dual-mode caution above.
2. **`mise run foundation-plan`** — dry run. Runs `tofu init` + `plan`, a pure
   read of the IdC instance. Expect `0 to add`; it changes nothing.
3. **`mise run foundation-apply`** — adopts (reads) the IdC instance and prints
   the exact `TF_VAR_*` export lines to carry forward. It prompts to approve and
   still creates nothing.
4. **Wire the IDs into the subscription step (step 5).** Export the two outputs
   so the subscription stack picks them up through its existing variables:

   ```bash
   cd foundation/terraform
   export TF_VAR_idc_instance_arn="$(tofu output -raw instance_arn)"
   export TF_VAR_identity_store_id="$(tofu output -raw identity_store_id)"

   # Informational only:
   tofu output -raw sign_in_url     # https://<identity-store-id>.awsapps.com/start
   tofu output -raw region
   ```

   The outputs are plain strings, so `tofu output -raw` emits a bare value you
   can assign straight to a `TF_VAR_*` variable. Prefer a file? Write them into
   the subscription stack's `terraform.tfvars` instead:

   ```hcl
   # subscription/terraform/terraform.tfvars
   idc_instance_arn  = "arn:aws:sso:::instance/ssoins-xxxxxxxxxxxx"
   identity_store_id = "d-xxxxxxxxxx"
   ```

The two IDs map forward as:

| Foundation output   | Subscription input          |
| ------------------- | --------------------------- |
| `instance_arn`      | `TF_VAR_idc_instance_arn`   |
| `identity_store_id` | `TF_VAR_identity_store_id`  |
| `region`            | (informational)             |
| `sign_in_url`       | (informational)             |

The stacks are wired together **by you, through variables** — never through a
remote-state reference. No stack declares a `data "terraform_remote_state"`
pointing at another, so each can be planned, applied, or destroyed on its own.
Because foundation runs once per account and is reused, you do this wiring once
and reuse the same IDs for every subsequent workshop. The three governance IDs
(`budgets_execution_role_arn`, `kiro_guardrail_scp_id`, `freeze_scp_id`) are
**not** emitted here — get them from
[`../governance-shared/README.md`](../governance-shared/README.md).

Re-running is always safe: the data source resolves the same single instance on
every run, foundation owns no managed resources, and a re-run converges to
`0 to change`.

Prefer raw tofu? The equivalent of steps 2–3 by hand:

```bash
cd foundation/terraform
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=foundation/terraform.tfstate"
tofu plan       # a pure read of the IdC instance (0 to add)
tofu apply      # resolves the data source; creates nothing
```

## Teardown

See the root [`TEARDOWN.md`](../TEARDOWN.md) for how to remove this stack —
`foundation-destroy` is a documented no-op (foundation adopts the instance
read-only and owns nothing to destroy).
