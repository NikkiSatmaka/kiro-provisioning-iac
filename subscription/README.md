# Subscription (step 5 of the flow) — create the Kiro IdC users, groups, and subscriptions

> Phase link: this is **Step 5** of the root [`README.md`](../README.md) flow.
> Prerequisites: Step 1 backend, Step 2 foundation (and, in organization mode,
> Steps 3–4 governance) · Next: Step 6 claim-service
> ([`../claim-service/README.md`](../claim-service/README.md)) — or hand the
> credentials file out directly (see Step 7 of How to run below).

> ⚠️ **Nothing here runs automatically.** Every step is manual or driven by an
> explicit task you invoke. Where AWS stops exposing an API, the tooling stops
> and hands you a precise console checklist instead.

## What it is

This stack provisions **Kiro enterprise subscriptions** for a workshop's users.
It uses an **IAM Identity Center (IdC)** instance — the AWS identity source the
`foundation/` step adopted — as the place those identities live. The users it
creates are meant for **Kiro login only**: by default they get **zero AWS
console access**.

For a given set of workshop accounts and group/user counts, applying this stack
creates:

1. **IdC users**, workshop-namespaced `<workshop_id>-<acct_last4>-<group>-<NN>`.
2. **IdC groups**, with workshop-namespaced display names `<workshop_id>-<group>`
   so many workshops coexist in the one shared directory.
3. **Group memberships** — each user placed in its own group.
4. **(Optional, gated) account access** — when `enable_account_access = true`, a
   single shared permission set and one account assignment per group, binding
   each group to its owning member account id. **Off by default**, so users get
   zero console access.

The remaining pieces of a working subscription — enabling Kiro, assigning a
tier to each group, and setting passwords — are **console-only** on AWS's side
(see "The console-only AWS limits" below). The stack takes you right up to those
lines and then hands you a guided manual step.

### Where the identities live

