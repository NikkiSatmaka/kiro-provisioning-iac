# Runbook — Govern a workshop's accounts (OU + guardrail + auto-freeze budgets)

This is the **optional Governance track** (root [`README.md`](../README.md)),
run in the management account against a workshop's **member accounts**; it is
not part of the linear Phase 0→4 flow. **Prerequisites:** Phase 0 auth +
Phase 1 backend, the management-only `governance-shared/` stack applied, and
member accounts already in the organization.

> **Shared primitives come from `governance-shared/`.** This stack is a pure
> **consumer** of the budgets execution role and the two SCP policy objects. Run
> [`../governance-shared/RUNBOOK.md`](../governance-shared/RUNBOOK.md) once
> first, then export the three `TF_VAR_*` it prints
> (`TF_VAR_budgets_execution_role_arn`, `TF_VAR_kiro_guardrail_scp_id`,
> `TF_VAR_freeze_scp_id`) before `governance-apply`. The `governance-*` tasks
> fail closed if any is unset. (These used to come from `foundation/`; they
> moved to `governance-shared/` when the SCPs left foundation.)

End-to-end order of operations for the **management-account-scoped** governance
stack: one OU per workshop, a Kiro-only guardrail SCP on the OU, an unattached
deny-all freeze SCP, and per-account budgets whose breach **automatically**
freezes the single breaching account. Steps marked **(IaC)** are automated here;
steps marked **(mgmt account)** or **(console)** are AWS platform limits you do
by hand. Nothing in this repo runs on its own — you invoke each step.

> Legend: **(mgmt account)** = AWS Organizations management account (or a
> delegated Organizations administrator), where every stack in this repo runs ·
> **(member accounts)** = the organization member accounts this stack's SCPs and
> budgets *target* · **(IaC)** = `tofu` · **(console)** = AWS web console.

Like the other stacks, this one runs with **management-account or delegated
Organizations-admin credentials**, selected through `var.aws_profile`. What is
distinct is its *targets*: the SCPs and budgets act on the **member accounts** in
`var.account_ids` (which must already be members of the organization — this stack
never creates or invites accounts; account creation is out of scope).

> ⚠️ **High blast radius.** `tofu apply` here mutates the **live AWS
> Organizations management account** — it creates the OU, attaches SCPs, and
> wires automatic freeze actions. (Moving the existing accounts into the OU is a
> separate out-of-band step, `governance-place-accounts` — see Step 3.) Apply
> only with an explicit go-ahead. See the verification-only note at the end.

---

## Step 0 — (mgmt account, one-time) Enable all-features + the SCP policy type

Service Control Policies and OUs only work when AWS Organizations is in **"all
features"** mode **and** the `SERVICE_CONTROL_POLICY` policy type is **enabled on
the organization root**. This is a **platform precondition this stack cannot
perform** — it lives in the management account, not in this repo.

1. Sign in to the **management account** (or your delegated Organizations
   administrator account).
2. Open **AWS Organizations** in the console.
3. Confirm the org is in **all features** mode (**Settings** → enable all
   features if it still shows consolidated-billing-only). This is a one-time,
   irreversible upgrade.
4. Enable the **Service control policies** policy type on the **root**
   (**Policies → Service control policies → Enable**).

Verify (from the management account):
- Organizations reports **all features** enabled.
- The **Service control policies** policy type shows **enabled** on the root.

If you skip this, apply **fails with an AWS Organizations authorization /
policy-type error** — typically an `AccessDeniedException` or a
`PolicyTypeNotEnabledException`. The policy *objects* are created by
`governance-shared/` (`aws_organizations_policy`), so that stack hits the error
first if the policy type is missing; this stack's
`aws_organizations_policy_attachment` needs the same precondition. That error
*is* the missing Step 0 precondition; nothing in this repo can enable it for you.

Docs (rephrased for compliance):
[Enabling all features](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_org_support-all-features.html)
and
[Enabling a policy type](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_enable-disable.html).

---

## Step 1 — (mgmt account) Confirm credentials & region

