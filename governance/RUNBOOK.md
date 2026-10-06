# Runbook — Govern a workshop's accounts (OU + guardrail + auto-freeze budgets)

End-to-end order of operations for the **management-account-scoped** governance
stack: one OU per workshop, a Kiro-only guardrail SCP on the OU, an unattached
deny-all freeze SCP, and per-account budgets whose breach **automatically**
freezes the single breaching account. Steps marked **(IaC)** are automated here;
steps marked **(mgmt account)** or **(console)** are AWS platform limits you do
by hand. Nothing in this repo runs on its own — you invoke each step.

> Legend: **(mgmt account)** = AWS Organizations management account (or a
> delegated Organizations administrator) · **(this account)** = the
> child/member account where Kiro lives · **(IaC)** = `tofu` ·
> **(console)** = AWS web console.

Unlike the other stacks, this one runs with **management-account or delegated
Organizations-admin credentials**, selected through `var.aws_profile` — distinct
from the member-account profile `foundation/`, `subscription/`, and
`claim-service/` use. It never creates or invites accounts: `var.account_ids`
must already be members of the organization. Account creation is out of scope.

> ⚠️ **High blast radius.** `tofu apply` here mutates the **live AWS
> Organizations management account** — it moves accounts, attaches SCPs, and
> wires automatic freeze actions. Apply only with an explicit go-ahead. See the
> verification-only note at the end.

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

If you skip this, Step 2's `tofu apply` **fails with an AWS Organizations
authorization / policy-type error** — typically an `AccessDeniedException` or a
`PolicyTypeNotEnabledException` on the `aws_organizations_policy` /
`aws_organizations_policy_attachment` resources. That error *is* the missing
Step 0 precondition; nothing in this repo can enable it for you.

Docs (rephrased for compliance):
[Enabling all features](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_org_support-all-features.html)
and
[Enabling a policy type](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_enable-disable.html).

---

## Step 1 — (this account/mgmt) Confirm credentials & region

This stack targets the **Organizations management account** (or a delegated
Org-admin). Point `var.aws_profile` at those credentials — they are **not** the
member-account profile the other stacks use.

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
foundation, subscription, and claim-service files, so you run it once for every
stack).

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
#   TF_VAR_aws_profile        management/Org-admin creds (distinct from member profile)

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
- **N** account placements (one per `var.account_ids`) — see the placement
  mechanism below.
- **2** SCPs: `kiro-guardrail-<id>` (attached to the OU) and `freeze-<id>`
  (created with **0 attachments**).
- **1** budgets execution role (`governance-budgets-exec-<id>`) + its inline
  policy.
- **N** COST budgets (`governance-<id>-<account>`), each filtered to its own
  `LinkedAccount`.
- **N** `AUTOMATIC` SCP budget actions, each targeting **only its own account**.

### Account placement — the chosen mechanism (read `organizations.tf`)

`organizations.tf` records the placement mechanism in its
`RUNBOOK (task 10) — RECORD THIS:` comment block. Lifted verbatim:

- **Chosen mechanism:** each pre-existing account is placed via
  `aws_organizations_account.placed["<id>"]` — **adopted via `tofu import`,
  never created** — with `parent_id` pointed at the workshop OU, so the only
  change the provider ever makes is the **move into the OU**. Confirmed against
  the installed provider `hashicorp/aws` **v6.67.0**, which still exposes no
  standalone "move account into an OU" resource.
- `close_on_deletion` is left unset (`false`) — a destroy only **removes** the
  account from the org, it never **closes** it.
- `lifecycle { prevent_destroy = true }` is a second explicit guard: a destroy
  of this stack errors out rather than touching these accounts.
- `ignore_changes = [name, email, role_name]` — these satisfy the importable
  schema but are reconciled from AWS (and `role_name` is unreadable after
  import), so ignoring them keeps the plan to the one meaningful attribute,
  `parent_id` (the placement itself).

**Import is required** before plan/apply shows a clean move — one per supplied
id:

```bash
cd governance/terraform
tofu import 'aws_organizations_account.placed["111111111111"]' 111111111111
# repeat for each id in var.account_ids
```

After import, the only planned change is the move into the workshop OU; if an
account is already in the OU, its plan is a no-op.

#### `moveAccount` fallback

If you prefer not to adopt accounts into state, or the import is impractical:
place the accounts **out-of-band** and let the stack own only the OU + SCP
attachment. Run once per account:

```bash
aws organizations move-account \
  --account-id <id> \
  --source-parent-id <current root/parent id> \
  --destination-parent-id <workshop OU id>
```

(or the console **"Move AWS account"** action). The move is recorded here rather
than driven by `tofu`.

---

## Automatic freeze behavior — (IaC, runtime)

Each account carries a COST budget (`aws_budgets_budget.account[<id>]`) with a
matching `AUTOMATIC` SCP action (`aws_budgets_budget_action.freeze[<id>]`):

- **On breach** of `var.freeze_threshold_percent` (default `100`), AWS Budgets
  assumes the budgets execution role and **attaches the freeze SCP to the single
  breaching account** — `scp_action_definition.target_ids = [<that account>]`,
  **never the OU**, so one account's overrun never freezes the whole workshop.
- Because `approval_model = "AUTOMATIC"`, the freeze happens with **no human in
  the loop**.
- Every address in `var.notification_emails` is subscribed **notify-only** on
  each budget, so a breach is never silent. An optional softer notify-only
  threshold is added when `var.notify_threshold_percent` is set.

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

## Teardown — (IaC) typed-phrase guarded

```bash
mise run governance-destroy
```

That task puts two gates in front of the delete, mirroring `foundation-destroy`:

1. It prompts you to type exactly **`destroy-governance`**. Any other string
   (including empty or whitespace) exits non-zero and **destroys nothing**.
2. On a match, it still requires `tofu`'s **own** apply/destroy approval prompt
   before anything is deleted.

Because account placements carry `prevent_destroy = true`, a destroy **will not
touch (or close) a pre-existing account** — and OpenTofu refuses to remove an OU
that still holds accounts or a policy that is still attached. So before the OU
and SCPs can be removed:

- **Empty the OU:** move each account out with
  `aws organizations move-account` (destination = root or another parent), or
  the console "Move AWS account" action.
- **Detach the SCPs:** the guardrail detaches as part of destroy once the OU is
  empty; detach any freeze SCP still attached to a (now-moved) account first
  (see the manual un-freeze above).

Only then does `governance-destroy` remove the OU, the two SCPs, the budgets
execution role, and the per-account budgets + actions. The accounts themselves
remain — created and closed externally, never by this stack.

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
| Create OU + guardrail + freeze SCP + budgets (Step 2) | ✅ (IaC, `governance-apply`) | High blast radius; apply only with explicit go-ahead |
| Adopt pre-existing accounts into the OU | ⚠️ `tofu import` then plan (or `move-account` fallback) | No standalone move-into-OU resource in hashicorp/aws v6.67.0 |
| Automatic freeze on budget breach | ✅ (IaC, `AUTOMATIC` SCP budget action) | Attaches freeze SCP to the single breaching account |
| Un-freeze a frozen account | ❌ (console / `aws organizations detach-policy`) | No recovery automation by design |
| Destroy the governance stack | ✅ (`governance-destroy`, typed-phrase `destroy-governance`) | Empty the OU + detach SCPs first; never closes accounts |
