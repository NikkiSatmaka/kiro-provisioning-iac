# ===========================================================================
# Remote S3 state backend — partial config (reuses the SHARED bucket)
# ===========================================================================
#
# This file is TRACKED and intentionally VALUE-FREE. The `backend "s3" {}` block
# is a partial configuration: backend blocks cannot reference variables, so the
# account-specific values (bucket, key, region) live in the git-ignored
# `backend.hcl` and are supplied at init time:
#
#   tofu init -backend-config=backend.hcl
#
# Isolation from the `subscription/` provisioning flow is achieved by a distinct state
# KEY (`claim-service/terraform.tfstate`), NOT a distinct bucket — this stack
# REUSES the shared `kiro-tofu-state-<account_id>` bucket that the `backend/`
# stack already created. There is deliberately NO `backend-bootstrap/`
# directory here (the bucket exists; see design.md Requirement 10.1, 10.2).
#
# Copy `backend.hcl.example` to `backend.hcl` and fill in your account id:
#
#   cp backend.hcl.example backend.hcl   # then edit the bucket's <account_id>
#   tofu init -backend-config=backend.hcl

terraform {
  backend "s3" {}
}