This stack targets the **Organizations management account** (or a delegated
Org-admin). Point `var.aws_profile` at those credentials — the same
management-account profile every stack in this repo now uses.

```bash
# Confirm you are authenticated as the management/Org-admin principal.
mise run verify          # aws sts get-caller-identity
```

Region and profile resolve from the environment with the usual fallback
(`var.aws_region`/`var.aws_profile`, each `!= "" ? ... : null`). Set them in the
git-ignored `.env` (or export `TF_VAR_aws_profile`) rather than editing tracked
files.

---

## Step 1b — (IaC, one-time) Shared remote S3 state backend (required)

**Mandatory. Do it before Step 2** — the governance tasks fail closed without
it. The `../backend/` stack creates the shared S3 bucket + lock table and writes
`governance/terraform/backend.hcl` for you (the same bootstrap writes the
foundation, governance-shared, subscription, and claim-service files, so you run
it once for every stack).

```bash
mise run backend-bootstrap-plan      # DRY RUN: what the bucket + lock table bootstrap would create
mise run backend-bootstrap           # create them AND write every stack's backend.hcl (prompts)
```

The governance stack reuses that one shared bucket under its own
workshop-namespaced state key `workshops/<WORKSHOP_ID>/governance/terraform.tfstate`,
so each workshop's governance state stays isolated.

Verify:
- `governance/terraform/backend.hcl` exists (git-ignored; `backend.tf` is
  tracked and already present) and carries **no** `key` line — the key is
  supplied at init time.
- A later `mise run governance-plan` reports the S3 backend is initialized (it
  fails closed if `backend.hcl` is missing, and also if `backend.hcl` carries a
  residual `key` line).

---

## Step 2 — (IaC) Plan / apply the governance stack

Set the workshop and the required inputs, then plan before you apply. The
`governance-*` tasks reuse the shared `WORKSHOP_ID` guard (strip whitespace →
fail if empty → slug regex → reject `--` → `backend.hcl` must exist → reject a
`key` line in `backend.hcl`) and run `tofu init -reconfigure` with this
workshop's governance key for you.

```bash
# Required inputs (set in the git-ignored .env or export as TF_VAR_*):
#   WORKSHOP_ID               the per-workshop slug (names the OU: workshop-<id>)
#   TF_VAR_parent_id          the parent OU / root the workshop OU hangs under
#   TF_VAR_account_ids        pre-existing, in-org 12-digit account ids
#   TF_VAR_notification_emails REQUIRED, non-empty (a breach must never be silent)
#   TF_VAR_aws_profile        management/Org-admin creds (same mgmt account every stack uses)

mise run governance-plan     # DRY RUN: tofu init + plan, mutates nothing
mise run governance-apply    # apply — prompts to approve (no -auto-approve), then echoes outputs
```

Both tasks run, for you:

```bash
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=workshops/${WORKSHOP_ID}/governance/terraform.tfstate"
```

What a clean apply produces (confirm this plan shape before approving):

- **1** `aws_organizations_organizational_unit.workshop` named
  `workshop-<workshop_id>` under `var.parent_id`.
- **2** SCPs: `kiro-guardrail-<id>` (attached to the OU) and `freeze-<id>`
  (created with **0 attachments**).
- **1** budgets execution role (`governance-budgets-exec-<id>`) + its inline
  policy.
- **N** COST budgets (`governance-<id>-<account>`), each filtered to its own
  `LinkedAccount`.
- **N** `AUTOMATIC` SCP budget actions, each targeting **only its own account**.

The accounts themselves are **not** in the plan — the stack owns no account
resource. They are moved into the OU in the next step.

---

## Step 3 — (out-of-band) Move the existing accounts into the OU

The governance stack creates **only** the OU. The pre-existing, in-org accounts
in `var.account_ids` are moved into that OU **outside Terraform**, by a dedicated
task that runs `aws organizations move-account` once per id:

```bash
# Reads account_ids from the stack output (terraform.tfvars is the source of
# truth); WORKSHOP_ID comes from .env. Set ACCOUNT_IDS only to move a subset.
mise run governance-place-accounts
```

