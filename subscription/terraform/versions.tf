terraform {
  # OpenTofu 1.12 is pinned in the project mise.toml. Creating the IdC account
  # instance needs the hashicorp/awscc provider (Cloud Control); the Identity
  # Store resources need hashicorp/aws >= 5.56.0.
  required_version = ">= 1.6"

  required_providers {
    # Used for Identity Store users/groups/memberships. The hashicorp/aws
    # provider has NO resource to *create* an Identity Center instance.
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
  # different machine later), and it is always active — the backend block lives
  # in the tracked backend.tf. Set it up before provisioning (RUNBOOK step 1b);
  # the backend spans these files:
  #
  #   backend-bootstrap/     creates the S3 bucket + DynamoDB lock table (run once)
  #   backend.tf             tracked, value-free `backend "s3" {}` (partial config)
  #   backend.hcl            git-ignored; auto-written by `mise run backend-bootstrap`
  #                          (or copy backend.hcl.example and edit it by hand)
  #
  # See RUNBOOK.md step 1b and TEARDOWN.md ("Option B") for the full walkthrough.
  # State contains user and group IDs — treat it as sensitive, but it holds NO
  # passwords (those never touch state; see scripts/).
  # ---------------------------------------------------------------------------
}
