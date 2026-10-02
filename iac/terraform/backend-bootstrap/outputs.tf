output "state_bucket_name" {
  description = "Derived (or overridden) state bucket name — the `bucket` in ../backend.hcl."
  value       = local.state_bucket_name
}

output "lock_table_name" {
  description = "Lock table name — paste into ../backend.hcl as `dynamodb_table`."
  value       = aws_dynamodb_table.locks.name
}

output "region" {
  description = "Region — paste into ../backend.hcl as `region`."
  value       = data.aws_region.current.region
}

# Ready-to-use backend.hcl body for the main config. `mise run backend-bootstrap`
# writes this to ../backend.hcl via `tofu output -raw backend_hcl`.
output "backend_hcl" {
  description = "The full ../backend.hcl body (mise writes it for you; tofu init -backend-config=backend.hcl reads it)."
  value       = <<-EOT
    bucket         = "${local.state_bucket_name}"
    key            = "kiro-subscriptions/terraform.tfstate"
    region         = "${data.aws_region.current.region}"
    dynamodb_table = "${aws_dynamodb_table.locks.name}"
    encrypt        = true
  EOT
}
