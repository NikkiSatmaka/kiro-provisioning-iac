# kiro-provisioning-iac

## Overview

This repository is reusable Infrastructure-as-Code (**OpenTofu**) and Python
tooling that provisions **Kiro enterprise subscriptions** for a team, using
**AWS IAM Identity Center** as the identity source. In plain terms: it creates
the login accounts your participants use to sign in to Kiro, then walks you
through the handful of steps AWS only exposes in the console.

The identities it creates are meant for **Kiro login only** — by default they
get no AWS console access.

> ⚠️ **Nothing here runs automatically.** Every step is something you invoke on
> purpose. Where AWS stops exposing an API, the tooling stops and hands you a
> precise console checklist instead.

This README is the **starting point**. It carries the one-time setup (Phase 0)
itself, then links out to one document per step. Read it top to bottom, then
follow each step's linked document in order.

> **Running more than one workshop?** This repo stack provisions **one
> workshop per directory**. To run another workshop, use a **separate directory**
> (clone again or unzip elsewhere). And when several workshops **share one AWS
> account**, only the first directory bootstraps the shared backend (Step 1);
> every later directory **copies** the backend wiring (`backend.hcl`) across by
> hand rather than bootstrapping again. Both rules are documented in
> [`MULTI-WORKSHOP.md`](./MULTI-WORKSHOP.md) — read it before setting up a
> second workshop.

## Organization vs account — which steps apply to you

Before you start, know which of two modes you are in. It decides whether the
governance steps (3 and 4) apply to you.

- **Organization mode** — you are running against the **AWS Organizations
  management account** (the account that owns AWS Organizations), using its
  **IAM Identity Center _organization instance_**. You run **every** step,
  including the governance steps.
- **Account mode** — you are running against a **child/member account**, using
  that account's **own IAM Identity Center account instance**. You **skip** the
  governance steps (3 and 4); they create AWS Organizations resources that only
  exist in the management account.

Which account your `AWS_PROFILE` points at (set in Phase 0) decides your mode.
The backend, foundation, subscription, and claim-service steps run the same in
both modes; only governance differs.

## Phase 0 — Set up (toolchain + AWS auth)

This phase is owned by no single stack, so it lives here. It installs the
toolchain, points it at your AWS account, and signs you in. Do it once before
Step 1.

