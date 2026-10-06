# AWS provider.
#
# The deployment region is NEVER hardcoded: it is inherited from AWS_REGION in
# the environment (mise sources it from the git-ignored .env, which defaults to
# us-east-1). An operator can pin it with var.aws_region, but by default the
# provider resolves the region from the standard AWS SDK chain, exactly like
# the backend/ and subscription/ stacks. Credentials likewise come from the
# standard chain (AWS_PROFILE / the environment).

provider "aws" {
  region = var.aws_region != "" ? var.aws_region : null

  # workshop_id is merged in UNCONDITIONALLY (not left to the operator) so every
  # taggable resource is attributable per workshop in Cost Explorer / CUR.
  default_tags {
    tags = merge(var.default_tags, { workshop_id = var.workshop_id })
  }
}
