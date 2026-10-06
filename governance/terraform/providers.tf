# Region/credentials come from the environment so the same config is reusable.
# IMPORTANT: this stack targets the ORGANIZATIONS MANAGEMENT account (or a
# delegated Org-admin). var.aws_profile selects those creds — the same
# management-account profile every stack in this repo now uses; its SCPs and
# budgets still TARGET the member accounts.
#
# Region precedence: an explicit -var/tfvars wins; when aws_region is empty (the
# default) the provider inherits AWS_REGION from the environment (mise sources it
# from the git-ignored .env file). Same resolution for the profile.

provider "aws" {
  region  = var.aws_region != "" ? var.aws_region : null
  profile = var.aws_profile != "" ? var.aws_profile : null

  # workshop_id is merged in UNCONDITIONALLY (not left to the operator) so every
  # taggable resource is attributable per workshop in Cost Explorer / CUR.
  default_tags {
    tags = merge(var.default_tags, { workshop_id = var.workshop_id })
  }
}

# Resolve the region the provider actually used (var.aws_region or the
# AWS_REGION env fallback), so any region reporting reflects a concrete value.
data "aws_region" "current" {}
