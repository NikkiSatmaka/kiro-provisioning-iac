# Kiro Subscription Provisioning (IAM Identity Center — account instance)

Reusable Infrastructure-as-Code (**OpenTofu**) + Python tooling to provision
**Kiro subscriptions for a team** in a single AWS account, using an
**IAM Identity Center _account instance_** as the identity source.

The identity users this creates are intended for **Kiro login only** — they are
not granted any AWS account access (no permission sets, no account assignments).

> ⚠️ **Nothing here runs automatically.** Every step is manual or driven by an
> explicit entrypoint you invoke. Read [`RUNBOOK.md`](./RUNBOOK.md) for the
> end-to-end run order and the steps that AWS only exposes through the console.

---

## What this provisions

For a given account, region, and a requested count `N`:

1. **An IAM Identity Center _account instance_** in the target (child) account.
2. **`N` IdC users**, named `<user_prefix><NN>` (zero-padded sequence).
3. **`M` IdC groups**, named `<group_prefix><NN>` (zero-padded sequence).
4. **Group memberships** — users distributed across the groups (round-robin, or
   all-in-one, configurable).
5. **A Kiro subscription per group** — see the big caveat below; this is the one
   step AWS does not expose as a stable, scriptable API.
6. **Passwords** — a one-time-password (OTP) workflow per user; IdC does **not**
   support an admin-set shared password via API (see caveat).
7. **A credentials Markdown file** capturing each user's sign-in URL, username,
   and password/OTP for distribution.

---

## Why an _account_ instance (not the org instance)

This account (`<TARGET_ACCOUNT_ID>` — the child/member account you are
provisioning into) is a **member** of an AWS
Organization whose **management account already has an _organization_ instance**
of Identity Center. You asked for IdC set up **in this child account**.

AWS allows exactly that: a member account can create its own **account
instance** of Identity Center (one per account per region), isolated to that
single account. This is the correct choice when:

- You want the identities scoped to this one account only (Kiro login, nothing
  else).
- You do **not** want to touch the org-wide instance in the management account.

**Preconditions and limits (verified against AWS docs):**

- The **org management account must have _permitted member-account instance
  creation_** — a one-time, irreversible org-level toggle. If it has not, the
  `CreateInstance` call from this child account is denied. This repo **cannot**
  flip that toggle for you (it lives in the management account). See
  [`RUNBOOK.md`](./RUNBOOK.md) step 0.
- One account instance per account per region.
- Account instances support **fewer features** than org instances, but **Kiro
  subscriptions are supported** on account instances.
- An account instance **cannot be upgraded** to an org instance later — it would
  have to be deleted and recreated.

