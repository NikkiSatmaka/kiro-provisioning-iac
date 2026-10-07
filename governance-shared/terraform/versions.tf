terraform {
  # OpenTofu is pinned in the project mise.toml. This stack creates AWS
  # Organizations resources (2 SCP policy objects) and an IAM role, all
  # first-class hashicorp/aws resources — no Cloud Control provider is needed.
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.56.0"
    }
    # NOTE: NO hashicorp/awscc. Organizations SCPs and IAM are all first-class
    # hashicorp/aws resources.
  }

  # ---------------------------------------------------------------------------
  # Remote S3 state (REQUIRED). The partial `backend "s3" {}` block lives in the
  # tracked backend.tf (not here); the account-specific values come from the
  # git-ignored, keyless backend.hcl at `tofu init` time, with the
  # governance-shared state key `governance-shared/terraform.tfstate` supplied as
  # an init-time argument. This is a management-account SINGLETON state (no
  # workshops/<id>/ prefix, mirroring foundation/terraform.tfstate). See
  # RUNBOOK.md and backend/README.md.
  # ---------------------------------------------------------------------------
}
