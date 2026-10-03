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

  default_tags {
    tags = {
      Project = "kiro-provisioning-iac"
      Service = "claim-service"
    }
  }
}
