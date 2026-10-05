# AWS provider.
#
# Region and credentials are intentionally NOT hard-coded. They come from the
# environment so the same config is reusable across accounts:
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
# IMPORTANT: the IdC account instance is created in whatever region this
# provider targets. Kiro must support that region for IdC. Keep region
# consistent across tofu, the Kiro console, and user sign-in.

provider "aws" {
  # Empty string => null => provider falls back to AWS_REGION from the env.
  region  = var.aws_region != "" ? var.aws_region : null
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = var.default_tags
  }
}

# Resolve the region the AWS provider actually used (whether it came from
# var.aws_region or the AWS_REGION env fallback), so outputs / the manifest
# always report a concrete region for the scripts and credentials file.
data "aws_region" "current" {}
