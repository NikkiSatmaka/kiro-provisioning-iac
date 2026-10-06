# Implementation Plan: multi-workshop-provisioning

> **⚠️ Superseded in part — management-account consolidation.** All stacks now
> run in the **management account**. Foundation adopts the **organization** IdC
> instance read-only (no `awscc_sso_instance`); subscription namespaces group
> display names by `workshop_id` and gates account access behind
> `enable_account_access` (default false → zero console access). See
> `.agents/tasks/management-account-consolidation-plan.md` for the authoritative
> current design.

## Overview

This plan turns the single-run provisioner into a per-workshop module, extending
the `idc-region-account-mapping` baseline (region split and `account_id` flow,
assumed in place). Work follows the design's five pillars, in order, so each
change builds on the previous and ends wired into the pipeline:

1. **Consume the Foundation IdC** — stop creating the instance, add the operator
   inputs (`idc_instance_arn` / `identity_store_id`), and add the shared
   permission set + one account assignment per group.
2. **Explicit nested account > groups > users map** — add `workshop_accounts` and
   `workshop_id`, remove the count/prefix/strategy generators and the baseline
   `idc_account_map`, flatten into the `for_each` locals, and thread per-user
   `account_id` through the manifest.
3. **Workshop-keyed state in the shared S3 backend** — remove `key` from both
   `backend.hcl` files and the rendered body, and parameterize the mise tasks on
   `WORKSHOP_ID` (guard, slug check, residual-key grep, collision warning,
   `-reconfigure` before every mutating op, derived seed/audit table name).
4. **One claim service per workshop** — add `var.workshop_id`, derive all claim
   resource names from `local.name = credential-claim-<workshop_id>`, keep
   `workshop_code` distinct, and resolve the seed/audit table from `workshop_id`
   with a not-found error path.
5. **Teardown + cross-workshop isolation** — add `verify_isolation.py` with a
   pure `diff_snapshots` core and AWS-touching readers.

Each code change is paired with property-based tests (for the 11 pure/pure-mirror
Correctness Properties, min 100 iterations each via Hypothesis) or
example/integration/smoke tests (for config facts: variable validations via
`tofu validate`/`plan` on fixtures, the keyless `backend.hcl`, removed-variable
supersession, and the seed/audit not-found path). Property tests exercise pure
Python mirrors of the HCL flatten/derivation logic or run against `tofu plan`
output over generated tfvars.

Implementation language: **Python** (scripts, Lambda, tests via pytest +
Hypothesis) and **HCL / OpenTofu** (Terraform), with `.env` / `.env.example` /
`mise.toml` for the environment layer — the existing languages of the repository.
Property-test files follow `tests/test_*_property.py`; example/integration tests
follow `tests/test_*.py`.

## Tasks

