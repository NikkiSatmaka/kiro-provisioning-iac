terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.56.0"
    }
    # NOTE: NO hashicorp/awscc. Organizations, SCPs, Budgets, and the budget
    # action are all first-class hashicorp/aws resources; the awscc provider
    # the foundation stack needs (for the IdC instance) has no role here.
  }

  # ---------------------------------------------------------------------------
  # Remote S3 state (REQUIRED). The partial `backend "s3" {}` block lives in the
  # tracked backend.tf (not here); the account-specific values come from the
  # git-ignored, keyless backend.hcl at `tofu init` time, with the governance
  # state key `workshops/<WORKSHOP_ID>/governance/terraform.tfstate` supplied as
  # an init-time argument. See RUNBOOK.md and backend/README.md.
  # ---------------------------------------------------------------------------
}
