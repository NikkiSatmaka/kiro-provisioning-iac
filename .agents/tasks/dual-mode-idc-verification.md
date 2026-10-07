# Verification note — dual-mode IdC (Phase 2 implementation)

Static verification only. **No live AWS apply, destroy, or `tofu state mv` was
run.** No real credentials were used. All checks are `tofu fmt` / `tofu
validate` plus careful reasoning about the precondition. Toolchain: OpenTofu
v1.13.0 (mise-pinned), hashicorp/aws 6.67.0 (lock-pinned).

Worktree: `/Users/nikki/workspace/berca/lab/kiro-provisioning-iac/.worktrees/dual-mode-idc`
(branch `feat/dual-mode-idc`).

## What was run and the result

### `tofu fmt -check` (all touched stacks) — CLEAN

Ran `tofu fmt -check` in each of:
`subscription/terraform`, `foundation/terraform`, `governance/terraform`,
`governance-shared/terraform`, `backend/terraform`.
Result: exit 0 / no files listed in every stack (formatting clean).

### `tofu validate` (each touched stack) — SUCCESS

`tofu validate` requires `tofu init -backend=false` first (no backend/creds).
Did that per stack, then validated:

| Stack | `tofu validate` result |
| ----- | ---------------------- |
| `subscription/terraform`      | `Success! The configuration is valid.` |
| `foundation/terraform`        | `Success! The configuration is valid.` |
| `governance/terraform`        | `Success! The configuration is valid.` |
| `governance-shared/terraform` | `Success! The configuration is valid.` |
| `backend/terraform`           | `Success! The configuration is valid.` |

Notes:
- `governance-shared/terraform` validated cleanly on its own init — proves the
  new stack is well-formed (versions/providers/backend/variables/scps/
  budgets_role/outputs all parse and type-check together).
- `governance/terraform` validated cleanly WITHOUT changes to its resources —
  confirms it still compiles as a PURE CONSUMER of the three `TF_VAR_*`
  (`budgets_execution_role_arn`, `kiro_guardrail_scp_id`, `freeze_scp_id`); it
  was NOT inverted to create the primitives.
- `foundation/terraform` validated cleanly after removing `scps.tf` /
  `budgets_role.tf`, the three outputs, and `kiro_allowed_actions` — confirms no
  dangling references to the extracted resources remain.
- During validation the aws provider plugin cache in a stack's `.terraform/` was
  reused across stacks (network was slow); this does not affect validate
  semantics — all five report a valid configuration.

### instance_mode precondition — confirmed by validate + reasoning

Location: `subscription/terraform/identity_center.tf`, a `lifecycle.precondition`
on `aws_ssoadmin_permission_set.this`:

```hcl
condition     = !(var.instance_mode == "account" && var.enable_account_access)
error_message = "instance_mode = \"account\" cannot be combined with enable_account_access = true: ..."
```

Confirmed:
- The expression references **BOTH** variables (`var.instance_mode` AND
  `var.enable_account_access`) — this is why it is a `precondition`, not a
  variable `validation` block (OpenTofu variable validations cannot reference
  another variable).
- The resource has `count = var.enable_account_access ? 1 : 0`. The INVALID
  combo requires `enable_account_access == true`, which makes `count = 1`, so
  the resource instance EXISTS and its precondition is ALWAYS evaluated for the
  invalid combo. The precondition then evaluates to `false` and FAILS the plan.
- The valid combos never fail: `account` + `enable_account_access=false`
  (count 0, resource absent, no precondition to evaluate), and both
  `organization` combos (precondition true).
- `instance_mode` also has a value `validation` block
  (`contains(["organization","account"], var.instance_mode)`) and defaults to
  `"organization"`, preserving today's zero-config behavior.

**Could NOT exercise the precondition via `tofu plan` offline.** Attempted a
no-backend `tofu plan` with `-var` fixtures (dummy `idc_instance_arn` /
`identity_store_id`, a `workshop_accounts` fixture, and a `backend "local"`
override). The aws provider resolves `data.aws_region.current` / performs an STS
identity call during plan BEFORE resource-level preconditions are evaluated, so
plan errors on provider credentials (`InvalidClientTokenId` with dummy creds, or
a shared-config profile error) rather than reaching the precondition. This is
the documented "plan requires creds/backend it can't reach" case — so the
precondition is verified by `tofu validate` + the reasoning above, not by a live
plan. The temporary `backend "local"` override and any local state were removed
afterward.

## Python

No Python LOGIC was changed — only docstrings / print text in
`subscription/scripts/provision.py` and `subscription/scripts/teardown.py` were
made mode-aware. The Python test suite is therefore a **no-op** for this change
and was not run.

## Not verified (explicitly)

- **No live apply / destroy / state mv.** The `foundation/` → `governance-shared/`
  state migration is a DOCUMENTED operator runbook only
  (`governance-shared/RUNBOOK.md`); it was not executed. The five live resources
  still reside in `foundation/`'s real tfstate in AWS — migrating them is an
  operator action with live-resource risk (the guardrail SCP is attached to live
  OUs), out of scope for this static implementation.
- Behavior against a real IdC account instance (OQ-1 Kiro web-feature caveat)
  was not validated against live AWS — documented as a known limitation.
