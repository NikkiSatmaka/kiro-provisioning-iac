# ===========================================================================
# IAM Identity Center — ACCOUNT instance owned by the Foundation IdC service
# ===========================================================================
#
# awscc_sso_instance creates an *account* instance of Identity Center in the
# account/region the provider targets (maps to AWS::SSO::Instance). This is the
# single, long-lived, shared instance every workshop's subscription stack
# consumes via var.idc_instance_arn / var.identity_store_id.
#
# PRECONDITION (cannot be enforced from here): the org management account must
# have permitted member-account instance creation. If it has not, apply fails
# with an authorization error on this resource. See RUNBOOK step 0.
#
# One account instance per account (across all regions). Import an existing one:
#   tofu import awscc_sso_instance.this <instance_arn>

resource "awscc_sso_instance" "this" {
  # name is optional; helps identify the instance in the console. Defaults to
  # "kiro-login" (var.instance_name).
  name = var.instance_name

  # AWSCC uses a list-of-objects tag shape (no provider default_tags support).
  tags = [for k, v in var.default_tags : { key = k, value = v }]
}

locals {
  identity_store_id = awscc_sso_instance.this.identity_store_id
  instance_arn      = awscc_sso_instance.this.instance_arn
  resolved_region   = data.aws_region.current.region
}
