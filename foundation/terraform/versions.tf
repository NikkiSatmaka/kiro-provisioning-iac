terraform {
  # OpenTofu is pinned in the project mise.toml. This stack never *creates* an
  # Identity Center instance; it READS whichever instance the credentialed
  # account exposes (organization instance in the management account, account
  # instance in a child account) via the `data "aws_ssoadmin_instances"` data
  # source, which resolves through hashicorp/aws >= 5.56.0. Only the aws
  # provider is needed — no Cloud Control provider.
  required_version = ">= 1.6"

  required_providers {
    # Reads the IdC instance (data "aws_ssoadmin_instances") and resolves the
    # concrete region for the `region` output.
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.56.0"
    }
  }

  # ---------------------------------------------------------------------------
  # Backend: remote S3 state is REQUIRED (it is what makes teardown work from a
  # different machine later). The `backend "s3" {}` partial block lives in the
  # tracked backend.tf (not here); the account-specific values come from the
  # git-ignored, keyless backend.hcl at `tofu init` time, with the foundation
  # state key `foundation/terraform.tfstate` supplied as an init-time argument.
  # See RUNBOOK.md and backend/README.md for the full walkthrough.
  # ---------------------------------------------------------------------------
}
