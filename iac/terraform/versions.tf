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
  # Backend: LOCAL by default so the repo is runnable out of the box.
  #
  # For real projects — and ESPECIALLY so teardown works from a different
  # machine later — switch to the remote S3 backend. It is opt-in and lives in
  # separate files so this config stays runnable with no setup:
  #
  #   backend-bootstrap/     creates the S3 bucket + DynamoDB lock table (run once)
  #   backend.tf.example     rename to backend.tf to activate the S3 backend
  #   backend.hcl.example    copy to backend.hcl with your bucket/table names
  #
  # See TEARDOWN.md ("Option B") for the full walkthrough. State contains user
  # and group IDs — treat it as sensitive, but it holds NO passwords (those
  # never touch state; see scripts/).
  # ---------------------------------------------------------------------------
}