The task reuses the governance `WORKSHOP_ID` guard and `backend.hcl` checks,
runs `tofu init -reconfigure` to this workshop's key, reads the destination OU
from `tofu output -raw workshop_ou_id`, and for each id finds its current parent
(`aws organizations list-parents`) and moves it:

```bash
aws organizations move-account \
  --account-id <id> \
  --source-parent-id <current parent id> \
  --destination-parent-id <workshop OU id>
```

It is **idempotent** — an account already in the destination OU is skipped with
no error — and it echoes every move. It runs only `tofu output` (never
`tofu apply`), so it does **not** need the three governance-shared `TF_VAR_*`
wire-forwards, but it does need a working `tofu init`; if `workshop_ou_id` cannot
be read it fails closed (run `governance-apply` for this workshop first).

> ⚠️ **Why out-of-band, not Terraform:** `hashicorp/aws` v6.67.0 has no
> standalone "move account into an OU" resource. The only resource carrying
> account→OU placement is `aws_organizations_account` — AWS's *create*-an-account
> resource — so expressing placement in Terraform risks **creating brand-new
> accounts** on an apply with no prior state. Keeping the move out-of-band makes
> it structurally impossible for this stack to create, invite, close, or own an
> account.

---

## Automatic freeze behavior — (IaC, runtime)

Each account carries a COST budget (`aws_budgets_budget.account[<id>]`) with a
matching `AUTOMATIC` SCP action (`aws_budgets_budget_action.freeze[<id>]`):

- **On breach** of `var.freeze_threshold_percent` (default `90`), AWS Budgets
  assumes the budgets execution role and **attaches the freeze SCP to the single
  breaching account** — `scp_action_definition.target_ids = [<that account>]`,
  **never the OU**, so one account's overrun never freezes the whole workshop.
- Because `approval_model = "AUTOMATIC"`, the freeze happens with **no human in
  the loop**.
- Every address in `var.notification_emails` is subscribed **notify-only** on
  each budget across a tiered set of ACTUAL-cost alerts: one per entry in
  `var.notify_threshold_percents` (default `[50, 75]`) plus the freeze-level
  alert at `var.freeze_threshold_percent` (default `90`). Default tiers: alert
  at 50%, alert at 75%, alert + freeze at 90% — so a breach is never silent.

A frozen account's users can no longer operate it (the deny-all SCP overrides
the guardrail). Recovery is **manual** — see the next section.

---

## Manual un-freeze — (console or CLI) — NO automation

**The stack provides no recovery automation.** There is **no `governance-unfreeze`
task**, and nothing in this stack detaches the freeze SCP. To restore a frozen
account you detach the freeze SCP yourself, by hand:

```bash
# Get the freeze SCP id if you don't have it:
#   cd governance/terraform && tofu output -raw freeze_scp_id
aws organizations detach-policy \
  --policy-id <freeze_scp_id> \
  --target-id <account_id>
```

Or, in the console: **AWS Organizations → the frozen account → Policies →
Service control policies → detach** the `freeze-<id>` policy.

Detaching the freeze SCP leaves the OU-level Kiro guardrail in place, so the
account returns to its normal Kiro-only boundary. Address the cost overrun (or
raise the budget) before un-freezing, or the next breach re-attaches it.

---

## Teardown — (IaC) two steps, each typed-phrase guarded

Teardown is **two tasks, in order**. Account placement is out-of-band (the
stack owns only the OU, never an account resource), so there is nothing in
Terraform state to clean up and no `prevent_destroy` guard to clear. But AWS
Organizations refuses to delete a **non-empty** OU, so you must move the
accounts back **out** of the OU first, then destroy.

### Step A — move the accounts out of the OU

```bash
mise run governance-move-accounts-out
```

This empties the OU **without touching the accounts themselves** — it is the
exact mirror of `governance-place-accounts` (which moved them in):

1. It prompts you to type exactly **`move-accounts-out`**. Any other string
   (including empty or whitespace) exits non-zero and **moves nothing**.
