output "state_bucket_name" {
  description = "Derived (or overridden) state bucket name — the `bucket` in subscription/terraform/backend.hcl."
  value       = local.state_bucket_name
}

output "lock_table_name" {
  description = "Lock table name — paste into subscription/terraform/backend.hcl as `dynamodb_table`."
  value       = aws_dynamodb_table.locks.name
}

output "region" {
  description = "Region — paste into each stack's backend.hcl as `region`."
  value       = data.aws_region.current.region
}

# The shared backend values every stack uses. Each stack gets its OWN
# backend.hcl that differs ONLY in the `key` (its isolated state path), so a
# `tofu destroy` on one stack can never touch another's state. The bucket,
# region, lock table, and encryption are identical across stacks.
locals {
  _backend_hcl_shared = {
    bucket         = local.state_bucket_name
    region         = data.aws_region.current.region
    dynamodb_table = aws_dynamodb_table.locks.name
  }

  # Render a full backend.hcl body for a given state key.
  _backend_hcl_for = {
    for stack, key in {
      subscription  = "subscription/terraform.tfstate"
      claim_service = "claim-service/terraform.tfstate"
    } :
    stack => <<-EOT
      bucket         = "${local._backend_hcl_shared.bucket}"
      key            = "${key}"
      region         = "${local._backend_hcl_shared.region}"
      dynamodb_table = "${local._backend_hcl_shared.dynamodb_table}"
      encrypt        = true
    EOT
  }
}

# Ready-to-use backend.hcl body for the subscription stack. `mise run backend-bootstrap`
# writes this to ../../subscription/terraform/backend.hcl via `tofu output -raw backend_hcl`.
output "backend_hcl" {
  description = "The full subscription/terraform/backend.hcl body (mise writes it for you; tofu init -backend-config=backend.hcl reads it)."
  value       = local._backend_hcl_for["subscription"]
}

# Ready-to-use backend.hcl body for the claim-service stack. Same shared bucket
# + lock table as subscription, isolated by a distinct state key
# (claim-service/terraform.tfstate). `mise run backend-bootstrap` writes this to
# ../../claim-service/terraform/backend.hcl.
output "backend_hcl_claim_service" {
  description = "The full claim-service/terraform/backend.hcl body (mise writes it for you; tofu init -backend-config=backend.hcl reads it)."
  value       = local._backend_hcl_for["claim_service"]
}
