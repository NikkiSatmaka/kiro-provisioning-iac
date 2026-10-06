# Runbook — Provision Kiro subscriptions in the management account

End-to-end order of operations. Steps marked **(IaC)** or **(script)** are
automated here; steps marked **(console)** are AWS platform limits you must do
by hand. Nothing in this repo runs on its own — you invoke each step.

> Legend: **(mgmt account)** = the AWS Organizations management account, where
> every stack in this repo now provisions · **(this account)** = the same
> management account · **(IaC)** = `tofu` · **(script)** = Python ·
> **(console)** = AWS web console.

---

## Step 0 — (mgmt account, one-time) Enable IAM Identity Center

Identities are created in the management account's **organization** IdC
instance, which the `foundation/` stack adopts. If IAM Identity Center has never
been enabled in the management account, there is no instance to write into.

1. Sign in to the **management account** (`<MGMT_ACCOUNT_ID>` — your AWS
   Organizations management account).
2. Open **IAM Identity Center** in the console.
3. **Enable** IAM Identity Center. This creates the single organization instance.

Verify (from the management account):
- IAM Identity Center is enabled and shows an organization instance.
- `foundation/` resolves its ARN / identity store id (see
  [`../foundation/RUNBOOK.md`](../foundation/RUNBOOK.md)).

