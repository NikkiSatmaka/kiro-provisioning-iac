terraform {
  # OpenTofu 1.12 is pinned in the project mise.toml. This stack needs the
  # hashicorp/aws provider for the DynamoDB table, Lambda, Function URL, and IAM
  # role, plus hashicorp/archive to zip the handler + inlined index.html into
  # the deployment package (lambda.tf). (Unlike subscription/, there is no awscc
  # provider: this stack creates no IdC instance.)
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.56.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4.0"
    }
  }

  # ---------------------------------------------------------------------------
  # Backend: remote S3 state in the SHARED bucket under a distinct key. The
  # backend block lives in the tracked, value-free backend.tf; account-specific
  # values come from the git-ignored backend.hcl at init time:
  #
  #   tofu init -backend-config=backend.hcl
  #
  # There is NO backend-bootstrap/ directory — the shared bucket already exists
  # (created by the backend/ stack). Isolation is by state KEY, not bucket.
  # ---------------------------------------------------------------------------
}
