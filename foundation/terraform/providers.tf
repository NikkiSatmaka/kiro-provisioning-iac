# This stack is DUAL-MODE and account-safe: it only READS the IdC instance the
# credentialed account exposes (no Organizations writes live here anymore — the
# shared SCPs + budgets role moved to governance-shared/). Use a management-
# account profile to adopt the ORGANIZATION instance, or a child/member
# account's profile to adopt that account's OWN account instance.
#
# Region and credentials come from the environment so the same config is
# reusable: AWS_PROFILE / AWS_REGION (set by mise from .env), an explicit
# `-var aws_region=...`, or the standard AWS SDK credential chain.
#
# Region precedence: an explicit -var/tfvars wins; when aws_region is empty (the
# default) the providers inherit AWS_REGION from the environment. The IdC
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
