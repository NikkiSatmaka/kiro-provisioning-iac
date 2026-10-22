# Running more than one workshop

This document covers two related operating rules that the step documents assume
but do not spell out:

1. **One repo directory = one workshop.** To run a second workshop, use a
   second directory (a fresh clone or an unzipped copy) — never reuse the same
   directory for two workshops at once.
2. **Sharing one AWS account across workshops.** When several workshops run in
   the same AWS account, only the **first** directory bootstraps the shared
   backend. Every later directory **reuses** it by copying the backend wiring
   (`backend.hcl`) — and, if it will ever tear the backend down, the backend
   stack's local `terraform.tfstate` — across by hand.

Read this once before you set up your second workshop. For the normal
single-workshop flow, the root [`README.md`](./README.md) is still the starting
point.

---

## 1. One directory per workshop

This repo's per-run settings live in a **single** git-ignored `.env` at the repo
root: `WORKSHOP_ID`, `AWS_PROFILE`, `AWS_REGION`, `WORKSHOP_CODE`. The mutating
tasks read `WORKSHOP_ID` from that one file to key a workshop's remote state and
resources (`workshops/<WORKSHOP_ID>/…` state keys,
`credential-claim-<WORKSHOP_ID>` resource names). Because there is exactly one
`.env`, a single directory describes exactly one workshop at a time.

So the rule is simple:

> **One workshop = one directory.** To run a second (or third) workshop, get a
> second copy of the repo in a **different directory** — `git clone` it again,
> or download the zip and unzip it somewhere else — and configure that copy's
> own `.env` for the new workshop.

Each directory then carries its own:

- `.env` (its `WORKSHOP_ID`, and optionally its own `WORKSHOP_CODE`),
- `.aws/` sign-in cache and credentials,
- per-stack `backend.hcl` files and OpenTofu working directories
  (`.terraform/`),
- `subscription/output/` and `claim-service/output/` artifacts.

Keeping them in separate directories means the two workshops never fight over
the same `.env`, the same local working state, or the same output files.

> **Why not just change `WORKSHOP_ID` in one directory and re-run?** You *can*
> drive several workshops sequentially from one directory by editing
> `WORKSHOP_ID` between full runs — the remote state is already namespaced per
> workshop, so they stay isolated in S3. But it is error-prone: one stale
> `WORKSHOP_ID`, one leftover `backend.hcl` key, or one half-finished
> `subscription/output/` and you act on the wrong workshop. You also cannot work
> on two workshops **in parallel** that way, because the single `.env` can only
> name one at a time. Separate directories remove the foot-gun entirely, so
> prefer them.

---

## 2. Sharing one AWS account across workshops

The backend stack (Step 1) creates the **shared** remote-state backend: one S3
bucket named `kiro-tofu-state-<ACCOUNT_ID>` and one `kiro-tofu-locks` DynamoDB
table **per AWS account**. Every stack, in every workshop, stores its state in
that **same** bucket, isolated only by a distinct state key
(`workshops/<WORKSHOP_ID>/<stack>/terraform.tfstate`). See
[`backend/README.md`](./backend/README.md).

That design is exactly what lets many workshops share one account. But it has a
consequence for the **second and later directories** on the same account:

> The backend bucket for an account can only be created **once**. The first
> directory runs `mise run backend-bootstrap` and creates it. Every later
> directory on the **same account must NOT bootstrap again** — the bucket
> already exists. Instead it must be handed the backend wiring the first
> directory produced.

### What `backend-bootstrap` produces, and why it is per-directory

`mise run backend-bootstrap` does two things:

1. Creates the S3 bucket + lock table (an account-level, once-per-account
   action).
2. Writes a `backend.hcl` into **each** consuming stack
   (`foundation/`, `subscription/`, `claim-service/`, `governance/`,
   `governance-shared/`), telling that stack which bucket, region, and lock
   table to use.