Identities are created in whichever IdC instance `foundation/` adopts (reads)
and hands forward via `idc_instance_arn` / `identity_store_id`. This stack
**consumes** that instance; it never creates or destroys it. Because many
workshops' users and groups coexist in that one shared directory, names are
workshop-namespaced: usernames carry the `workshop_id` prefix (plus the owning
account's last four digits), and group display names are prefixed
`"<workshop_id>-"` so two workshops can reuse a plain group name (e.g. `team-a`)
without colliding.

The `workshop_accounts` map's account ids are **billing/attribution metadata
only** — they identify which member account a group is attributed to, and are
the assignment target used **only** when `enable_account_access` is `true`. With
the flag `false` (the default) they grant no console access whatsoever.

### Dual-mode: organization vs account instance

This stack is **dual-mode** via the `instance_mode` variable (default
`organization`). It writes to one of two kinds of IdC instance:

| | `organization` (default) | `account` |
| --- | --- | --- |
| Instance | management account's org instance | child account's own account instance |
| `AWS_PROFILE` | management-account profile | **child account's** profile |
| `enable_account_access` | may be `true` or `false` | **must be `false`** |
| Account assignments | available | **not supported** (a plan-time precondition fails if attempted) |
| `foundation` adopts | the org instance | the child's account instance (run foundation under the child profile) |
| `workshop_accounts` shape | identical | identical (account-id key is naming metadata only) |

**Cautions:**

- **Wrong profile silently targets the org instance.** If you run with a
  **management-account** profile while intending account mode, foundation and
  subscription silently resolve and write to the **organization** instance.
  Double-check `AWS_PROFILE` points at the child account before applying.
- **Kiro web-feature caveat.** AWS supports Kiro on account instances **unless**
  users need the full set of Kiro features on AWS websites. For login-only
  workshops the impact is minimal; verify against a real child-account instance
  before a production workshop.
- **governance / governance-shared are management-only** and are **not**
  dual-mode. Account mode provisions users/groups/memberships only — there is no
  OU, SCP, or budget governance in a child account.

### The console-only AWS limits

These are hard AWS platform limits, not gaps in this repo. The tooling automates
everything up to each line and then hands you a precise manual step (listed in
"How to run" below).

- **Making MFA optional.** By default an IdC instance prompts users for MFA
  every time they sign in and enforces device registration. For login-only
  users you turn that off with one console setting. The MFA mode is not exposed
  by the Terraform AWS provider or any public boto3 call, so it cannot be set
  from IaC. It is instance-wide: the organization instance is shared by every
  workshop, so change it once, deliberately.
- **Enabling Kiro + assigning a tier to a group.** Kiro enterprise onboarding
  ("Onboard your team to Kiro" / "Enable small teams") provisions a Kiro profile
  and service-linked role, and the tier assignment ("Add group" → pick Pro /
  Pro+ / Pro Max / Power) is driven through the Kiro console. The underlying API
  (`q:CreateAssignment`) is internal, undocumented, and unreliable outside the
  console. The Python tooling offers a best-effort scripted attempt behind an
  explicit `--attempt` flag, but it fails closed and tells you to use the
  console rather than pretend it worked.
- **Setting or sharing passwords.** IAM Identity Center has no public API to
  set, reset, or share a user password; `CreateUser` neither sets a password nor
  sends an invitation email. An admin-chosen shared password is therefore **not
  achievable**. The supported path is a per-user one-time password (OTP) that
  the user must change on first sign-in — generated per user in the console and
  pasted back into the tooling, which renders the credentials file.

Sources (rephrased for compliance with licensing restrictions):
[IAM Identity Center organization vs account instances](https://docs.aws.amazon.com/singlesignon/latest/userguide/identity-center-instances.html),
[Prompt users for MFA](https://docs.aws.amazon.com/singlesignon/latest/userguide/how-to-disable-mfa.html),
[Kiro deployment options](https://kiro.dev/docs/enterprise/deployment-options/),
[Enable Kiro with IdC](https://repost.aws/articles/AR3YUupHzQQ2mqMzL5Y8KvbQ).

## Prerequisites

Before you run this step, these must be true:

1. **Phase 0 toolchain + AWS auth done** (root [`README.md`](../README.md)) —
   `mise run verify` resolves the **intended** account: the management account
   in organization mode, or the **child** account in account mode. `AWS_PROFILE`
   must match the chosen mode (a management-account profile silently targets the
   organization instance even when you meant account mode).
2. **Step 1 backend done** — the shared S3 remote-state bucket + lock table
   exist and `mise run backend-bootstrap` has written
   `subscription/terraform/backend.hcl`. Remote state is **required** for this
   stack: `tofu destroy` can only remove what is in its state, so without S3
   state a teardown from a fresh clone later would orphan every user and group.
   The `subscription-plan` / `subscription-apply` tasks run
   `tofu init -backend-config=backend.hcl` and **fail closed** if it is missing.
   See [`../backend/README.md`](../backend/README.md).
3. **Step 2 foundation done** — foundation adopted the IdC instance and printed
   its two IDs; export them as `TF_VAR_idc_instance_arn` /
   `TF_VAR_identity_store_id` so this stack can consume them
   ([`../foundation/README.md`](../foundation/README.md)).
4. **IAM Identity Center enabled in the target account** — a one-time console
   action (the management account in organization mode, or the child account in
   account mode). If it is not enabled, there is no instance to write identities
   into. Exactly one organization instance exists per management account; a
   child account exposes exactly one account instance.
5. **`terraform/terraform.tfvars` filled in** — copy
   `terraform/terraform.tfvars.example` and set your accounts, groups, user
   counts, `instance_mode`, `enable_account_access`, and Kiro tier.

## How to run

Follow these in order. Steps that AWS only exposes through the web console are
marked **(console)**; the rest are tasks you invoke.

1. **Dry run — review what will be created.** Reports the planned users, groups,
   and memberships and changes nothing.

   ```bash
   mise run subscription-plan
   ```

2. **Apply — create the users, groups, and memberships.** Prompts to approve,
   then creates them in the adopted instance and exports the manifest the
   scripts consume. Expect `tofu output users` / `tofu output groups` to list
   the namespaced names, and the console (IAM Identity Center → Users / Groups)
   to show them.

   ```bash
   mise run subscription-apply
   ```

   > With `enable_account_access = false` (the default) no permission sets or
   > account assignments are created — these identities can log into Kiro and
   > nothing else. To grant console access later, set
   > `enable_account_access = true` in tfvars and re-apply.

3. **(console, one-time) Make MFA optional.** IAM Identity Center → Settings →
   Authentication → Multi-factor authentication → Configure → **Prompt users for
   MFA → "Never (disabled)"** → Save. Confirm the tab shows MFA = Disabled and a
   test user signs in with username + password only.

4. **(console, one-time) Enable Kiro with IAM Identity Center.** Open the Kiro
   console (same region as Step 2) → **Onboard your team to Kiro** → choose
   **IAM Identity Center** as the identity source → **Enable**. A Kiro profile
   is created. You do not need to copy the sign-in URL — step 6 derives it from
   the manifest.

5. **(console) Assign the Kiro tier to each group.** Kiro console → **Users &
   Groups → Groups → Add group** → select each `<workshop_id>-<group>` group →
   choose the tier (Pro / Pro+ / Pro Max / Power) → confirm. Confirm each group
   shows its plan active. (A best-effort scripted attempt exists via
   `subscription/scripts/attempt_kiro_subscription.py --attempt`, but it fails
   closed and points you back here.)

6. **(console + task) Passwords and the credentials file.** For each user, in
   IAM Identity Center → Users → **Reset password → Generate a one-time password
   → copy it**. Record them in a git-ignored CSV at `subscription/output/otps.csv`:

   ```csv
   username,otp
   <workshop_id>-<acct_last4>-<group>-01,<otp>
   <workshop_id>-<acct_last4>-<group>-02,<otp>
   ```

   Then render the credentials Markdown. The task reads `output/otps.csv`,
   derives the sign-in URL from the manifest, and writes the git-ignored
   `output/credentials.md`:

   ```bash
   mise run subscription-credentials
   ```

   To re-render from an existing manifest later (for example after editing the
   OTP CSV), use `mise run subscription-render`.

7. **Distribute and verify sign-in.** Pick one:
   - **Direct:** share `output/credentials.md` securely, then delete it after
     distribution.
   - **Self-serve claim service (optional):** deploy Step 6
     ([`../claim-service/README.md`](../claim-service/README.md)) so
     participants claim their own credential from a QR code / short link. It
     seeds from the `output/otps.csv` + `output/manifest.json` you just produced,
     so run it only **after** this step.

   However it was distributed, a user signs in: Kiro → sign in with organization
   → **Sign in via IAM Identity Center** → enter the sign-in URL + region →
   username + OTP → set a new password → **Allow access**, then confirm the Kiro
   subscription is active inside Kiro.

### Reusability

Nothing is hard-coded to one workshop. Region and `AWS_PROFILE` come from the
git-ignored `.env` (root README, Phase 0); the account/group/user topology, the
`instance_mode`, the `enable_account_access` gate, and the Kiro tier live in
`terraform/terraform.tfvars` (copy `terraform.tfvars.example`). This stack
stores its OpenTofu state at `workshops/<id>/subscription/terraform.tfstate` in
the shared S3 bucket from Step 1; generated credential files land in
`subscription/output/` and are git-ignored.

## Teardown

See the root [`TEARDOWN.md`](../TEARDOWN.md) for how to remove this stack.