- [x] 1. Pillar 1 — Consume the Foundation IdC
  - [x] 1.1 Remove the created instance and awscc provider
    - In `subscription/terraform/identity_center.tf` delete `resource "awscc_sso_instance" "this"` and the `locals { identity_store_id ...; instance_arn ... }` block that read from it
    - In `subscription/terraform/variables.tf` remove `variable "instance_name"`
    - In `subscription/terraform/providers.tf` remove the `awscc` provider block; in `subscription/terraform/versions.tf` drop the `awscc` required-provider, keeping `hashicorp/aws`
    - _Requirements: 1.1, 1.2_

  - [x] 1.2 Add the Foundation IdC input variables
    - In `subscription/terraform/variables.tf` add `idc_instance_arn` (string, no default, `length(trimspace(...)) > 0` validation naming the missing variable) and `identity_store_id` (string, no default, same validation)
    - Both suppliable only via tfvars or `TF_VAR_*`; no data-source discovery, no remote-state lookup
    - _Requirements: 1.3, 1.4, 1.6, 1.7, 8.6_

  - [x] 1.3 Point the foundation locals at the variables
    - In `subscription/terraform/locals.tf` set `identity_store_id = var.identity_store_id` and `instance_arn = var.idc_instance_arn` (replacing the removed `awscc_sso_instance.this` references)
    - Leave the `aws_identitystore_user/group/group_membership` resources reading `local.identity_store_id` unchanged
    - _Requirements: 1.5, 1.6_

  - [x] 1.4 Add the shared permission set and per-group account assignments
    - In `subscription/terraform/identity_center.tf` add one `aws_ssoadmin_permission_set "this"` bound to `var.idc_instance_arn`
    - Add `aws_ssoadmin_account_assignment "this"` with `for_each = local.groups`: `principal_type = "GROUP"` / `principal_id = aws_identitystore_group.this[each.key].group_id`, `target_type = "AWS_ACCOUNT"` / `target_id = local.group_account[each.key]`, `permission_set_arn = aws_ssoadmin_permission_set.this.arn`, `instance_arn = var.idc_instance_arn`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6_

  - [x] 1.5 Write integration test: Foundation IdC inputs and assignment wiring
    - `tofu validate` (or plan on a fixture tfvars) asserting: `idc_instance_arn`/`identity_store_id` exist with no default; empty values fail validation naming the missing variable; no `awscc_sso_instance` resource and no `awscc` provider remain; plan yields one permission set and one assignment per group
    - _Requirements: 1.1, 1.3, 1.4, 1.7, 2.1_

  - [x] 1.6 Write property test: every group maps to exactly one account assignment
    - **Feature: multi-workshop-provisioning, Property 1: every group maps to exactly one account assignment** (min 100 iterations over valid `workshop_accounts` maps; an account with G groups yields exactly G assignments, each `target_id` the account's 12-digit id)
    - **Validates: Requirements 2.2, 2.3**

- [x] 2. Checkpoint - Pillar 1 (Foundation IdC consumption)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Pillar 2 — Explicit nested account > groups > users map
  - [x] 3.1 Add `workshop_accounts` and `workshop_id` variables; remove the generators
    - In `subscription/terraform/variables.tf` add `workshop_accounts` (`map(object({ groups = map(object({ user_count = number })) }))`) with three validations: every key a 12-digit account id, every group name non-empty, every `user_count` in `0..500`
    - Add `workshop_id` (string) with the slug validation (1-63 lowercase alphanumeric + hyphens, begin/end alphanumeric, no consecutive hyphens)
    - Remove `user_count`, `group_count`, `user_prefix`, `group_prefix`, `sequence_start`, `sequence_padding`, `membership_strategy`, `user_emails`, `display_name_template`, and the baseline `idc_account_map` so any reference fails to resolve
    - _Requirements: 3.1, 3.2, 3.3, 3.8, 3.9, 8.3, 8.4, 8.6_

  - [x] 3.2 Rewrite `locals.tf` to flatten `workshop_accounts`
    - In `subscription/terraform/locals.tf` build `local.group_account` (`<account_id>:<group>` => account id), `local.groups` (`<account_id>:<group>` => `{ name }`), `local.users` (`<account_id>:<group>:<NN>` => `{ username, email=null, display_name, given_name, family_name, group_key, account_id }`), `local.memberships` (user_key => `{ user_key, group_key }`), and `local.user_account_id` (user_key => account id)
    - Build keys from account id + group name + per-group index only (no global counter) so they are deterministic and locally stable; derive `username = "<workshop_id>-<acct_last4>-<group>-<NN>"` and `display_name = "<group> participant NN"`
    - Set document-level `local.account_id` to the sole account when there is one, else `""`
    - _Requirements: 3.4, 3.5, 3.6, 3.7, 4.1_

  - [x] 3.3 Thread per-user account_id and surface workshop_id in outputs
    - In `subscription/terraform/outputs.tf` set each manifest `users[k].account_id = local.user_account_id[k]`, keep document-level `account_id = local.account_id`, and add `workshop_id = var.workshop_id` to `provisioning_manifest`
    - Halt before emitting the manifest if a user's owning account cannot be resolved, naming the participant/group
    - _Requirements: 4.2, 4.3_

  - [x] 3.4 Write property test: user and membership counts equal the declared user_count
    - **Feature: multi-workshop-provisioning, Property 2: user and membership counts equal the declared user_count** (min 100 iterations; group with user_count N yields exactly N users and N memberships placing them in that group)
    - **Validates: Requirements 3.6**

  - [x] 3.5 Write property test: flatten keys are deterministic and locally stable
    - **Feature: multi-workshop-provisioning, Property 3: flatten keys are deterministic and locally stable** (min 100 iterations; flattening twice is byte-identical, and a mutation confined to one account leaves all other accounts' keys unchanged)
    - **Validates: Requirements 3.7**

  - [x] 3.6 Write property test: flattened maps match the for_each value shapes
    - **Feature: multi-workshop-provisioning, Property 4: flattened maps match the shapes the for_each resources consume** (min 100 iterations; every `users[k]` carries the baseline fields, every `groups[gk]` is `{ name }`, every `memberships[k]` has `user_key`/`group_key` referencing existing entries)
    - **Validates: Requirements 3.4, 3.5**

  - [x] 3.7 Write property test: each participant's account_id is its owning account
    - **Feature: multi-workshop-provisioning, Property 5: each participant's account_id is its owning account** (min 100 iterations; `user_account_id[uk]` and the manifest per-user `account_id` equal the 12-digit id of the account under which the user's group is nested)
    - **Validates: Requirements 4.1, 4.3**

  - [x] 3.8 Write integration/example test: variable validations and removed-variable supersession
    - `tofu validate`/plan on fixtures: `workshop_accounts` rejects a non-12-digit key, an empty group name, and `user_count` outside `0..500`, and accepts valid input; `workshop_id` slug grammar enforced; a tfvars file still setting a removed generator or `idc_account_map` fails to resolve rather than silently taking effect; manifest carries per-user `account_id` and `workshop_id`
    - _Requirements: 3.1, 3.2, 3.3, 3.8, 3.9, 4.3_

- [x] 4. Checkpoint - Pillar 2 (nested map + per-user account resolution)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Pillar 3 — Workshop-keyed state in the shared S3 backend
  - [x] 5.1 Remove the key line from the backend configs
    - Remove the `key = ...` line from `subscription/terraform/backend.hcl`, `subscription/terraform/backend.hcl.example`, `claim-service/terraform/backend.hcl`, and `claim-service/terraform/backend.hcl.example`, leaving only bucket/region/dynamodb_table/encrypt
    - _Requirements: 5.4, 5.5_

  - [x] 5.2 Render a keyless backend body
    - In `backend/terraform/outputs.tf` update `_backend_hcl_for` / `_backend_hcl_body` so the rendered subscription and claim-service bodies omit `key` and carry only bucket, region, dynamodb_table, encrypt
    - _Requirements: 5.4, 5.5_

  - [x] 5.3 Parameterize the mise tasks on WORKSHOP_ID
    - In `mise.toml` rework `provision`, `teardown-tofu`, `claim-deploy`, `claim-destroy`, `claim-seed`, `claim-audit`: require `WORKSHOP_ID` (whitespace-only treated as unset -> error + non-zero exit + no action), slug-guard the value, grep `backend.hcl` for a residual `key =` and error if present, `head-object` the subscription state key and warn on collision, export `TF_VAR_workshop_id` (and `TF_VAR_workshop_code` where used), run `tofu init -reconfigure` with the workshop state key before every apply/destroy and fail closed if it exits non-zero, and derive the seed/audit table name as `credential-claim-${WID}`
    - _Requirements: 5.1, 5.6, 5.7, 5.8, 5.9, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 8.2, 8.4, 8.5_

  - [x] 5.4 Write property test: state keys follow the workshop-scoped scheme
    - **Feature: multi-workshop-provisioning, Property 9: state keys follow the workshop-scoped scheme** (min 100 iterations; subscription/claim-service keys are exactly `workshops/<id>/subscription/terraform.tfstate` and `.../claim-service/terraform.tfstate`, differing only in the stack segment)
    - **Validates: Requirements 5.2, 5.3, 7.4**

  - [x] 5.5 Write property test: the slug validator accepts exactly the slug grammar
    - **Feature: multi-workshop-provisioning, Property 8: the slug validator accepts exactly the specified slug grammar** (min 100 iterations over arbitrary strings; accept iff 1-63 lowercase alphanumeric + hyphens, begin/end alphanumeric, no consecutive hyphens; reject empty/whitespace/uppercase/over-length/leading/trailing/double-hyphen)
    - **Validates: Requirements 5.2, 5.8, 8.3, 8.4**

  - [x] 5.6 Write smoke/integration test: keyless backend.hcl and init-time key
    - Assert the rendered `backend.hcl` (and both `.example` files) omit a `key` line; assert `tofu init` for a fixture succeeds only with an init-time `-backend-config="key=workshops/<id>/<stack>/terraform.tfstate"`
    - _Requirements: 5.4, 5.5, 5.6, 5.9_

- [x] 6. Checkpoint - Pillar 3 (workshop-keyed state + mise tasks)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Pillar 4 — One claim service per workshop
  - [x] 7.1 Add var.workshop_id and derive claim resource names
    - In `claim-service/terraform/variables.tf` add `workshop_id` (string) with the slug validation, remove the `table_name` default, and keep `workshop_code` distinct (sensitive, required)
    - In `claim-service/terraform/dynamodb.tf` and `claim-service/terraform/lambda.tf` add `local.name = "credential-claim-${var.workshop_id}"` and derive the table name, Lambda function name, Function URL function name, role name (`${local.name}-lambda`), and policy name (`${local.name}-table-access`) from it; set handler env `TABLE_NAME = local.name` and keep `WORKSHOP_CODE = var.workshop_code` as the distinct access gate
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 8.6, 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 7.2 Resolve the seed/audit table name from workshop_id with a not-found path
    - In `claim-service/scripts/seed_claim_pool.py` resolve the table name from `workshop_id` (CLI `--table`/env), leaving the pure functions (`credential_item`, `classify_rows`, `load_rows`) untouched; catch `ResourceNotFoundException` and exit non-zero with a message naming the `workshop_id`, touching no other workshop's table
    - In `claim-service/scripts/export_audit.py` resolve the table name from `workshop_id` the same way, keep `email_item_to_row` pure, and apply the same not-found error path; keep `claim_handler._credential_response` returning exactly `{username, otp, sign_in_url, region}`
    - _Requirements: 6.5, 6.6, 7.6, 7.7_

  - [x] 7.3 Write property test: distinct workshop_ids yield fully distinct names and state keys
    - **Feature: multi-workshop-provisioning, Property 6: distinct workshop_ids yield fully distinct claim names and state keys** (min 100 iterations over two distinct valid slugs; derived table/lambda/role/policy names and both state keys share no value)
    - **Validates: Requirements 7.3, 7.5, 9.3**

  - [x] 7.4 Write property test: workshop_id is the sole namespace; workshop_code never namespaces
    - **Feature: multi-workshop-provisioning, Property 7: workshop_id is the sole namespace substring; workshop_code never namespaces** (min 100 iterations over valid `workshop_id` and arbitrary `workshop_code`; every derived name and both state keys contain the exact `workshop_id` and never the `workshop_code`)
    - **Validates: Requirements 7.2, 9.3, 9.4**

  - [x] 7.5 Write property test: claim response excludes account_id
    - **Feature: multi-workshop-provisioning, Property 11: claim response excludes account_id** (min 100 iterations over `CRED#` items including ones carrying `account_id`; `_credential_response` returns exactly `username`, `otp`, `sign_in_url`, `region` and never `account_id`)
    - **Validates: Requirements 4.7**

  - [x] 7.6 Write example test: seed/audit table resolution and not-found path
    - Assert `seed_claim_pool.py` and `export_audit.py` resolve `credential-claim-<workshop_id>` for a sample id, and that a `ResourceNotFoundException` against a missing table exits non-zero naming the `workshop_id` and touches no other workshop's table
    - _Requirements: 7.6, 7.7_

- [x] 8. Checkpoint - Pillar 4 (per-workshop claim service)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Pillar 5 — Teardown + cross-workshop isolation
  - [x] 9.1 Create verify_isolation.py with baseline/verify phases and a pure diff
    - Create `scripts/verify_isolation.py` with `--other-workshop <id> --phase {baseline|verify} --baseline <path>`: `baseline` reads another workshop's IdC groups/users, its permission set's account assignments, and its claim resources into a JSON snapshot; `verify` re-reads and diffs via a pure `diff_snapshots(before, after) -> list[str]`, exiting 0 + "unchanged" when identical and non-zero + the affected resources when they differ
    - Keep AWS access confined to the readers; keep `diff_snapshots` pure/testable
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 9.2 Write property test: isolation diff flags any removal or modification
    - **Feature: multi-workshop-provisioning, Property 10: isolation diff flags any removal or modification of another workshop's resources** (min 100 iterations over (before, after) snapshot pairs; empty result when equal, every removed/modified resource reported when they differ)
    - **Validates: Requirements 10.5, 10.6**

- [x] 10. Final checkpoint - full pipeline
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster MVP.
- Each task references specific requirement clauses for traceability.
- The 11 Correctness Properties map to pure / pure-mirror property tests (min 100
  iterations each via Hypothesis): P1 group→assignment cardinality → 2.2/2.3;
  P2 user/membership counts → 3.6; P3 deterministic + locally-stable keys → 3.7;
  P4 flattened map shapes → 3.4/3.5; P5 per-user account resolution → 4.1/4.3;
  P6 distinct workshop_ids → distinct names/state keys → 7.3/7.5/9.3; P7
  workshop_id sole namespace / workshop_code never namespaces → 7.2/9.3/9.4;
  P8 slug validator grammar → 5.2/5.8/8.3/8.4; P9 state-key scheme → 5.2/5.3/7.4;
  P10 isolation diff → 10.5/10.6; P11 claim response excludes account_id → 4.7.
- Property tests exercise pure Python mirrors of the HCL flatten/derivation logic
  (`workshop_accounts` → users/groups/memberships/group_account/user_account_id,
  the `credential-claim-<id>` name derivation, the state-key scheme, the slug
  validator, `diff_snapshots`) or run against `tofu plan` output over generated
  tfvars.
- Config / schema / wiring facts (variable existence and validation, removed-
  variable supersession, keyless `backend.hcl`, `-reconfigure` behavior, the
  seed/audit not-found path, assignment console wiring, foundation instance left
  untouched) are covered by example/integration/smoke tasks, not property tasks.
- `subscription/terraform/variables.tf` is edited by both Pillar 1 (1.1/1.2) and
  Pillar 2 (3.1); `subscription/terraform/locals.tf` by Pillar 1 (1.3) and Pillar
  2 (3.2); `identity_center.tf` by 1.1 and 1.4 — these same-file edits are
  sequenced across waves below so no two tasks write the same file in one wave.
- Property-test files follow the repo convention `tests/test_*_property.py`;
  example/integration tests follow `tests/test_*.py`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["1.4", "5.1", "5.2"] },
    { "id": 3, "tasks": ["1.5", "1.6", "3.1"] },
    { "id": 4, "tasks": ["3.2"] },
    { "id": 5, "tasks": ["3.3", "7.1"] },
    { "id": 6, "tasks": ["3.4", "3.5", "3.6", "3.7", "3.8", "5.3", "7.2", "9.1"] },
    { "id": 7, "tasks": ["5.4", "5.5", "5.6", "7.3", "7.4", "7.5", "7.6", "9.2"] }
  ]
}
```
