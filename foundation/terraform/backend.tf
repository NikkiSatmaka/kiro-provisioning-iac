# ===========================================================================
# Remote S3 state backend — REQUIRED (foundation RUNBOOK)
# ===========================================================================
#
# This file is TRACKED and intentionally VALUE-FREE. The `backend "s3" {}` block
# is a partial configuration: backend blocks cannot reference variables, so the
# account-specific values (bucket, region, lock table) live in the git-ignored
# `backend.hcl` and are supplied at init time:
#
#   tofu init -backend-config=backend.hcl \
#     -backend-config="key=foundation/terraform.tfstate"
#
# `backend.hcl` is normally written for you by `mise run backend-bootstrap`
# (bucket name derived from your account id); you can also copy and edit
# `backend.hcl.example` by hand. Because this file is always present, the config
# always uses remote state — there is no local-state fallback, by design.

terraform {
  backend "s3" {}
}
