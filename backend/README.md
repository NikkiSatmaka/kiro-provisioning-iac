# Phase 1 — Shared remote-state backend

This is **Phase 1** of the root README journey: the S3 bucket + DynamoDB lock
table that hold the other stacks' OpenTofu state. Run it **once per account**,
before the `subscription/` stack.

- **Prerequisites:** Phase 0 (toolchain + management-account AWS auth) — see the
  root [`README.md`](../README.md).
- **Next:** Phase 2 — Foundation ([`../foundation/README.md`](../foundation/README.md)).

## Why it exists (and why its own state)

A remote backend cannot create the bucket it stores state in — classic
chicken-and-egg. So this stack runs **first** and keeps its **own local**
state. It only tracks the state bucket and the lock table.

## What it creates

- A versioned, AES256-encrypted, public-access-blocked S3 bucket named
  `kiro-tofu-state-<ACCOUNT_ID>` (derived from your account id, so it is
  globally unique with nothing to fill in; override with `var.state_bucket_name`).
- The `kiro-tofu-locks` DynamoDB table used by OpenTofu for state locking.

## How to run (prefer mise)

```bash
mise run backend-bootstrap-plan   # DRY RUN: tofu init + plan, creates nothing
mise run backend-bootstrap        # apply AND auto-write both stacks' backend.hcl
```

A single bootstrap writes the backend config for **every** consuming stack —
`subscription/terraform/backend.hcl` and `claim-service/terraform/backend.hcl`.
Both point at this one bucket + lock table and differ only by their state
`key`, so you never fill in an account id by hand.

Raw equivalent:

```bash
cd backend/terraform
tofu init
tofu apply
tofu output -raw backend_hcl              > ../../subscription/terraform/backend.hcl
tofu output -raw backend_hcl_claim_service > ../../claim-service/terraform/backend.hcl
```

## Who consumes it

- `subscription/` — remote state with key `subscription/terraform.tfstate`.
- `claim-service/` — remote state with key `claim-service/terraform.tfstate`.

Both reuse the **same bucket** under their own distinct state key, so each
stack's state stays isolated (a `tofu destroy` on one can never touch the
other's state). Any future stack follows the same pattern: add a
`backend_hcl_<stack>` output here and have the bootstrap write it.

## Teardown

Destroy the consuming stacks first, then tear this down last:

```bash
mise run backend-destroy   # flips force_destroy=true, empties + deletes the bucket + table
```

See [`../subscription/TEARDOWN.md`](../subscription/TEARDOWN.md) ("Option B")
for the full order.

## Cost allocation

Every stack stamps a `workshop_id` tag on every taggable resource via the
provider's `default_tags`. The workshop-scoped stacks (`subscription/`,
`claim-service/`, `governance/`) use the real workshop id, so their costs
attribute per workshop in Cost Explorer / CUR. The shared stacks (`backend/`
and this remote-state backend, plus `foundation/`'s IdC instance) stamp
`workshop_id = "shared"`: a single S3 state bucket, DynamoDB lock table, and
IdC instance back **every** workshop, so their (negligible) cost is shared
overhead that cannot be split per workshop.

**One-time manual activation (management account).** A user-defined tag does
nothing for cost reporting until it is activated once in the Billing console —
this is not a reliable Terraform resource/API, so it stays a manual step:

> **Billing → Cost allocation tags → User-defined cost allocation tags →**
> select **`workshop_id`** → **Activate**.

After activation, AWS begins populating the tag in Cost Explorer and the CUR
going forward (it is not retroactive). From then on you can group or filter cost
by `workshop_id` to see each workshop's spend, with `shared` collecting the
backend/foundation overhead.

## State note

This stack's local state is git-ignored (see [`.gitignore`](./.gitignore)); the
provider lock file `terraform/.terraform.lock.hcl` stays tracked for
reproducible versions.
