# Kiro Subscription Provisioning (dual-mode: organization or account IdC)

This is **Phase 3** of the root README journey.

- **Prerequisites:** Phase 2 foundation adopt done and its two IDs wired forward
  ([`../foundation/README.md`](../foundation/README.md)) — this stack consumes
  `idc_instance_arn` / `identity_store_id`.
- **Next:** Phase 4 — Distribute ([`../claim-service/README.md`](../claim-service/README.md)),
  or the direct-handout path ([`RUNBOOK.md`](./RUNBOOK.md) Step 6).

Infrastructure-as-Code (**OpenTofu**) + Python tooling to provision **Kiro
enterprise subscriptions** for a workshop's users, using an **IAM Identity
Center** instance as the identity source. The stack is **dual-mode** via
`instance_mode`:

- **`organization`** (default) — the AWS Organizations **management account**'s
  **organization instance** (today's behavior; per-group account assignments
  available when `enable_account_access = true`).
- **`account`** — a **child/member account**'s **own IdC account instance**.
  Only users, groups, and memberships are created; account instances do **not**
  support permission sets or account assignments, so `enable_account_access`
  **must** be `false` (a plan-time precondition enforces this). See
  [Dual-mode: organization vs account instance](#dual-mode-organization-vs-account-instance).

The identity users this creates are, by default, intended for **Kiro login
only** — they are granted **zero AWS console access**. No permission sets and no
account assignments exist unless you deliberately flip `enable_account_access`
to `true`.

> ⚠️ **Nothing here runs automatically.** Every step is manual or driven by an
> explicit entrypoint you invoke. [`RUNBOOK.md`](./RUNBOOK.md) is the
> end-to-end run order, including the steps AWS only exposes through the console.

**Scope of this doc.** This README explains the subscription stack itself — what
it provisions, where the identities live, the AWS platform limits, and the
reusability knobs. For the overall repo journey (toolchain setup, the shared
state backend, and distributing the result), start at the
[root `README.md`](../README.md). To run the subscription steps in order, use
[`RUNBOOK.md`](./RUNBOOK.md); to tear it down, [`TEARDOWN.md`](./TEARDOWN.md).

---

## What this provisions

For a given set of workshop accounts and group/user counts:

1. **IdC users** in the adopted instance (org instance in organization mode, or
   the child's account instance in account mode), named
   `<workshop_id>-<acct_last4>-<group>-<NN>` (workshop-namespaced).
2. **IdC groups**, with workshop-namespaced display names
   `<workshop_id>-<group>` so many workshops coexist in the one shared directory.
3. **Group memberships** — each user placed in its own group.
4. **(Optional, gated) account access** — when `enable_account_access = true`, a
   single shared permission set and one account assignment per group, binding
   each group to its owning member account id. **Off by default**, so users get
   zero console access.
5. **A Kiro subscription per group** — see the big caveat below; this is the one
   step AWS does not expose as a stable, scriptable API.
6. **Passwords** — a one-time-password (OTP) workflow per user; IdC does **not**
   support an admin-set shared password via API (see caveat).
7. **A credentials Markdown file** capturing each user's sign-in URL, username,
   and password/OTP.

What happens to that credentials file afterwards — handing it out directly or
feeding it to the claim service — is **out of scope here**; that is the
distribution phase, owned by the root README and `../claim-service/`.

---

## Where the identities live

Identities are created in whichever IdC instance `foundation/` adopts (reads)
and hands forward via `idc_instance_arn` / `identity_store_id`. In the default
`organization` mode that is the management account's single **organization**
instance; in `account` mode it is the child account's own **account** instance.
This stack consumes that instance; it never creates or destroys it.

Because **many workshops' users and groups coexist in this one shared
directory**, names are workshop-namespaced:

- Usernames carry the `workshop_id` prefix (and the owning account's last four
  digits).
- Group **display names** are prefixed `"<workshop_id>-"` so two workshops can
  reuse a plain group name (e.g. `team-a`) without colliding.

The `workshop_accounts` map's account ids are **billing/attribution metadata
only** — they identify which member account a group is attributed to and are the
assignment target used **only** when `enable_account_access` is `true`. With the
flag `false` (the default) they grant no console access whatsoever.

**Preconditions and limits:**

- IAM Identity Center must be **enabled in the target account first** (a
  one-time console action; see [`RUNBOOK.md`](./RUNBOOK.md) step 0) — the
  management account in organization mode, or the child account in account mode.
  If it is not, there is no instance to write identities into.
- Exactly one organization instance exists per management account; a child
  account exposes exactly one account instance.
- Kiro subscriptions are supported on both instance types (account instances
  carry one documented caveat — see the dual-mode section below).

Sources (rephrased for compliance with licensing restrictions):
[IAM Identity Center organization vs account instances](https://docs.aws.amazon.com/singlesignon/latest/userguide/identity-center-instances.html),
[Kiro deployment options](https://kiro.dev/docs/enterprise/deployment-options/),
[Enable Kiro with IdC](https://repost.aws/articles/AR3YUupHzQQ2mqMzL5Y8KvbQ).

---

## Dual-mode: organization vs account instance

Set `instance_mode` (variable, default `organization`) to choose where this
stack writes:

| | `organization` (default) | `account` |
| --- | --- | --- |
| Instance | management account's org instance | child account's own account instance |
| `AWS_PROFILE` | management-account profile | **child account's** profile |
| `enable_account_access` | may be `true` or `false` | **must be `false`** |
| Account assignments | available | **not supported** (precondition fails the plan if attempted) |
| `foundation` adopts | the org instance | the child's account instance (run foundation under the child profile) |
| `workshop_accounts` shape | identical | identical (account-id key is naming metadata only) |

Account-mode operator checklist:

1. **Enable IAM Identity Center in the child account first** — this creates its
   account instance (the per-account equivalent of the org-mode Step 0).
2. Run `foundation` and `subscription` with the **child account's**
   `AWS_PROFILE`, and point `idc_instance_arn` / `identity_store_id` at the
   child's instance (foundation resolves them).
3. Keep `instance_mode = "account"` and `enable_account_access = false`.

**Cautions:**

- **R-2 (wrong profile silently targets the org instance).** If you run with a
  **management-account** profile while intending account mode, foundation and
  subscription silently resolve and write to the **organization** instance.
  Double-check `AWS_PROFILE` points at the child account before applying.
- **OQ-1 (Kiro web-feature caveat).** AWS supports Kiro on account instances
  **unless** users need the full set of Kiro features on AWS websites. For
  login-only workshops the impact is minimal; verify against a real
  child-account account instance before a production workshop.
- **governance / governance-shared are management-only** and are **not**
  dual-mode. Account mode provisions users/groups/memberships only — there is no
  OU, SCP, or budget governance in a child account.

---

## ⚠️ The things AWS does NOT let you fully automate

These are hard platform limits, not gaps in this repo. The tooling automates
everything up to these lines and then hands you a precise, guided manual step.
Each maps to a step in [`RUNBOOK.md`](./RUNBOOK.md).

### 0. Making MFA optional (not required) for sign-in

By **default** an Identity Center instance prompts users for MFA **every time
they sign in** (always-on), and enforces MFA device registration. For these
Kiro-login-only users you do **not** want that friction.

The fix is one console setting: **Settings → Authentication → Multi-factor
authentication → Configure → Prompt users for MFA → "Never (disabled)"**. In
that mode users sign in with username + password only.

This MFA mode is **not exposed** by the `aws` Terraform provider nor by a public
boto3 operation (the `sso-admin` SDK has no set-MFA-mode call), so it cannot be
set from IaC. It is a one-time console step per instance —
see [`RUNBOOK.md`](./RUNBOOK.md) step 2b.

Source (rephrased for compliance):
[Prompt users for MFA](https://docs.aws.amazon.com/singlesignon/latest/userguide/how-to-disable-mfa.html).

### 1. Enabling Kiro + assigning a subscription tier to a group

The Kiro enterprise onboarding ("Onboard your team to Kiro" / "Enable small
teams") provisions a Kiro profile and service-linked role, and the
tier-assignment ("Add group" → pick Pro / Pro+ / Pro Max / Power) is driven
through the **Kiro console**. The underlying API (`q:CreateAssignment`) is
internal, undocumented, and has a track record of `UnknownError` responses when
called outside the console flow.

- The Python tooling provides a **best-effort** scripted attempt behind an
  explicit `--attempt` flag, but it will **fail closed and tell you to use the
  console** rather than pretend it worked.
- The reliable path is the console checklist in [`RUNBOOK.md`](./RUNBOOK.md).

### 2. Setting a shared/default password or resetting passwords via API

IAM Identity Center has **no public API** to set, reset, or share a user
password. `CreateUser` neither sets a password nor sends the invitation email.
AWS only exposes this through the console per user:

- **"Generate a one-time password"** (admin reads it out — this is the
  closest thing to "same default password" you can get, but each OTP is unique
  and must be changed on first login), **or**
- **"Send an email with password-setup instructions"** (requires real,
  reachable email addresses).

So the "reset each user to the same default password" requirement is **not
achievable** as literally stated — AWS does not permit an admin-chosen shared
password. The tooling instead supports the realistic workflow:

- Create users via API (fast, repeatable).
- Generate a one-time password per user in the console.
- Paste the OTPs back into the tooling (or a CSV), and it renders the
  credentials Markdown.

See [`RUNBOOK.md`](./RUNBOOK.md) for the exact clicks and the paste-back format.

---

## Repo layout

```
subscription/
├── README.md                 ← you are here
├── RUNBOOK.md                ← end-to-end run order + the console-only steps
├── TEARDOWN.md               ← cleanup: remote-state destroy (B) + fallback script (A)
├── terraform/                ← OpenTofu config (reusable via variables)
│   ├── versions.tf           ← required providers + backend notes
│   ├── providers.tf          ← AWS provider (dual-mode: management or child account profile/region)
│   ├── variables.tf          ← idc inputs, workshop_id, workshop_accounts, enable_account_access, tier
│   ├── locals.tf             ← user/group name generation (workshop-namespaced)
│   ├── identity_center.tf    ← users + groups + memberships (+ gated permission set / assignments)
│   ├── outputs.tf            ← instance ARN, identity store id, names/ids, URLs, manifest
│   ├── backend.tf            ← tracked, value-free S3 backend block (partial config)
│   ├── backend.hcl.example   ← template for manual backend.hcl (normally auto-written by backend-bootstrap)
│   └── terraform.tfvars.example
├── scripts/
│   ├── provision_passwords_and_output.py  ← OTP workflow + credentials MD writer
│   ├── attempt_kiro_subscription.py       ← best-effort, fail-closed tier assign
│   ├── teardown.py                        ← state-free IdC teardown (Option A fallback)
│   └── requirements.txt                   ← (uses project boto3; listed for clarity)
├── config/
│   └── settings.example.env               ← non-secret run settings
└── output/
    ├── .gitkeep
    └── credentials.template.md            ← shape of the generated MD
```

This stack stores its OpenTofu state
(`workshops/<id>/subscription/terraform.tfstate`) in the shared S3 bucket
created by the sibling `../backend/` stack. That bucket is a **prerequisite**,
set up once — see [`../backend/README.md`](../backend/README.md) and
[`RUNBOOK.md`](./RUNBOOK.md) step 1b. Generated credential files land in
`subscription/output/` and are **git-ignored**.

---

## Reusability

Nothing is hard-coded to one workshop. Everything that changes between projects
is a variable:

| Knob | Where | Example |
| ---- | ----- | ------- |
| AWS region | `.env` (git-ignored; `AWS_REGION`) | `us-east-1` (default) → any Kiro-supported region |
| Instance mode | `variables.tf` `instance_mode` | `organization` (default) or `account` |
| AWS profile (management or child account) | `.env` (git-ignored; `AWS_PROFILE`) | `kiro-mgmt` (org) / child profile (account) |
| Workshop namespace | `WORKSHOP_ID` / tfvars `workshop_id` | `kiro-2025-10-10` |
| Accounts, groups, user counts | `variables.tf` `workshop_accounts` | `{ "1111…" = { groups = { team-a = { user_count = 10 } } } }` |
| Account access gate | `variables.tf` `enable_account_access` | `false` (default) → zero console access |
| Kiro tier | `variables.tf` + script | `PRO`, `PRO_PLUS`, `PRO_MAX`, `POWER` |

Region and profile come from the git-ignored `.env` at the repo root (set up in
the root README's Phase 0; `AWS_PROFILE` must be a management-account profile in
organization mode, or the child account's profile in account mode); the
account/group/user topology, the instance mode, the access gate, and the Kiro
tier live in `terraform/terraform.tfvars` (copy `terraform.tfvars.example`).

---

## Running it

The step-by-step order — the IdC-enablement prerequisite (management account in
organization mode, child account in account mode), provisioning, the
console-only Kiro steps, and rendering the credentials file — lives in
[`RUNBOOK.md`](./RUNBOOK.md). Teardown lives in [`TEARDOWN.md`](./TEARDOWN.md).
