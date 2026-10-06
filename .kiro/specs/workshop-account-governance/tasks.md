# Implementation Plan: Workshop Account Governance

## Overview

Build the standalone, management-account-scoped `governance/` OpenTofu stack per
the design: one OU per workshop, placement of pre-existing accounts, a Kiro
guardrail SCP on the OU, an unattached deny-all freeze SCP, a least-privilege
budgets execution role, and per-account budgets whose breach automatically
attaches the freeze SCP to the single breaching account. Add the `mise`
lifecycle tasks, the `backend/` bootstrap wiring, the `.gitignore` entries, and
the README/RUNBOOK docs.

Each task builds on the previous one and ends wired into the stack — no orphaned
code. The language is **HCL / OpenTofu** throughout (plus the POSIX shell used
by the existing `mise` tasks).

**Verification is non-mutating only.** Every task is verified with `tofu fmt`,
`tofu validate`, and `tofu plan` — **never `tofu apply`**. Applying mutates the
live AWS Organizations management account (high blast radius) and happens only
with the operator's explicit go-ahead. No task below runs `apply` or `destroy`.

## Tasks

- [x] 1. Scaffold the stack skeleton and wire provider + backend
  - Create `governance/terraform/` and author `versions.tf` (`required_version >= 1.6`, `hashicorp/aws >= 5.56.0`, **no `hashicorp/awscc`**)
  - Author `providers.tf`: aws provider with `region = var.aws_region != "" ? var.aws_region : null` and `profile = var.aws_profile != "" ? var.aws_profile : null`, `default_tags`, a `data "aws_region" "current"`, and a `data "aws_caller_identity" "current"`
  - Author `backend.tf` as a tracked, value-free `backend "s3" {}` block
  - Author `backend.hcl.example`: keyless, mirroring foundation (bucket, region, `dynamodb_table`, `encrypt = true`), with a comment that the governance state key `workshops/<WORKSHOP_ID>/governance/terraform.tfstate` is supplied at init time and is not in this file
  - _Requirements: 9.1, 9.2, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8, 14.3_
  - _Verify:_ `cd governance/terraform && tofu init -backend=false && tofu validate && tofu fmt -check` all pass.

- [x] 2. Define `variables.tf` with all inputs and validations
  - [x] 2.1 Author all input variables with their validations
    - `workshop_id` (slug regex `^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$` **and** reject consecutive hyphens via `!can(regex("--", ...))`)
    - `parent_id`; `account_ids` (each `^\d{12}$`, error message naming the offending value(s))
    - `aws_region` (default `""`), `aws_profile` (default `""`), `default_tags` (sensible default)
    - `kiro_allowed_actions` (conservative Kiro/IdC starter allowlist default), `freeze_threshold_percent` (default `100`)
    - `notification_emails` (**no default; required**, `length > 0` validation), `notify_threshold_percent` (default `null`)
    - `budget_limit_amount`, `budget_limit_unit` (default `"USD"`)
    - _Requirements: 1.2, 1.3, 2.2, 4.3, 4.4, 8.1, 8.2, 13.2, 13.3, 14.3_
  - [x] 2.2 Confirm the negative-validation behavior
    - Assert bad slug (`Bad_ID`, `a--b`), a non-12-digit `account_ids` entry (message names the value), and empty `notification_emails` each fail `tofu validate`
    - _Requirements: 1.3, 8.2, 13.2, 13.3_
  - _Verify:_ `tofu validate` passes with valid inputs; the three negative cases in 2.2 fail validation.

- [x] 3. Implement `organizations.tf` — the OU and account placement
  - Author a single `aws_organizations_organizational_unit "workshop"` (`name = "workshop-${var.workshop_id}"`, `parent_id = var.parent_id`) — never `for_each`, so exactly one OU per run
  - Place pre-existing accounts via `for_each = toset(var.account_ids)`; use the import/adopt mechanism from the design with `lifecycle { prevent_destroy = true }` so a destroy never closes an account; confirm the exact placement primitive against the installed provider version and record the chosen mechanism + `moveAccount` fallback for the RUNBOOK (task 9)
  - Keep placement keyed solely by `var.account_ids` so no account outside that set is ever moved
  - _Requirements: 1.1, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3_
  - _Verify:_ `tofu validate` passes; a sample `tofu plan` shows exactly 1 OU + N placements, creates/closes no accounts.

- [x] 4. Implement `scps.tf` — guardrail (attached) and freeze (unattached) SCPs
  - [x] 4.1 Author the Kiro guardrail and freeze SCPs
    - Guardrail: `data "aws_iam_policy_document"` with a single `Allow` of `var.kiro_allowed_actions` on `*`; `aws_organizations_policy` (type `SERVICE_CONTROL_POLICY`); `aws_organizations_policy_attachment` to the workshop OU
    - Freeze: a separate `data "aws_iam_policy_document"` (`Deny *` on `*`) and `aws_organizations_policy` (type `SERVICE_CONTROL_POLICY`) with **intentionally no attachment resource**
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3_
  - [x] 4.2 Property test — guardrail renders exactly the supplied allowlist
    - **Property 1: Guardrail renders exactly the supplied allowlist**
    - Over several `kiro_allowed_actions` shapes, assert the rendered guardrail document has a single `Allow` whose action set equals the input and grants nothing outside it (plan-output / policy-document assertion over varied tfvars)
    - **Validates: Requirements 4.3, 4.4**
  - _Verify:_ `tofu validate` passes; a sample `tofu plan` shows the guardrail attached to the OU and the freeze policy created with 0 attachments.

