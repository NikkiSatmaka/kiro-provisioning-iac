# scps.tf — the per-workshop Kiro guardrail SCP ATTACHMENT.
#
# The SCP policy OBJECTS (the Kiro guardrail allowlist and the deny-all freeze
# policy) are once-per-management-account singletons owned by foundation/ and
# consumed here by id (var.kiro_guardrail_scp_id / var.freeze_scp_id). This
# stack owns only the per-workshop ATTACHMENT of the shared guardrail SCP to the
# workshop OU, so every account in the OU is bounded to the Kiro-relevant
# actions.
#
# The freeze SCP is intentionally NOT attached here: AWS Budgets attaches it to
# a single breaching account automatically on budget breach (see budgets.tf);
# this stack declares NO attachment resource for it.

# --- Attach the shared Kiro guardrail SCP to the workshop OU ----------------
resource "aws_organizations_policy_attachment" "kiro_guardrail" {
  policy_id = var.kiro_guardrail_scp_id
  target_id = aws_organizations_organizational_unit.workshop.id
}
