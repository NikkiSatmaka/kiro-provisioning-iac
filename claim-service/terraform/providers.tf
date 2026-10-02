# AWS provider.
#
# The deployment region is pinned to ap-southeast-1 (Requirement 4.2): the Kiro
# IdC credentials this service distributes are issued in ap-southeast-1, so the
# table, Lambda, and Function URL that hand them out live in the same region.
# Credentials come from the standard AWS SDK credential chain (AWS_PROFILE /
# the environment); only the region is fixed here.

provider "aws" {
  region = "ap-southeast-1"

  default_tags {
    tags = {
      Project = "kiro-provisioning-iac"
      Service = "claim-service"
    }
  }
}
