# ===========================================================================
# Backend bootstrap — the S3 bucket + DynamoDB lock table that hold tofu state
# ===========================================================================
#
# WHY THIS IS A SEPARATE CONFIG
# -----------------------------
# A remote backend cannot create the bucket it stores state in — the bucket must
# already exist before `tofu init` can migrate state into it. That is the
# classic chicken-and-egg. So this tiny config runs FIRST, with its OWN local
# state, and creates:
#
#   * an S3 bucket (versioned, encrypted, public access blocked) for the
#     main config's terraform.tfstate, and
#   * a DynamoDB table used by OpenTofu for state locking.
#
# You run this ONCE per account. Its own state is small and can live locally or
# be committed-by-value is NOT needed — if this state is ever lost you can
# re-import or simply re-create (the resources are idempotent by name).
#
# ORDER OF OPERATIONS (normally via `mise run backend-bootstrap`)
# ---------------------------------------------------------------
#   cd iac/terraform/backend-bootstrap
#   tofu init
#   tofu apply                                     # bucket name auto-derived
#   tofu output -raw backend_hcl > ../backend.hcl  # mise does this for you
#
# The bucket name needs NO human input: it is derived deterministically from the
# account id as "kiro-tofu-state-<ACCOUNT_ID>" (globally unique). Set
# var.state_bucket_name in terraform.tfvars only to OVERRIDE that default.
#
# Then in ../ (the main config): backend.tf is tracked + value-free; backend.hcl
# (auto-written above, or copied from backend.hcl.example) carries the values.
#
# TEARDOWN
# --------
# Destroy the MAIN config first (so its state is empty / no longer needed),
# migrate the main config back to local state, THEN destroy this bootstrap:
#   cd iac/terraform/backend-bootstrap && tofu destroy
# The bucket has force_destroy=false by default to prevent accidental loss of
# state; flip var.force_destroy=true only when you intend to delete it.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.56.0"
    }
  }
  # Bootstrap keeps its own LOCAL state on purpose (it has nowhere remote to go
  # yet). This state only tracks the bucket + lock table.
}

provider "aws" {
  # Empty => inherit AWS_REGION from the env (mise sources it from .env).
  # Keep this region the SAME as the main config's.
  region  = var.aws_region != "" ? var.aws_region : null
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = var.default_tags
  }
}

# Region the provider actually resolved to, surfaced in outputs for backend.hcl.
data "aws_region" "current" {}

# Account id, used to derive a deterministic, globally-unique bucket name.
data "aws_caller_identity" "current" {}

locals {
  # Deterministic bucket name: no human has to invent a globally-unique string.
  # Operator override (var.state_bucket_name) wins when set; otherwise derive
  # "kiro-tofu-state-<ACCOUNT_ID>" — unique across AWS because the account id is.
  state_bucket_name = var.state_bucket_name != "" ? var.state_bucket_name : "kiro-tofu-state-${data.aws_caller_identity.current.account_id}"
}

# ---------------------------------------------------------------------------
# State bucket
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "state" {
  bucket        = local.state_bucket_name
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---------------------------------------------------------------------------
# Lock table
# ---------------------------------------------------------------------------
# OpenTofu's S3 backend uses a DynamoDB table for state locking. The hash key
# MUST be named "LockID" (string). PAY_PER_REQUEST avoids capacity planning.

resource "aws_dynamodb_table" "locks" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}
