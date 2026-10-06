terraform {
  # OpenTofu 1.12 is pinned in the project mise.toml. This module consumes the
  # long-lived Foundation IdC instance (operator-supplied ARN + identity store
  # ID) rather than creating it, so only hashicorp/aws >= 5.56.0 is needed for
  # the Identity Store users/groups/memberships and SSO admin resources.
  required_version = ">= 1.6"

  required_providers {
    # Used for Identity Store users/groups/memberships and SSO admin permission
    # sets / account assignments against the Foundation IdC instance.
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.56.0"
    }
  }

  # ---------------------------------------------------------------------------
  # Backend: remote S3 state is REQUIRED (it is what makes teardown work from a
  # different machine later), and it is always active — the backend block lives
  # in the tracked backend.tf. Set it up before provisioning (RUNBOOK step 1b);
  # the backend spans these files:
  #
  #   ../../backend/terraform/  sibling stack: creates the S3 bucket + DynamoDB lock table (run once)
  #   backend.tf             tracked, value-free `backend "s3" {}` (partial config)
  #   backend.hcl            git-ignored; auto-written by `mise run backend-bootstrap`
  #                          (or copy backend.hcl.example and edit it by hand)
  #
  # See RUNBOOK.md step 1b and TEARDOWN.md ("Option B") for the full walkthrough.
  # State contains user and group IDs — treat it as sensitive, but it holds NO
  # passwords (those never touch state; see scripts/).
  # ---------------------------------------------------------------------------
}
