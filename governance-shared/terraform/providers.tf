# Region/credentials come from the environment so the same config is reusable.
#
# IMPORTANT: this stack is MANAGEMENT-ACCOUNT ONLY. It creates AWS Organizations
# SCPs and the budgets execution role — Organizations resources that only exist
# in the management account. Unlike foundation/ and subscription/, this stack is
# NOT dual-mode: it never runs in a child account. var.aws_profile MUST select a
# management-account (or delegated Org-admin) profile.
#
# Region precedence: an explicit -var/tfvars wins; when aws_region is empty (the
# default) the provider inherits AWS_REGION from the environment (mise sources it
# from the git-ignored .env file). Same resolution for the profile.

provider "aws" {
  region  = var.aws_region != "" ? var.aws_region : null
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = var.default_tags
  }
}

# Resolve the region the provider actually used (var.aws_region or the
# AWS_REGION env fallback), so any region reporting reflects a concrete value.
data "aws_region" "current" {}