The `backend.hcl` files are **git-ignored** (they name your account's bucket),
so a fresh clone does not have them. A second directory therefore needs those
files, but it must **not** re-run step 1 against an account that already has the
bucket.

The backend stack also keeps its **own local `terraform.tfstate`** (it is the
bootstrap stack — it has nowhere remote to store state yet). That local state is
git-ignored too, and it exists only in the directory that ran the bootstrap.

### The manual copy procedure (second and later directories)

On the **first** directory for the account, bootstrap normally:

```bash
# in directory #1 (the first workshop on this account)
mise run backend-bootstrap
```

For **each additional** directory on the **same account**, do **not** bootstrap.
Copy the backend wiring across by hand instead. Let `WS1` be the first
directory and `WS2` the new one:

```bash
# copy every stack's backend.hcl from the already-bootstrapped directory
for stack in foundation subscription claim-service governance governance-shared; do
  cp "WS1/$stack/terraform/backend.hcl" "WS2/$stack/terraform/backend.hcl"
done
```

All of these `backend.hcl` files are **identical across workshops on the same
account** — they carry only the shared `bucket`, `region`, `dynamodb_table`, and
`encrypt`, and **no** `key`. The per-workshop `key` is supplied at init time by
the mise tasks from `WORKSHOP_ID`, so the same copied file serves every
workshop. (If you cannot copy from the first directory — e.g. you no longer have
it — recreate each file from its tracked `backend.hcl.example` template and fill
in your 12-digit account id; see
[`claim-service/terraform/backend.hcl.example`](./claim-service/terraform/backend.hcl.example).)

Then configure `WS2`'s `.env` with the **new** workshop's `WORKSHOP_ID` (and the
same `AWS_PROFILE` / `AWS_REGION`, since it is the same account), sign in, and
run the normal flow from **Step 2** onward — you skip Step 1 because the backend
already exists:

```bash
# in directory #2 (same account, new workshop)
cp .env.example .env    # then set the NEW WORKSHOP_ID, same AWS_PROFILE/REGION
mise run aws-login
mise run verify
# Step 1 (backend-bootstrap) is SKIPPED — the bucket already exists.
# Continue at Step 2 (foundation) per the root README.
```

### When you also need the backend stack's `terraform.tfstate`

The copied `backend.hcl` files are enough to **provision and run** a second
workshop on a shared account. You only need the backend stack's **local
`terraform.tfstate`** in a directory that will **operate on the backend stack
itself**, specifically:

- `mise run backend-destroy-workshop` — purge one finished workshop's leftover
  state. It reads the shared bucket + lock table names from the backend stack's
  **own** outputs, which require that stack's local state (or a `tofu init` that
  can read it).
- `mise run backend-destroy` — tear the whole shared backend down (only once
  **every** workshop on the account is gone).

If the directory that ran the bootstrap is still around, run those backend
teardown tasks **from that directory** and you need to copy nothing. If instead
you want a different directory to be able to destroy the backend, copy the
backend stack's local state across as well:

```bash
# only needed if a NON-bootstrapping directory must run backend-destroy* tasks
cp WS1/backend/terraform/terraform.tfstate         WS2/backend/terraform/terraform.tfstate
cp WS1/backend/terraform/terraform.tfstate.backup  WS2/backend/terraform/terraform.tfstate.backup
```

> The backend resources are **idempotent by name** (the bucket name is derived
> from the account id, the lock table name is fixed). So even if that local
> state is lost entirely, a directory can re-adopt the backend without
> recreating it. Copying the state is the clean path; re-importing is the
> fallback. Either way, **never** let two directories run a destructive backend
> task against the same account at the same time.

### Tearing down on a shared account — order matters

Because the bucket and lock table are shared, the whole-backend teardown
(`mise run backend-destroy`) is **all-or-nothing for the account**. Run it only
after **every** workshop on that account has been torn down. While other
workshops are still live, remove just the finished one's leftover state with
`mise run backend-destroy-workshop` (it is surgical — it only touches
`workshops/<WORKSHOP_ID>/…` and never the bucket, the lock table, or another
workshop). The full teardown order is in [`TEARDOWN.md`](./TEARDOWN.md).

---

## Quick reference

| Situation | What to do |
| --------- | ---------- |
| Second workshop, **separate** AWS account | Fresh directory, set its `.env`, run the **full** flow including Step 1 `backend-bootstrap`. |
| Second workshop, **same** AWS account | Fresh directory, **copy** every stack's `backend.hcl` from the first directory, set its `.env` with the new `WORKSHOP_ID`, **skip** Step 1, continue from Step 2. |
| A non-bootstrapping directory must run `backend-destroy*` | Also copy the backend stack's local `terraform.tfstate` (+ `.backup`) across, or run those tasks from the original bootstrapping directory. |
| Several workshops over time on one account | Any order of provisioning; tear down each with `backend-destroy-workshop`, and run the account-wide `backend-destroy` only once **all** are gone. |
