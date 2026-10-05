terraform {
  # OpenTofu is pinned in the project mise.toml. Creating the IdC account
  # instance needs the hashicorp/awscc provider (Cloud Control); the region
  # output resolves through hashicorp/aws >= 5.56.0.
  required_version = ">= 1.6"

  required_providers {
    # Resolves the concrete region for the `region` output. hashicorp/aws has
    # NO resource to *create* an Identity Center instance.
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.56.0"
    }
    # Cloud Control provider: the only way to CREATE an IdC *instance*
    # (awscc_sso_instance maps to the AWS::SSO::Instance CloudFormation type,
    # which creates an account instance in a standalone or member account).
    awscc = {
      source  = "hashicorp/awscc"
      version = ">= 1.0.0"
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
