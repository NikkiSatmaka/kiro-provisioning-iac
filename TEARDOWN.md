# Teardown — remove everything in reverse order

This is the single teardown document for the whole repo, linked from the root
[`README.md`](./README.md). It removes what the provisioning flow created, in
the **reverse** of the order you built it: step 6 first, step 1 last.

A few terms used below:

- **Workshop** — one run of the flow, identified by a short id. Most teardown
  tasks act on exactly one workshop, so they never disturb another.
- **Organization mode** — you are working against the AWS Organizations
  **management account** and its organization IAM Identity Center instance.
  Steps 3 and 4 (governance-shared and governance) apply only in this mode.
- **Account mode** — you are working against a single child/member account and
  its own account IAM Identity Center instance. In this mode you **skip** steps
  3 and 4 entirely; there is nothing to tear down for them.

> **Before you start — set `WORKSHOP_ID`.** Edit `.env` and set `WORKSHOP_ID`
> to the workshop you are tearing down. The per-workshop tasks (claim-service,
> subscription, governance, and the backend per-workshop cleanup) **fail closed
> without it** — a missing id stops the task rather than guessing which
> workshop to remove.
>
> **Dry-run first.** Where a step has a dry-run task and a mutating task, run
> the dry run first to see exactly what would be removed, then run the mutating
> task. The dry-run task never changes anything.

The sections run from step 6 down to step 1.

---

## 6. Claim-service (if you deployed it)

The optional self-serve credential service (one DynamoDB table, a Lambda, and a
Function URL) is removed first because later steps assume it is already gone.

1. `mise run claim-destroy` — tears down this workshop's claim-service table,
   Lambda, and Function URL. It prompts before it deletes anything and never
   touches the `subscription/` identities.

If you did not deploy the claim service for this workshop, skip this section.

---

## 5. Subscription

This removes **one workshop's** IAM Identity Center users, groups, and
memberships (plus the permission set and account assignments if that workshop
enabled account access). It never deletes the shared Identity Center instance,
which every workshop reuses.

The automatable part has two paths. **Option B (remote-state `tofu destroy`) is
the primary one**; **Option A (a state-free discovery script) is the fallback**
for when `tofu destroy` has no usable state (for example a fresh clone a month
later). Both finish with the same manual Kiro-console cleanup that AWS exposes
no stable API for.

1. `mise run subscription-teardown-plan` — dry run. Discovers what teardown
   would delete and changes nothing.
2. `mise run subscription-destroy` — **Option B (primary).** Runs `tofu
   destroy` against this workshop's remote state and deletes its users, groups,
   and memberships. Prompts to confirm.
   - Fallback: `mise run subscription-teardown-run` — **Option A.** A
     state-free script that rediscovers this workshop's identities live from the
     account by naming convention and deletes them. Use it only when `tofu
     destroy` has no usable state. It prompts to confirm and never deletes the
     shared Identity Center instance.
3. Manual Kiro-console cleanup — AWS has no stable API for these, so do them in
   the console after either path above:
   1. Deactivate the Kiro subscriptions / tier assignments for the workshop's
      groups.
   2. Remove the Kiro application assignment in IAM Identity Center →
      Applications. Removing subscription access does **not** auto-remove this
      assignment, so it lingers if you skip it.
   3. Delete the local secret files: `subscription/output/credentials.md` and
      `subscription/output/otps.csv`.
   4. Do **not** disable IAM Identity Center to clean up one workshop — the
      instance is shared by every workshop. Disabling it is a deliberate,
      standalone console action, never part of a per-workshop teardown.

---

## 4. Governance — 🏢 organization mode only

> **Do I need this step?** Only if you are in **organization mode** (working
> against the AWS Organizations management account). In **account mode** (a
> child/member account) there is no governance stack to remove, so **skip this
> section** and continue at step 3 — which you also skip — then go to step 2.

Governance owns one workshop organizational unit (OU — a folder in AWS
Organizations that groups accounts), the Kiro guardrail Service Control Policy
(SCP — an organization-wide permission boundary) attachment, and the
per-account budgets. AWS Organizations refuses to delete a non-empty OU, so
teardown is **two tasks, in order**: first move the accounts out of the OU, then
destroy the stack.

1. `mise run governance-move-accounts-out` — moves this workshop's accounts back
   out of the workshop OU to their parent so the OU is empty. It prompts you to
   type the phrase `move-accounts-out` before it moves anything, and it never
   creates, closes, or TF-manages an account.
2. `mise run governance-destroy` — deletes the workshop OU, the guardrail
   attachment, the budgets execution role, and the per-account budgets. It
   prompts you to type the phrase `destroy-governance`, then still requires
   OpenTofu's own destroy approval. The accounts themselves are never closed by
   this stack.

> Moving the accounts back out of the OU removes the Kiro guardrail (and any
> still-attached freeze) SCP from them. If a freeze SCP is still attached to a
> moved account, detach it by hand first — recovery from a freeze is a
> deliberate manual detach, by design there is no un-freeze task.

---

## 3. Governance-shared — 🏢 organization mode only

> **Do I need this step?** Only in **organization mode** (the AWS Organizations
> management account). In **account mode** there is nothing here to remove, so
> **skip this section** and go to step 2.

Governance-shared owns the long-lived management-account singletons: the budgets
execution role and the two SCP policy objects (the Kiro guardrail and the
deny-all freeze). These are shared by **every** workshop's governance stack, so
a per-workshop `governance-destroy` never touches them.

Destroy them **only at full decommission** — when the management account is
being retired and **no workshop remains**. There is intentionally **no
`governance-shared-destroy` mise task**; removal is a deliberate manual `tofu
destroy`:

```bash
cd governance-shared/terraform
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=governance-shared/terraform.tfstate"
tofu destroy
```

> Destroying the guardrail or freeze SCP while **any** workshop's governance
> stack still references it breaks that workshop's attachment and freeze
> automation. Tear down every workshop's governance stack (step 4 above) first.

---

## 2. Foundation

There is **nothing to destroy** here. Foundation only *adopts* (reads) whichever
Identity Center instance the account exposes — it is never in the stack's state,
so the stack owns nothing to remove.

- `mise run foundation-destroy` — a documented **no-op**. It runs no OpenTofu and
  deletes nothing; it only prints a note confirming there is nothing to tear
  down.
- Disabling IAM Identity Center itself is a deliberate management-account console
  action, never a repo task. Do it only when no workshop depends on the
  directory.

---

## 1. Backend (last)

The backend is the shared S3 remote-state bucket and DynamoDB lock table that
every workshop's state lives in, so it is torn down **last**. There are two
scopes:

- **One finished workshop, others still live** — remove just this workshop's
  leftover state:
  1. `mise run backend-destroy-workshop` — dry run by default. Lists the S3
     object versions, delete markers, and lock rows it would purge under
     `workshops/<WORKSHOP_ID>/` and changes nothing. It is surgical: it never
     touches the shared bucket, the lock table, or any other workshop.
  2. `APPLY=1 mise run backend-destroy-workshop` — performs the purge. It
     prompts you to type the phrase `destroy-workshop-state` before deleting.
- **All workshops done** — remove the whole shared backend:
  1. `mise run backend-destroy` — deletes the entire shared S3 state bucket and
     DynamoDB lock table (it flips `force_destroy=true` to empty the versioned
     bucket first, then destroys). This is all-or-nothing, so run it only when
     **every** workshop has been torn down.