- [x] 5. Implement `budgets.tf` — execution role, per-account budgets, and SCP actions
  - [x] 5.1 Author the budgets execution role (least privilege + confused-deputy guard)
    - Trust policy: `sts:AssumeRole` for `budgets.amazonaws.com` with a `StringEquals aws:SourceAccount = data.aws_caller_identity.current.account_id` condition
    - Inline permissions scoped to Organizations attach/detach of the freeze policy plus the minimal reads the service needs; no org-wide admin
    - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - [x] 5.2 Author the per-account budgets
    - `for_each = toset(var.account_ids)`; `budget_type = "COST"`, `limit_amount`/`limit_unit` from vars, `cost_filter` `LinkedAccount = [each.key]`
    - Required notify-only `notification` subscribing every `var.notification_emails` at `freeze_threshold_percent`; an optional `dynamic "notification"` for `var.notify_threshold_percent` when non-null
    - _Requirements: 7.1, 8.3, 8.4, 8.5_
  - [x] 5.3 Author the per-account AUTOMATIC SCP freeze actions
    - `for_each = toset(var.account_ids)`; `approval_model = "AUTOMATIC"`, `execution_role_arn` from 5.1, `action_threshold` at `freeze_threshold_percent`
    - `scp_action_definition` referencing the freeze policy with `target_ids = [each.key]` (the single breaching account, never the OU); EMAIL subscriber(s) from `notification_emails`
    - Confirm the exact SCP `action_type` enum and `scp_action_definition` nesting against the installed `hashicorp/aws` provider version during execution
    - _Requirements: 7.2, 7.3, 7.4, 7.5_
  - [x] 5.4 Property test — each budget action freezes only its own account
    - **Property 2: Each budget action freezes only its own account**
    - Over a multi-account `account_ids` set, assert every action's `scp_action_definition.target_ids` equals exactly `[its own account]` (never the OU, never another account) and references the freeze policy and the execution role
    - **Validates: Requirements 7.4, 7.5**
  - [x] 5.5 Property test — every notification email is subscribed notify-only on every budget
    - **Property 3: Every notification email is subscribed notify-only on every budget**
    - Over a non-empty `notification_emails` list and a multi-account set, assert each account's budget renders a notify-only notification whose email subscriber set equals the full list
    - **Validates: Requirements 8.3**
  - _Verify:_ `tofu validate` passes; a sample `tofu plan` shows 1 role, N budgets, and N AUTOMATIC SCP actions each targeting its own account and referencing the freeze policy + role.

- [x] 6. Checkpoint — stack config validates end to end
  - Run `tofu fmt -check`, `tofu validate`, and a sample-tfvars `tofu plan`; confirm the plan shape (1 OU, N placements, 2 SCPs with only the guardrail attached, 1 role, N budgets, N AUTOMATIC actions). Ensure all checks pass; ask the user if questions arise.

- [x] 7. Implement `outputs.tf`
  - Author outputs: `workshop_ou_id`, `workshop_ou_arn`, `workshop_ou_name`, `kiro_guardrail_scp_id`, `freeze_scp_id`, `budgets_execution_role_arn`, and `per_account_budgets` (map keyed by account id → `{ budget_name, action_id }`)
  - _Requirements: 2.1, 4.1, 5.1, 6.1, 7.1 (operator wiring; supports verification of plan shape)_
  - _Verify:_ `tofu validate` passes.

- [x] 8. Add the governance `mise` lifecycle tasks
  - [x] 8.1 Add `governance-plan`, `governance-apply`, and `governance-destroy` to `mise.toml`
    - Reuse the **exact** shared `WORKSHOP_ID` guard from the subscription/claim tasks: strip whitespace → fail if empty → slug regex via `grep -Eq` → reject `--` → `backend.hcl` must exist (named in the error) → reject a `key` line in `backend.hcl`
    - All run `dir = "governance/terraform"`, `export TF_VAR_workshop_id="$WID"`, and `tofu init -reconfigure -backend-config=backend.hcl -backend-config="key=workshops/${WID}/governance/terraform.tfstate"`
    - `governance-plan`: guards → init → `tofu plan` (mutates nothing). `governance-apply`: same guards + init → `tofu apply` (prompts; no `-auto-approve`) → echo outputs. `governance-destroy`: prepend a typed-phrase gate reading exactly `destroy-governance` (mirrors `foundation-destroy`) → same init → `tofu destroy` (its own prompt)
    - Add **no** `governance-unfreeze` task and **no** task that detaches the freeze SCP
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 15.2, 15.3_
  - [x] 8.2 Confirm the guards fail closed
    - Assert `governance-plan` exits non-zero on unset/whitespace/bad-slug/`--` `WORKSHOP_ID`, on missing `backend.hcl` (naming the file), and on a `key`-bearing `backend.hcl`; and `governance-destroy` with a wrong phrase destroys nothing; a dry-run plan works with valid inputs
    - _Requirements: 12.4, 13.1, 13.2, 13.3, 13.4, 13.5_
  - _Verify:_ guard failures exit non-zero and run no tofu; a valid-input `governance-plan` reaches a non-mutating plan.

