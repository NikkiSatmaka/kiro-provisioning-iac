# Region and credentials come from the environment so the same config is
# reusable across accounts: AWS_PROFILE / AWS_REGION (set by mise from .env), an
# explicit `-var aws_region=...`, or the standard AWS SDK credential chain.
#
# Region precedence: an explicit -var/tfvars wins; when aws_region is empty (the
# default) the providers inherit AWS_REGION from the environment. The IdC account
# instance is created in whatever region these providers target.

provider "aws" {
  region  = var.aws_region != "" ? var.aws_region : null
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = var.default_tags
  }
}

# The Cloud Control provider that creates the IdC instance. Same region/profile
# resolution as the aws provider so the instance lands in the configured region.
# awscc has no default_tags block; tags are passed on the resource (list shape).
provider "awscc" {
  region  = var.aws_region != "" ? var.aws_region : null
  profile = var.aws_profile != "" ? var.aws_profile : null
}

# Resolve the region the providers actually used (var.aws_region or the
# AWS_REGION env fallback), so the region output reports a concrete value.
data "aws_region" "current" {}
