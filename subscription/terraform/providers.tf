# AWS provider.
#
# This stack targets the AWS Organizations MANAGEMENT account; AWS_PROFILE must
# be a management-account profile (the account that owns the organization IdC
# instance identities are written into).
#
# Region and credentials are intentionally NOT hard-coded. They come from the
# environment so the same config is reusable:
#
#   AWS_PROFILE / AWS_REGION          (set by the project mise.toml), or
#   -var "aws_region=..."             (explicit override), or
#   standard AWS SDK credential chain.
#
# Region precedence: an explicit `-var aws_region=...` (or tfvars) wins; when
# aws_region is left empty (the default) the provider inherits AWS_REGION from
# the environment. mise sources AWS_REGION from the git-ignored .env file —
# change the region there (`cp .env.example .env`), no edits here.
#
# IMPORTANT: identities are written into the org IdC instance in whatever region
# this provider targets. Kiro must support that region for IdC. Keep region
# consistent across tofu, the Kiro console, and user sign-in.

provider "aws" {
  # Empty string => null => provider falls back to AWS_REGION from the env.
  region  = var.aws_region != "" ? var.aws_region : null
  profile = var.aws_profile != "" ? var.aws_profile : null

  # workshop_id is merged in UNCONDITIONALLY (not left to the operator) so every
  # taggable resource is attributable per workshop in Cost Explorer / CUR.
  default_tags {
    tags = merge(var.default_tags, { workshop_id = var.workshop_id })
  }
}

# Resolve the region the AWS provider actually used (whether it came from
# var.aws_region or the AWS_REGION env fallback), so outputs / the manifest
# always report a concrete region for the scripts and credentials file.
data "aws_region" "current" {}