- [x] 9. Extend the `backend/` bootstrap for governance
  - Add `governance` to the `_backend_hcl_for` map in `backend/terraform/outputs.tf` and emit a `backend_hcl_governance` output
  - Extend the `backend-bootstrap` task to write `governance/terraform/backend.hcl` from that output (mirroring the foundation write)
  - Add `.gitignore` entries for `governance/terraform/backend.hcl` and `governance/terraform/*.tfvars`
  - _Requirements: 10.1, 10.2, 10.3, 10.4_
  - _Verify:_ `cd backend/terraform && tofu validate` passes; the `backend_hcl_governance` output renders a valid keyless `backend.hcl` body; `.gitignore` covers the two new paths.

- [x] 10. Author the documentation
  - [x] 10.1 Write `governance/README.md`
    - Concepts (one OU per workshop; the deny-by-default Kiro guardrail with `var.kiro_allowed_actions` noted as a **tunable** starting point; the automatic per-account budget freeze); management-account / delegated Org-admin creds via `var.aws_profile` (the same management-account profile every stack now uses; SCPs/budgets still target the member accounts); the all-features + `SERVICE_CONTROL_POLICY`-type Step 0 the stack cannot perform; account creation out of scope; high-blast-radius apply note
    - _Requirements: 4.5, 14.1, 14.2, 16.2_
  - [x] 10.2 Write `governance/RUNBOOK.md`
    - Legend; Step 0 precondition + the auth/policy-type error it surfaces; backend bootstrap; plan/apply with the chosen account-placement mechanism + `moveAccount` fallback; automatic freeze behavior; the **manual** un-freeze detach with no automation; typed-phrase (`destroy-governance`) teardown with the empty-OU / detach note; verification-only note
    - _Requirements: 14.1, 14.2, 14.4, 15.1, 15.2, 15.3, 16.1, 16.2, 16.3_
  - [x] 10.3 Update the root `README.md`
    - Add a documentation-index row linking `governance/README.md` and `governance/RUNBOOK.md`, and a repo-layout tree entry for `governance/` (OU + guardrail SCP + freeze SCP + per-account budgets, management-account creds, shared backend key `workshops/<id>/governance/terraform.tfstate`)
    - _Requirements: 11.1, 16.2_
  - _Verify:_ doc review — every documented task/variable/output exists in the code; internal links resolve.

- [x] 11. Final checkpoint — whole-stack verification (no apply)
  - Run `tofu fmt -check` and `tofu validate` across `governance/terraform` and `backend/terraform`
  - Run a sample-tfvars `tofu plan` (placeholder `parent_id`, two 12-digit `account_ids`, `notification_emails`) and assert the whole-stack plan shape: 1 OU, N placements (set == supplied ids, no extras), 2 SCPs with only the guardrail attached, 1 budgets execution role, N budgets, N AUTOMATIC SCP actions each targeting its own account
  - Re-confirm the negative variable-validation cases (bad slug, non-12-digit account, empty `notification_emails`)
  - **Explicitly NO `tofu apply` / `destroy`.** Ensure all checks pass; ask the user if questions arise.
  - _Requirements: 16.1, 16.3_

## Notes

- Tasks marked with `*` are optional (the property/validation/guard verification sub-tasks) and can be skipped for a faster MVP; they are not implemented automatically.
- Verification is strictly `tofu fmt` / `tofu validate` / `tofu plan`. **No task applies to the live organization** — apply requires the operator's explicit go-ahead because the blast radius on the management account is high.
- Each task references the specific requirement clauses it satisfies for traceability; every requirement (1–16) is covered by at least one task.
- Properties 1–3 from the design are exercised as plan-output / policy-document assertions over varied tfvars, complementing the structural plan-shape assertions.
- Account placement, the SCP budget-action `action_type` enum, and the placement primitive are confirmed against the installed `hashicorp/aws` provider version during execution; the design intent is fixed.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "9"] },
    { "id": 2, "tasks": ["2.2", "3", "4.1", "5.1"] },
    { "id": 3, "tasks": ["4.2", "5.2"] },
    { "id": 4, "tasks": ["5.3"] },
    { "id": 5, "tasks": ["5.4", "5.5", "7"] },
    { "id": 6, "tasks": ["8.1", "10.1", "10.2", "10.3"] },
    { "id": 7, "tasks": ["8.2"] }
  ]
}
```
