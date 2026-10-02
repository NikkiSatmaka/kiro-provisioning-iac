# Shared remote-state backend (FUNCTION 1)

The S3 bucket + DynamoDB lock table that hold the other stacks' OpenTofu state.
Run this **once per account**, before the `subscription/` stack.

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
mise run backend-bootstrap        # apply AND auto-write subscription/terraform/backend.hcl
```

Raw equivalent:

```bash
cd backend/terraform
tofu init
tofu apply
tofu output -raw backend_hcl > ../../subscription/terraform/backend.hcl
```

## Who consumes it

- `subscription/` — remote state with key `subscription/terraform.tfstate`.

Future stacks reuse the **same bucket** under their own distinct state key, so
each stack's state stays isolated.

## Teardown

Destroy the consuming stacks first, then tear this down last:

```bash
mise run backend-destroy   # flips force_destroy=true, empties + deletes the bucket + table
```

See [`../subscription/TEARDOWN.md`](../subscription/TEARDOWN.md) ("Option B")
for the full order.

## State note

This stack's local state is git-ignored (see [`.gitignore`](./.gitignore)); the
provider lock file `terraform/.terraform.lock.hcl` stays tracked for
reproducible versions.
