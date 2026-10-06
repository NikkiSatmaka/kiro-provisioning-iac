# This stack targets the AWS Organizations MANAGEMENT account. AWS_PROFILE must
# be a management-account profile (the account that owns AWS Organizations and
# the organization IAM Identity Center instance this stack reads).
#
# Region and credentials come from the environment so the same config is
# reusable: AWS_PROFILE / AWS_REGION (set by mise from .env), an explicit
# `-var aws_region=...`, or the standard AWS SDK credential chain.
#
# Region precedence: an explicit -var/tfvars wins; when aws_region is empty (the
# default) the providers inherit AWS_REGION from the environment. The org IdC
# instance is READ from whatever region these providers target.

provider "aws" {
  region  = var.aws_region != "" ? var.aws_region : null
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = var.default_tags
  }
}

# Resolve the region the providers actually used (var.aws_region or the
# AWS_REGION env fallback), so the region output reports a concrete value.
data "aws_region" "current" {}
