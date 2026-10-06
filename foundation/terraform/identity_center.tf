# ===========================================================================
# IAM Identity Center — ORGANIZATION instance adopted (read-only)
# ===========================================================================
#
# This stack READS the management account's existing IAM Identity Center
# ORGANIZATION instance. It never creates or destroys it. Enabling IdC in the
# management account is the one-time console Step 0 (see RUNBOOK). The single,
# long-lived org instance is what every workshop's subscription stack consumes
# via var.idc_instance_arn / var.identity_store_id.
#
# If IdC has never been enabled in the management account, the data source
# returns no instance and plan fails — that is the missing Step 0, not an error
# to work around here.

data "aws_ssoadmin_instances" "this" {}

locals {
  # Exactly one organization instance exists per management account. The data
  # source attributes are already lists; tolist(...) is a safe no-op and [0]
  # selects the single org instance.
  instance_arn      = tolist(data.aws_ssoadmin_instances.this.arns)[0]
  identity_store_id = tolist(data.aws_ssoadmin_instances.this.identity_store_ids)[0]
  resolved_region   = data.aws_region.current.region
}
