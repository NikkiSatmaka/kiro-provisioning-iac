# Runbook — Provision Kiro subscriptions in a child account

End-to-end order of operations. Steps marked **(IaC)** or **(script)** are
automated here; steps marked **(console)** or **(mgmt account)** are AWS
platform limits you must do by hand. Nothing in this repo runs on its own — you
invoke each step.

> Legend: **(mgmt account)** = AWS Organizations management account ·
> **(this account)** = the child/member account where Kiro lives ·
> **(IaC)** = `tofu` · **(script)** = Python · **(console)** = AWS web console.

---

## Step 0 — (mgmt account, one-time) Permit member-account IdC instances

An account instance can only be created in a member account if the org
management account has turned this on. It is a **one-time, irreversible** toggle.

1. Sign in to the **management account** (`<MGMT_ACCOUNT_ID>` — your AWS
   Organizations management account).
2. Open **IAM Identity Center** in the console.
3. **Settings → Management → Account instances of IAM Identity Center → Enable.**
   Confirm. (You can later constrain this with an SCP; see the AWS docs.)

Verify (from the management account):
- The setting shows account instances are allowed.

If you skip this, Step 2's `tofu apply` fails with an authorization error on
`awscc_sso_instance`.

Docs (rephrased for compliance):
[Permit account instance creation](https://docs.aws.amazon.com/singlesignon/latest/userguide/enable-account-instance-console.html).

> ℹ️ One account instance per account, across **all** regions. If this account
> already has an account instance, import it instead of creating a new one:
> `tofu import awscc_sso_instance.this <instance_arn>`.

---

## Step 1 — (this account) Confirm credentials & region

```bash
# From repo root; mise exports AWS_PROFILE / AWS_REGION automatically.
mise run verify          # aws sts get-caller-identity
```

Confirm the account is the intended **child** account and the region is one
Kiro supports for IdC. Profile and region come from the git-ignored `.env` file
at the repo root (`cp .env.example .env`, then edit); mise sources it and
exports `AWS_PROFILE` / `AWS_REGION`. Default region when `.env` is absent:
`us-east-1`.

---

## Step 1b — (IaC, one-time) Set up the remote S3 state backend (required)

**This step is mandatory. Do it before Step 2.** `tofu destroy` can only delete
what is in its state, and local state is git-ignored — it does not travel with
the repo. If you tear down a month later from a fresh clone (or a different
machine) without remote state, `tofu destroy` finds empty state and deletes
nothing, orphaning every user, group, and the account instance. Putting state in
S3 is what makes the "a month later, different computer" teardown work.

`backend.tf` is tracked (value-free), so the S3 backend is already active in the
config; `provision.py` / `mise run provision-plan` **fail closed (exit
non-zero)** until the account-specific `backend.hcl` exists. The bootstrap
writes `backend.hcl` for you — the bucket name is derived from your account id
(`kiro-tofu-state-<ACCOUNT_ID>`), so there is nothing to fill in and no tfvars
to edit (set `state_bucket_name` only to override the derived name).

```bash
# 1. Dry run — see what the bucket + lock table bootstrap would create.
mise run backend-bootstrap-plan      # creates nothing

# 2. Create the S3 bucket + DynamoDB lock table AND write backend.hcl.
mise run backend-bootstrap           # prompts to approve; writes iac/terraform/backend.hcl

# 3. Provision (mise runs `tofu init -backend-config=backend.hcl` for you).
mise run provision-plan              # dry run; or `mise run provision` to apply
```

Prefer manual control? Instead of letting the bootstrap write it, copy the
template and edit the two or three values by hand:

```bash
cp iac/terraform/backend.hcl.example iac/terraform/backend.hcl   # then edit
```

The bootstrap config keeps its **own local state** on purpose (chicken-and-egg:
it is what creates the bucket). Only the main config uses the S3 backend.

Verify:
- `iac/terraform/backend.hcl` exists (git-ignored; `backend.tf` is tracked and
  already present).
- `tofu init -backend-config=backend.hcl` reports the S3 backend is initialized.

---

## Step 2 — (IaC) Create the IdC account instance, users, groups, memberships

```bash
# 1. Set your counts/prefixes/tier (no task — one-time copy + edit).
cp iac/terraform/terraform.tfvars.example iac/terraform/terraform.tfvars

# 2. Dry run — tofu init + plan (1 instance + N users + M groups + memberships).
mise run provision-plan      # creates nothing

# 3. Apply — creates them (prompts to approve).
mise run provision
```

Both tasks run `tofu init -backend-config=backend.hcl` for you (S3 backend from
Step 1b) and **require** it — they fail closed if Step 1b was skipped.

Prefer raw tofu? The equivalent by hand:

```bash
cd iac/terraform
tofu init -backend-config=backend.hcl          # S3 backend from Step 1b
tofu plan      # review: 1 instance + N users + M groups + memberships
tofu apply     # creates them
```

What this creates:
- One IAM Identity Center **account instance** in this account.
- `user_count` users named `<user_prefix><NN>`.
- `group_count` groups named `<group_prefix><NN>`.
- Group memberships per `membership_strategy`.
- **No** permission sets and **no** account assignments — these identities can
  log into Kiro and nothing else.

`mise run provision` already exports the manifest the scripts consume. To
re-export it by hand:
```bash
cd iac/terraform
tofu output -json provisioning_manifest > ../output/manifest.json
```

Verify:
- `tofu output users` / `tofu output groups` list the expected names.
- Console → IAM Identity Center → Users / Groups shows them.

---

## Step 2b — (console, one-time) Make MFA optional for sign-in

By default the instance requires MFA **every time** users sign in and prompts
them to register a device. These Kiro-login-only users are not obligated to set
up MFA, so turn it off. Not settable from IaC (no provider resource / public
API for the MFA mode).

1. In **this account**, open **IAM Identity Center → Settings**.
2. **Authentication** tab → **Multi-factor authentication** → **Configure**.
3. Under **Prompt users for MFA**, choose **Never (disabled)**.
4. **Save changes.**

Verify:
- The Authentication tab shows MFA prompt = **Disabled**.
- A test user signs in with username + password only, no MFA prompt.

> In "Disabled" mode you cannot manage MFA devices for these users, which is
> fine here. If you later need MFA for some users, switch to "Context-aware"
> or "Always-on" instead.

---

## Step 3 — (console, one-time) Enable Kiro with IAM Identity Center

This provisions the Kiro profile + service-linked role. Not scriptable.

1. In **this account**, open the **Kiro** console (check you are in the right
   region — the one from Step 2).
2. Click **Onboard your team to Kiro** (or **Enable small teams**).
3. When asked for the identity source, choose **IAM Identity Center**. You may
   be prompted to verify the IdC configuration.
4. Click **Enable**. A Kiro profile is created.
5. Note the **Sign-in URL** shown (looks like
   `https://d-xxxxxxxxxx.awsapps.com/start`).

You normally don't need to record this: Step 5's `mise run credentials` derives
the same default URL from the manifest automatically. Only copy it down if your
org uses a **custom vanity subdomain** (`your-subdomain.awsapps.com/start`),
which the derivation can't know about — pass that one to the render task.

---

## Step 4 — Assign the Kiro tier to each group

Two paths. The console path is the reliable one.

### 4a — (script, best-effort, opt-in) Try the API

```bash
cd iac/scripts
python attempt_kiro_subscription.py --manifest ../output/manifest.json   # dry run
python attempt_kiro_subscription.py --manifest ../output/manifest.json --attempt --tier PRO
```

This is **fail-closed**: if the installed SDK exposes no subscription API (the
normal case), it prints the console steps and exits non-zero. Even on an
accepted call, verify in the console — an accepted API call is not proof of an
active plan.

### 4b — (console) The reliable path

1. Kiro console → **Users & Groups → Groups** tab → **Add group**.
2. Select each `<group_prefix><NN>` group.
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
2. Record them in a CSV (git-ignored) at `iac/output/otps.csv`:
   ```csv
   username,otp
   kiro-user-01,<otp>
   kiro-user-02,<otp>
   ```
3. **(task)** Render the credentials file:
   ```bash
   mise run credentials
   ```
   This reads `output/otps.csv` and writes `output/credentials.md`. The
   **sign-in URL is taken from the manifest automatically** — `tofu output`
   derives it from the identity store id (`https://<identity-store-id>.awsapps.com/start`),
   so there is nothing to paste by hand. The task fails fast with instructions
   if `output/otps.csv` is missing.

   Only if you configured a **custom vanity subdomain** in the IdC console does
   the default URL differ; pass it explicitly:
   ```bash
   mise run credentials -- --sign-in-url "https://your-subdomain.awsapps.com/start"
   ```

`output/credentials.md` is git-ignored. It lists each user's username, email
(if set; anonymous users show a dash), group(s), OTP, and the sign-in URL +
region.

> On "same default password": AWS does not allow an admin-chosen shared
> password. The closest supported option is a per-user OTP that the user must
> change on first sign-in. The tooling captures those OTPs; it cannot force one
> shared value.

---

## Step 6 — Distribute & verify sign-in

1. Share `output/credentials.md` securely; delete it after distribution.
2. A user signs in: Kiro → sign in with organization → **Sign in via IAM
   Identity Center** → enter the **Sign-in URL** + **region code** → username +
   OTP → set a new password → **Allow access**.
3. Confirm the Kiro subscription is visible/active inside Kiro.

---

## Teardown

Full teardown instructions — including how to do it **from a different machine
a month later** — live in [`TEARDOWN.md`](./TEARDOWN.md). Two paths:

- **Option B (standard):** remote S3 state + `tofu destroy`. The remote backend
  is set up as a **required** step at provision time (Step 1b: bootstrap bucket
  + `backend.hcl`), so state lives in S3 and `tofu destroy` works from any clone.

  ```bash
  mise run teardown-tofu    # tofu destroy: removes users, groups, memberships, and the account instance (prompts to confirm)
  ```

- **Option A (fallback):** a state-free discovery script for when no state is
  available (fresh clone, local state gone).

  ```bash
  mise run teardown-plan    # dry run: discover what would be deleted
  mise run teardown-run     # delete IdC users/groups/memberships + instance (prompts to confirm)
  ```

Caveats (detailed in `TEARDOWN.md`):
- Remote S3 state (Option B, set up in Step 1b) is what makes `tofu destroy`
  work from any machine. If you ever ran without it, a local backend holds state
  only on the machine that created it and deletes nothing on a fresh clone — use
  Option A (the state-free script) to recover that case.
- **Deactivate Kiro subscriptions first** in the Kiro console. Per Kiro docs,
  when you remove access "at end of month" the Kiro-created Identity Center
  application assignment is **not** auto-removed and needs a manual cleanup step
  in IdC.
- Deleting the account instance is destructive and (per Step 0) the enablement
  of account instances org-wide cannot be reversed.
- Delete any local `output/credentials.md` and `output/otps.csv`.

---

## Quick reference — what is / isn't automated

| Step | Automated here? | Why |
| ---- | --------------- | --- |
| Permit member account instances | ❌ (mgmt account console) | Org-level, irreversible toggle |
| Create IdC account instance | ✅ (IaC, `awscc_sso_instance`) | — |
| Create users / groups / memberships | ✅ (IaC) | — |
| Make MFA optional (prompt = Never) | ❌ (console) | No provider resource / public API for MFA mode |
| Enable Kiro + Kiro profile | ❌ (console) | Provisions service-linked role; no stable API |
| Assign tier to group | ⚠️ best-effort script, else console | `q:CreateAssignment` is internal/undocumented |
| Set/share password | ❌ (console OTP) | IdC has no password API |
| Render credentials.md | ✅ (script) | — |
| Teardown users/groups/instance | ✅ (`tofu destroy`, or `teardown.py`) | Uses required remote state (Step 1b); state-free script is the fallback |
| Deactivate Kiro subscription + app assignment | ❌ (console) | No stable API; not auto-removed |