Sources (rephrased for compliance with licensing restrictions):
[Account instances of IAM Identity Center](https://docs.aws.amazon.com/singlesignon/latest/userguide/account-instances-identity-center.html),
[Permit account instance creation](https://docs.aws.amazon.com/singlesignon/latest/userguide/enable-account-instance-console.html),
[Kiro deployment options](https://kiro.dev/docs/enterprise/deployment-options/),
[Enable Kiro with IdC](https://repost.aws/articles/AR3YUupHzQQ2mqMzL5Y8KvbQ).

---

## ⚠️ The things AWS does NOT let you fully automate

These are hard platform limits, not gaps in this repo. The tooling automates
everything up to these lines and then hands you a precise, guided manual step.

### 0. Making MFA optional (not required) for sign-in

By **default** an Identity Center instance prompts users for MFA **every time
they sign in** (always-on), and enforces MFA device registration. For these
Kiro-login-only users you do **not** want that friction.

The fix is one console setting: **Settings → Authentication → Multi-factor
authentication → Configure → Prompt users for MFA → "Never (disabled)"**. In
that mode users sign in with username + password only.

This MFA mode is **not exposed** by the `aws` or `awscc` Terraform providers,
nor by a public boto3 operation (the `sso-admin` SDK has no set-MFA-mode call),
so it cannot be set from IaC. It is a one-time console step per instance —
see [`RUNBOOK.md`](./RUNBOOK.md) step 2b.

Source (rephrased for compliance):
[Prompt users for MFA](https://docs.aws.amazon.com/singlesignon/latest/userguide/how-to-disable-mfa.html).

### 1. Enabling Kiro + assigning a subscription tier to a group

The Kiro team onboarding ("Onboard your team to Kiro" / "Enable small
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
iac/
├── README.md                 ← you are here
├── RUNBOOK.md                ← end-to-end run order + the console-only steps
├── TEARDOWN.md               ← cleanup: remote-state destroy (B) + fallback script (A)
├── terraform/                ← OpenTofu config (reusable via variables)
│   ├── versions.tf           ← required providers + backend notes
│   ├── providers.tf          ← AWS provider wired to the project profile/region
│   ├── variables.tf          ← prefixes, counts, tier, membership strategy, …
│   ├── locals.tf             ← name generation (prefix + zero-padded sequence)
│   ├── identity_center.tf    ← account instance + users + groups + memberships
│   ├── outputs.tf            ← instance ARN, identity store id, names/ids, URLs
│   ├── backend.tf.example    ← rename to backend.tf to use remote S3 state (Option B)
│   ├── backend.hcl.example   ← copy to backend.hcl with your bucket/table names
│   ├── backend-bootstrap/    ← one-time: creates the S3 state bucket + lock table
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

Generated credential files land in `iac/output/` and are **git-ignored**.

---

## Reusability

Nothing is hard-coded to one account or one count. Everything that changes
between projects is a variable:

| Knob | Where | Example |
| ---- | ----- | ------- |
| AWS region | `.env` (git-ignored; `AWS_REGION`) | `ap-southeast-1` → `us-east-1` |
| AWS profile | `.env` (git-ignored; `AWS_PROFILE`) | `kiro-provisioning` |
| User prefix + count | `variables.tf` | `kiro-user-` × 25 |
| Group prefix + count | `variables.tf` | `kiro-team-` × 1 |
| Sequence padding | `variables.tf` | `2` → `01`, `02`, … |
| Membership strategy | `variables.tf` | `all_in_first` / `round_robin` |
| Kiro tier | `variables.tf` + script | `PRO`, `PRO_PLUS`, `PRO_MAX`, `POWER` |

Point it at a different account/region by editing one git-ignored file, `.env`
(see below). No code edits required.

### The `.env` file — one place for per-run settings

All per-run / per-account values live in a single git-ignored `.env` at the repo
root. mise sources it and exports the variables to the AWS CLI, the SDKs,
OpenTofu, and the scripts.

```bash
cp .env.example .env    # then edit .env
```

```dotenv
# .env
AWS_PROFILE=kiro-provisioning
AWS_REGION=us-east-1          # change region here — nothing else to touch
```

mise exports these (and derives `AWS_DEFAULT_REGION` from `AWS_REGION`). OpenTofu's
`aws_region` variable defaults to empty and inherits `AWS_REGION`; the scripts
read `AWS_REGION` (or `--region`). When `.env` is absent, mise falls back to the
defaults in `mise.toml` (`kiro-provisioning` / `ap-southeast-1`).

---

## Run order (summary — full detail in RUNBOOK.md)

1. **(Management account, one-time)** Permit member-account IdC instances.
2. **(This repo)** `tofu init && tofu plan && tofu apply` — creates the account
   instance, users, groups, memberships.
3. **(Console, one-time)** Set MFA prompt to **Never (disabled)** so users are
   not obligated to set up MFA.
4. **(Console, one-time)** Enable Kiro with IAM Identity Center as the identity
   source; note the sign-in URL.
5. **(Console)** Assign the Kiro tier to each group.
6. **(Console + script)** Generate a one-time password per user; paste back and
   run the output script to produce `output/credentials.md`.
7. Distribute credentials. Users sign in to Kiro via the IdC sign-in URL.

To remove everything later — including from a different machine a month on — see
[`TEARDOWN.md`](./TEARDOWN.md). Set up the remote S3 state backend (Option B) at
provision time so `tofu destroy` works from any clone; a state-free discovery
script (Option A) is the fallback.