You need [mise](https://mise.jdx.dev/) to manage the toolchain and run the
tasks. It installs the pinned tools — Python 3.12, OpenTofu 1.13, the AWS CLI,
uv — and creates the Python `.venv`.

Run these in order:

1. **`mise install`** — install the pinned toolchain and create the Python
   `.venv`.
2. **`mise run setup`** — sync the Python dependencies into `.venv`.
3. **`cp .env.example .env`** — then edit the git-ignored `.env`: set
   `AWS_PROFILE` and `AWS_REGION` for your target account. If you will use the
   optional claim service (Step 6), also set `WORKSHOP_CODE`.
4. **`mise run aws-login`** — sign in to AWS. A browser opens for console
   sign-in; the short-term credentials are cached in the project-local
   `.aws/login-cache`, not your global `~/.aws`. On a headless host, run
   `aws login --remote` instead. Re-run this when the session expires.
5. **`mise run verify`** — confirm AWS auth resolves to the account you intend
   (it runs `aws sts get-caller-identity`).

When `mise run verify` prints the expected account, Phase 0 is done. Continue to
Step 1.

## The ordered flow (0 → 6)

Follow these steps in order. Each stack row links to that stack's document,
which tells you what the stack is and how to run it — the run commands live
there, not here.

| Step | What you do | Mode | Document |
| ---- | ----------- | ---- | -------- |
| **0. Set up** | Install the toolchain, configure `.env`, sign in to AWS | both | [Phase 0 above](#phase-0--set-up-toolchain--aws-auth) |
| **1. Backend** | Prepare the shared S3 remote-state backend for the account in use | both | [`backend/README.md`](./backend/README.md) |
| **2. Foundation** | Adopt (read) the IAM Identity Center instance the account exposes | both | [`foundation/README.md`](./foundation/README.md) |

> **Do the governance steps apply to me?** Ask: **am I running against the AWS
> Organizations management account?**
> - **Yes — organization mode:** perform Step 3 and Step 4.
> - **No — a child/member account (account mode):** **skip** Step 3 and Step 4;
>   go straight to Step 5.
>
> Why: the governance steps create AWS Organizations resources that only exist
> in the management account. Each governance document (Steps 3 and 4) opens with
> this same check.

| Step | What you do | Mode | Document |
| ---- | ----------- | ---- | -------- |
| **3. Governance-shared** | Create the management-account singleton primitives (budgets role + Service Control Policy (SCP) objects — an SCP is an organization-wide permission boundary) | **organization only** | [`governance-shared/README.md`](./governance-shared/README.md) |
| **4. Governance** | Put a workshop's accounts under an organizational unit (OU — a folder in AWS Organizations that groups accounts) with the Kiro guardrail SCP + auto-freeze budgets | **organization only** | [`governance/README.md`](./governance/README.md) |
| **5. Subscription** | Create the IAM Identity Center (IdC — the AWS identity service holding users and the sign-in portal) users, groups, and memberships; do the console-only Kiro steps | both | [`subscription/README.md`](./subscription/README.md) |
| **6. Claim-service** | Optional: deploy the self-serve credential distribution service | both | [`claim-service/README.md`](./claim-service/README.md) |

> **Order-reconciliation note.** This flow runs the governance steps (3–4)
> **before** subscription (5). Earlier documentation ran subscription first and
> treated governance as an optional sidebar outside the linear flow. The order
> changed so a workshop's account guardrails exist **before** the identities
> that will use those accounts. If you followed the old README, note the
> reversal: governance now comes before subscription.

The steps chain. Step 2 adopts the IdC instance and emits its ARN + identity
store id, which Step 5 consumes. In organization mode, Step 3 creates the shared
primitives that Step 4 consumes. Step 5 produces the credential outputs that
Step 6 (if you use it) distributes.

## Teardown

When the engagement ends, remove everything in reverse order. The remote state
from Step 1 is what lets the teardown work from any machine.

> To remove everything, see [`TEARDOWN.md`](./TEARDOWN.md).

## Reference

### Repo layout

The repo is split into independent top-level stacks, each with its own OpenTofu
state:

```
.
├── README.md                 ← you are here (overview + the ordered flow)
├── MULTI-WORKSHOP.md         ← running >1 workshop: one dir per workshop + sharing an account
├── TEARDOWN.md               ← the single teardown document (reverse order)
├── mise.toml                 ← toolchain (python, opentofu, aws-cli, uv) + task runner
├── pyproject.toml / uv.lock  ← Python deps (boto3) managed by uv
├── .env.example              ← per-run settings template (AWS_PROFILE / AWS_REGION / WORKSHOP_CODE)
├── .aws/                     ← project-local AWS config/credentials (git-ignored secrets)
├── creds/                    ← raw setup credentials (git-ignored)
├── backend/                  ← step 1: shared remote-state backend (LOCAL state, run once)
├── foundation/               ← step 2: adopts the IdC instance, dual-mode; run once per account
├── governance-shared/        ← step 3: management-account singletons (organization mode only)
├── governance/               ← step 4: per-workshop OU + guardrail + budgets (organization mode only)
├── subscription/             ← step 5: IdC users + groups + memberships + Kiro subscription
└── claim-service/            ← step 6: optional self-serve credential claim
```

Each stack folder's `README.md` is its step document — open the folder and you
land on it.

### Configuration knobs

Everything that changes between projects is a variable: the region, the AWS
profile (which also sets organization vs account mode), the instance mode, the
workshop namespace, the accounts/groups/user counts, the account-access gate,
and the Kiro tier. Region and profile live in the git-ignored `.env`; the
workshop topology, `enable_account_access`, and the tier live in
`subscription/terraform/terraform.tfvars`. See
[`subscription/README.md`](./subscription/README.md) for the full list.

### Security notes

- `.env`, `.aws/credentials`, `creds/`, and anything under
  `subscription/output/` (generated manifests and credentials) are
  **git-ignored**. Keep them that way.
- Generated credential and OTP files contain sign-in secrets — distribute
  securely and delete them after use.
- The claim service's Function URL (the public HTTPS address AWS assigns the
  claim Lambda) is **public**; access is gated by the
  `WORKSHOP_CODE` and a per-IP cap. Pick a fresh code per workshop and don't
  share it before the event.
- Every stack stamps a `workshop_id` cost-allocation tag for per-workshop cost
  attribution — activate the tag once in the Billing console; see
  [`backend/README.md`](./backend/README.md).
