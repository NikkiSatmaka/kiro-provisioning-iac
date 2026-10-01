output "state_bucket_name" {
  description = "Bucket name — paste into ../backend.hcl as `bucket`."
  value       = aws_s3_bucket.state.id
}

output "lock_table_name" {
  description = "Lock table name — paste into ../backend.hcl as `dynamodb_table`."
  value       = aws_dynamodb_table.locks.name
}

output "region" {
  description = "Region — paste into ../backend.hcl as `region`."
  value       = data.aws_region.current.region
}

# Copy-paste-ready backend.hcl body for the main config.
output "backend_hcl" {
  description = "Paste this into ../backend.hcl (tofu init -backend-config=backend.hcl)."
  value       = <<-EOT
    bucket         = "${aws_s3_bucket.state.id}"
    key            = "kiro-subscriptions/terraform.tfstate"
    region         = "${data.aws_region.current.region}"
    dynamodb_table = "${aws_dynamodb_table.locks.name}"
    encrypt        = true
  EOT
}
