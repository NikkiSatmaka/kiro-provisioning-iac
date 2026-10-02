output "state_bucket_name" {
  description = "Derived (or overridden) state bucket name — the `bucket` in subscription/terraform/backend.hcl."
  value       = local.state_bucket_name
}

output "lock_table_name" {
  description = "Lock table name — paste into subscription/terraform/backend.hcl as `dynamodb_table`."
  value       = aws_dynamodb_table.locks.name
}

output "region" {
  description = "Region — paste into subscription/terraform/backend.hcl as `region`."
  value       = data.aws_region.current.region
}

# Ready-to-use backend.hcl body for the subscription stack. `mise run backend-bootstrap`
# writes this to ../../subscription/terraform/backend.hcl via `tofu output -raw backend_hcl`.
output "backend_hcl" {
  description = "The full subscription/terraform/backend.hcl body (mise writes it for you; tofu init -backend-config=backend.hcl reads it)."
  value       = <<-EOT
    bucket         = "${local.state_bucket_name}"
    key            = "subscription/terraform.tfstate"
    region         = "${data.aws_region.current.region}"
    dynamodb_table = "${aws_dynamodb_table.locks.name}"
    encrypt        = true
  EOT
}