Docs (rephrased for compliance):
[Enable IAM Identity Center](https://docs.aws.amazon.com/singlesignon/latest/userguide/get-set-up-for-idc.html).

> ℹ️ Exactly one organization instance exists per management account. This stack
> consumes it via `idc_instance_arn` / `identity_store_id`; it never creates or
> destroys it.

---

## Step 1 — (this account) Confirm credentials & region

Assumes the toolchain + AWS auth are already set up (root README, Phase 0).

```bash
# From repo root; mise exports AWS_PROFILE / AWS_REGION automatically.
mise run verify          # aws sts get-caller-identity
```

Confirm the account is the intended **management** account and the region is one
Kiro supports for IdC. `AWS_PROFILE` must be a management-account profile.
Profile and region come from the git-ignored `.env` (default region
`us-east-1`); see the root README's Phase 0 if `mise run verify` resolves the
wrong account.

---

## Step 1b — (IaC, one-time) Set up the remote S3 state backend (required)

**This step is mandatory. Do it before Step 2** — provisioning fails closed
without it. It matters for *this* stack specifically: `tofu destroy` can only
remove what is in its state, so if the subscription's state is not in S3, a
teardown from a fresh clone later would orphan every user and group. The
`../backend/` stack creates that S3 bucket + lock table and writes
`subscription/terraform/backend.hcl` for you (the same bootstrap also writes
`claim-service/terraform/backend.hcl`, used later if you distribute via the
claim service).

```bash
mise run backend-bootstrap-plan      # DRY RUN: what the bucket + lock table bootstrap would create
mise run backend-bootstrap           # create them AND write the stacks' backend.hcl (prompts)
```

That is all this stack needs from the backend. The mechanics — why the backend
stack keeps its own local state, the derived bucket name, and the manual
`backend.hcl` escape hatch — are documented in
[`../backend/README.md`](../backend/README.md).

Verify:
- `subscription/terraform/backend.hcl` exists (git-ignored; `backend.tf` is
  tracked and already present).
- `mise run provision-plan` runs `tofu init -backend-config=backend.hcl` and
  reports the S3 backend is initialized (it fails closed if `backend.hcl` is
  missing).

---

## Step 2 — (IaC) Create users, groups, memberships in the org instance

```bash
# 1. Set your accounts/groups/counts/tier (no task — one-time copy + edit).
cp subscription/terraform/terraform.tfvars.example subscription/terraform/terraform.tfvars

# 2. Dry run — tofu init + plan (N users + M groups + memberships).
mise run provision-plan      # creates nothing

# 3. Apply — creates them (prompts to approve).
mise run provision
```

Both tasks run `tofu init -backend-config=backend.hcl` for you (S3 backend from
Step 1b) and **require** it — they fail closed if Step 1b was skipped.

Prefer raw tofu? The equivalent by hand:

```bash
cd subscription/terraform
tofu init -backend-config=backend.hcl          # S3 backend from Step 1b
tofu plan      # review: N users + M groups + memberships
tofu apply     # creates them
```

What this creates (in the management account's shared organization IdC
instance):
- IdC users, workshop-namespaced `<workshop_id>-<acct_last4>-<group>-<NN>`.
- IdC groups with workshop-namespaced display names `<workshop_id>-<group>`.
- Group memberships (each user in its own group).
- **No** permission sets and **no** account assignments by default
  (`enable_account_access = false`) — these identities can log into Kiro and
  nothing else. The organization instance itself is never created or modified.

> **Granting console access later (optional).** The `workshop_accounts` account
> ids are billing attribution only. If you ever need to grant AWS console
> access, set `enable_account_access = true` in tfvars and re-apply: that
> creates one shared permission set and one assignment per group binding it to
> its owning member account id. Leave it `false` for Kiro-login-only workshops.

`mise run provision` already exports the manifest the scripts consume. To
re-export it by hand:
```bash
cd subscription/terraform
tofu output -json provisioning_manifest > ../output/manifest.json
```

Verify:
- `tofu output users` / `tofu output groups` list the expected namespaced names.
- Console → IAM Identity Center → Users / Groups shows them.

---

## Step 2b — (console, one-time) Make MFA optional for sign-in

By default the instance requires MFA **every time** users sign in and prompts
them to register a device. These Kiro-login-only users are not obligated to set
up MFA, so turn it off. Not settable from IaC (no provider resource / public
API for the MFA mode).

1. In the **management account**, open **IAM Identity Center → Settings**.
2. **Authentication** tab → **Multi-factor authentication** → **Configure**.
3. Under **Prompt users for MFA**, choose **Never (disabled)**.
4. **Save changes.**

Verify:
- The Authentication tab shows MFA prompt = **Disabled**.
- A test user signs in with username + password only, no MFA prompt.

> This setting is instance-wide. Because the organization instance is shared by
> every workshop, changing the MFA mode affects all of them — set it once,
> deliberately. If you later need MFA for some users, switch to "Context-aware"
> or "Always-on" instead.

---

## Step 3 — (console, one-time) Enable Kiro with IAM Identity Center

This provisions the Kiro profile + service-linked role. Not scriptable.

1. In the **management account**, open the **Kiro** console (check you are in
   the right region — the one from Step 2).
2. Click **Onboard your team to Kiro** (or **Enable small teams**).
3. When asked for the identity source, choose **IAM Identity Center**. You may
   be prompted to verify the IdC configuration.
4. Click **Enable**. A Kiro profile is created.

You do **not** need to copy the sign-in URL from this screen. Step 5's
`mise run credentials` always takes it from the manifest, which Terraform
derives from the identity store id (`https://<identity-store-id>.awsapps.com/start`).

---

## Step 4 — Assign the Kiro tier to each group

Two paths. The console path is the reliable one.

### 4a — (script, best-effort, opt-in) Try the API

```bash
cd subscription/scripts
python attempt_kiro_subscription.py --manifest ../output/manifest.json   # dry run
python attempt_kiro_subscription.py --manifest ../output/manifest.json --attempt --tier PRO
```

This is **fail-closed**: if the installed SDK exposes no subscription API (the
normal case), it prints the console steps and exits non-zero. Even on an
accepted call, verify in the console — an accepted API call is not proof of an
active plan.

### 4b — (console) The reliable path

1. Kiro console → **Users & Groups → Groups** tab → **Add group**.
2. Select each workshop-namespaced `<workshop_id>-<group>` group.
3. In the dialog, choose the tier (**Pro / Pro+ / Pro Max / Power**) and confirm.

Verify:
- Each group shows the assigned plan as active in the Kiro console.

---

## Step 5 — Passwords + credentials file

IAM Identity Center has **no API** to set or share a password. Use the console
one-time-password (OTP) flow, then render the Markdown.

1. **(console)** IAM Identity Center → **Users**. For each user:
   **Reset password → Generate a one-time password → copy it.**
   (The alternative, "Send an email…", needs real inboxes.)
2. Record them in a CSV (git-ignored) at `subscription/output/otps.csv`:
   ```csv
   username,otp
   <workshop_id>-<acct_last4>-<group>-01,<otp>
   <workshop_id>-<acct_last4>-<group>-02,<otp>
   ```
3. **(task)** Render the credentials file:
   ```bash
   mise run credentials
   ```
   This reads `output/otps.csv` and writes `output/credentials.md`. The
   **sign-in URL is always taken from the manifest** — `tofu output` derives it
   from the identity store id (`https://<identity-store-id>.awsapps.com/start`),
   so it is never passed in by hand. The task fails fast with instructions if
   `output/otps.csv` is missing.

`output/credentials.md` is git-ignored. It lists each user's username, email
(if set; anonymous users show a dash), member account id (billing attribution),
group(s), OTP, and the sign-in URL + region.

> On "same default password": AWS does not allow an admin-chosen shared
> password. The closest supported option is a per-user OTP that the user must
> change on first sign-in. The tooling captures those OTPs; it cannot force one
> shared value.

---

## Step 6 — Distribute & verify sign-in

You have two ways to get credentials to users — pick one:

- **Direct (default):** share `output/credentials.md` securely; delete it after
  distribution.
- **Self-serve claim service (optional):** instead of handing out the file,
  deploy the `claim-service/` stack and let participants claim their own
  credential from a QR code / short link using a workshop code. It seeds its
  pool from the `output/otps.csv` + `output/manifest.json` you just produced, so
  run it only **after** this step. See
  [`../claim-service/README.md`](../claim-service/README.md) for the
  `mise run claim-*` lifecycle (deploy → seed → audit → destroy).

Then, however it was distributed:

1. A user signs in: Kiro → sign in with organization → **Sign in via IAM
   Identity Center** → enter the **Sign-in URL** + **region code** → username +
   OTP → set a new password → **Allow access**.
2. Confirm the Kiro subscription is visible/active inside Kiro.

---

## Teardown

Full teardown instructions — including how to do it **from a different machine
a month later** — live in [`TEARDOWN.md`](./TEARDOWN.md). Two paths:

- **Option B (standard):** remote S3 state + `tofu destroy`. The remote backend
  is set up as a **required** step at provision time (Step 1b: bootstrap bucket
  + `backend.hcl`), so state lives in S3 and `tofu destroy` works from any clone.

  ```bash
  mise run teardown-tofu    # tofu destroy: removes this workshop's users, groups, memberships (prompts to confirm)
  ```

- **Option A (fallback):** a state-free discovery script for when no state is
  available (fresh clone, local state gone).

  ```bash
  mise run teardown-plan    # dry run: discover what would be deleted
  mise run teardown-run     # delete this workshop's IdC users/groups/memberships (prompts to confirm)
  ```

Caveats (detailed in `TEARDOWN.md`):
- Remote S3 state (Option B, set up in Step 1b) is what makes `tofu destroy`
  work from any machine. If you ever ran without it, a local backend holds state
  only on the machine that created it and deletes nothing on a fresh clone — use
  Option A (the state-free script) to recover that case.
- **The shared organization IdC instance is NEVER deleted** by either path — all
  stacks run in the management account against the one org instance, so removing
  it would wipe every other workshop. Teardown removes only this workshop's
  users / groups / memberships (and, when `enable_account_access` was true, the
  permission set / assignments).
- **Deactivate Kiro subscriptions first** in the Kiro console. Per Kiro docs,
  when you remove access "at end of month" the Kiro-created Identity Center
  application assignment is **not** auto-removed and needs a manual cleanup step
  in IdC.
- Delete any local `output/credentials.md` and `output/otps.csv`.

---

## Quick reference — what is / isn't automated

| Step | Automated here? | Why |
| ---- | --------------- | --- |
| Enable IAM Identity Center (Step 0) | ❌ (mgmt account console) | One-time console enablement of the org instance |
| Create users / groups / memberships | ✅ (IaC) | In the shared org instance; the instance itself is never created |
| Gated account access (permission set / assignment) | ✅ (IaC, `enable_account_access`) | Off by default; zero console access |
| Make MFA optional (prompt = Never) | ❌ (console) | No provider resource / public API for MFA mode |
| Enable Kiro + Kiro profile | ❌ (console) | Provisions service-linked role; no stable API |
| Assign tier to group | ⚠️ best-effort script, else console | `q:CreateAssignment` is internal/undocumented |
| Set/share password | ❌ (console OTP) | IdC has no password API |
| Render credentials.md | ✅ (script) | — |
| Teardown users/groups/memberships | ✅ (`tofu destroy`, or `teardown.py`) | Uses required remote state (Step 1b); state-free script is the fallback. The shared org instance is never deleted |
| Deactivate Kiro subscription + app assignment | ❌ (console) | No stable API; not auto-removed |
