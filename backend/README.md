# Backend (step 1 of the flow) — the shared remote-state backend

> Phase link: this is **Step 1** of the root [`README.md`](../README.md) flow.
> Prerequisites: Phase 0 (toolchain + AWS sign-in) · Next: Step 2 — Foundation
> ([`../foundation/README.md`](../foundation/README.md)).

## What it is

The backend stack prepares the shared *remote state* for every other stack —
the place OpenTofu records what it has created. It provisions an S3 bucket and a
DynamoDB lock table, and nothing else.

A remote backend cannot create the bucket it stores its own state in — a
chicken-and-egg problem. So this stack runs **first** and keeps its state
**locally**, tracking only the state bucket and the lock table. Every later
stack then stores its state in that one bucket.

It creates:

- A versioned, AES256-encrypted, public-access-blocked S3 bucket named
  `kiro-tofu-state-<ACCOUNT_ID>`. The name is derived from your AWS account id,
  so it is globally unique with nothing to fill in (override with
  `var.state_bucket_name` if you need to).
- The `kiro-tofu-locks` DynamoDB table that OpenTofu uses for state locking.

Every consuming stack reuses that **same bucket** under its own distinct state
key, so each stack's state stays isolated — a `tofu destroy` on one stack can
never touch another's state.

This stack is account-agnostic: because it derives the bucket name from the
caller's own account id, it works the same whether you run under a
management-account profile (organization mode) or a child account's profile
(account mode).

> **Sharing one account across workshops.** The bucket + lock table are created
> **once per account**. Only the first repo directory for an account runs
> `backend-bootstrap`; every later directory on the **same account** reuses the
> same backend by **copying** each stack's `backend.hcl` across by hand instead
> of bootstrapping again. And each directory runs exactly **one workshop** — use
> a separate directory per workshop. Both rules, with the copy procedure, are in
> [`../MULTI-WORKSHOP.md`](../MULTI-WORKSHOP.md).

**Cost allocation.** Every stack stamps a `workshop_id` tag on each taggable
resource. The backend and the other shared resources stamp
`workshop_id = "shared"`, because one state bucket and lock table back every
workshop and their (negligible) cost cannot be split per workshop. A
user-defined tag does nothing for cost reporting until it is activated once in
the Billing console, which is a manual management-account step: **Billing → Cost
allocation tags → User-defined cost allocation tags →** select **`workshop_id`**
→ **Activate**. Activation is not retroactive; AWS populates the tag going
forward, after which you can group or filter cost by `workshop_id`.

This stack's local state is git-ignored (see [`.gitignore`](./.gitignore)); the
provider lock file `terraform/.terraform.lock.hcl` stays tracked so versions
stay reproducible.

## Prerequisites

- Phase 0 is complete: the toolchain is installed and you are signed in to AWS.
  See the root [`README.md`](../README.md).
- You are signed in under the AWS profile for the account you want to hold the
  shared state (management account for organization mode, or a child account for
  account mode).

## How to run

Run the dry run first to see what would happen, then run the mutating task.

1. `mise run backend-bootstrap-plan` — dry run. Initializes and plans; creates
   nothing. Review the plan.
2. `mise run backend-bootstrap` — creates the state bucket and lock table, then
   writes every consuming stack's `backend.hcl` so none of them needs an account
   id filled in by hand. Prompts you to approve before it changes anything.

Expected result: the S3 state bucket and DynamoDB lock table exist, and each
consuming stack has a `backend.hcl` pointing at them. You are ready for Step 2.

## Teardown

See the root [`TEARDOWN.md`](../TEARDOWN.md) for how to remove this stack.
