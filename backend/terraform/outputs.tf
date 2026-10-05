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

# The shared backend values every stack uses. The backend.hcl is keyless: the
# per-workshop state path (`key`) is supplied at init time via
# `tofu init -backend-config="key=workshops/<id>/<stack>/terraform.tfstate"`,
# so one bootstrapped backend.hcl serves every workshop and nothing in the file
# pins a single state path. The bucket, region, lock table, and encryption are
# identical across stacks.
locals {
  _backend_hcl_shared = {
    bucket         = local.state_bucket_name
    region         = data.aws_region.current.region
    dynamodb_table = aws_dynamodb_table.locks.name
  }

  # A keyless backend.hcl body carrying only bucket, region, dynamodb_table, and
  # encrypt. `key` is intentionally omitted and supplied at init time.
  _backend_hcl_body = <<-EOT
    bucket         = "${local._backend_hcl_shared.bucket}"
    region         = "${local._backend_hcl_shared.region}"
    dynamodb_table = "${local._backend_hcl_shared.dynamodb_table}"
    encrypt        = true
  EOT

  # Both stacks share the identical keyless body.
  _backend_hcl_for = {
    subscription  = local._backend_hcl_body
    claim_service = local._backend_hcl_body
    foundation    = local._backend_hcl_body
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

# Ready-to-use backend.hcl body for the foundation stack. Same shared bucket
# + lock table as the other stacks, isolated by a distinct init-time state key
# (foundation/terraform.tfstate). `mise run backend-bootstrap` writes this to
# ../../foundation/terraform/backend.hcl.
output "backend_hcl_foundation" {
  description = "The full foundation/terraform/backend.hcl body (mise writes it for you; tofu init -backend-config=backend.hcl reads it)."
  value       = local._backend_hcl_for["foundation"]
}