2. On a match (and after the shared `WORKSHOP_ID` guard + backend reconfigure),
   it reads this workshop's `account_ids` and `workshop_ou_id` from
   `tofu output` (the same single source of truth `governance-place-accounts`
   uses — never any account outside `var.account_ids`), and for each one:
   - resolves the account's real current parent via
     `aws organizations list-parents` (the move source);
   - moves it back to `var.parent_id` (the parent the workshop OU hangs under)
     with `aws organizations move-account`, skipping any account already there.

   It runs only `tofu output` (never `tofu apply`) and touches **no** Terraform
   state. Set `ACCOUNT_IDS="<id> <id>"` to override the tfvars-derived list with
   a deliberate subset.

> ⚠️ Moving the accounts back to `var.parent_id` (typically the org root) takes
> them out from under the workshop OU, so they **lose the Kiro guardrail (and
> any still-attached freeze) SCP**. Detach any freeze SCP still attached to a
> moved account by hand first (see the manual un-freeze above).

The `moveAccount` fallback still applies if you prefer to do it entirely by hand:
`aws organizations move-account` (destination = root or another parent), or the
console "Move AWS account" action, once per account.

### Step B — destroy the stack

```bash
mise run governance-destroy
```

That task puts two gates in front of the delete, mirroring `foundation-destroy`:

1. It prompts you to type exactly **`destroy-governance`**. Any other string
   (including empty or whitespace) exits non-zero and **destroys nothing**.
2. On a match, it still requires `tofu`'s **own** apply/destroy approval prompt
   before anything is deleted.

The stack owns **no account resource**, so a destroy can never touch (or close)
a pre-existing account. But OpenTofu refuses to remove an OU that still holds
accounts or a policy that is still attached — which is exactly why Step A runs
first. With the OU emptied:

- **Detach the SCPs:** the guardrail detaches as part of destroy once the OU is
  empty; detach any freeze SCP still attached to a (now-moved) account first
  (see the manual un-freeze above).

Only then does `governance-destroy` remove the OU, the two SCPs, the budgets
execution role, and the per-account budgets + actions. The accounts themselves
remain — created, moved, and closed externally, never by this stack.

---

## Verification is non-mutating only

Authoring and reviewing this stack uses **`tofu fmt`, `tofu validate`, and
`tofu plan` only** — never `tofu apply` or `tofu destroy`. Applying mutates the
live AWS Organizations management account (high blast radius) and happens **only
with the operator's explicit go-ahead**.

```bash
cd governance/terraform
tofu fmt -check
tofu init -backend=false && tofu validate
mise run governance-plan     # sample-tfvars plan; creates/closes nothing
```

---

## Quick reference — what is / isn't automated

| Step | Automated here? | Why |
| ---- | --------------- | --- |
| All-features + SCP policy type on the root (Step 0) | ❌ (mgmt account console) | Org-level platform precondition; the stack cannot enable it |
| Shared backend bucket + `backend.hcl` (Step 1b) | ✅ (IaC, `backend-bootstrap`) | — |
| Create OU + guardrail attachment + budgets (Step 2) | ✅ (IaC, `governance-apply`) | High blast radius; apply only with explicit go-ahead |
| Move pre-existing accounts into the OU (Step 3) | ✅ (out-of-band, `governance-place-accounts`) | No standalone move-into-OU resource in hashicorp/aws v6.67.0; a TF resource would risk CREATING accounts |
| Automatic freeze on budget breach | ✅ (IaC, `AUTOMATIC` SCP budget action) | Attaches freeze SCP to the single breaching account |
| Un-freeze a frozen account | ❌ (console / `aws organizations detach-policy`) | No recovery automation by design |
| Empty the OU before teardown | ✅ (out-of-band, `governance-move-accounts-out`, typed-phrase `move-accounts-out`) | Mirror of `governance-place-accounts`: moves accounts back to `parent_id` via `move-account`; no TF state, never closes accounts |
| Destroy the governance stack | ✅ (`governance-destroy`, typed-phrase `destroy-governance`) | Run `governance-move-accounts-out` first; never closes accounts |
