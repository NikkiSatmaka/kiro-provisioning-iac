# ===========================================================================
# IAM Identity Center — instance adopted (read-only, dual-mode)
# ===========================================================================
#
# This stack READS whichever IAM Identity Center instance the credentialed
# account exposes. It never creates or destroys it:
#   - in the AWS Organizations MANAGEMENT account it adopts the single
#     ORGANIZATION instance (today's behavior), and
#   - in a CHILD/member account it adopts that account's OWN account instance.
# The same `data "aws_ssoadmin_instances"` source resolves per-account, so no
# instance_mode input is needed here. Enabling IdC in the target account is the
# one-time console Step 0 (see RUNBOOK). The adopted instance is what the
# subscription stack consumes via var.idc_instance_arn / var.identity_store_id.
#
# If IdC has never been enabled in the credentialed account, the data source
# returns no instance and plan fails — that is the missing Step 0 (now
# applicable per-account), not an error to work around here.

data "aws_ssoadmin_instances" "this" {}

locals {
  # Exactly one instance is exposed per account (one organization instance in
  # the management account, or one account instance in a child account). The
  # data source attributes are already lists; tolist(...) is a safe no-op and
  # [0] selects that single instance.
  instance_arn      = tolist(data.aws_ssoadmin_instances.this.arns)[0]
  identity_store_id = tolist(data.aws_ssoadmin_instances.this.identity_store_ids)[0]
  resolved_region   = data.aws_region.current.region
}
