# Implementation Plan: foundation-idc-service

## Overview

This plan builds the **Foundation IdC service** — a new standalone
OpenTofu/Terraform stack at `foundation/terraform/` that creates and owns the
single account-level IAM Identity Center instance every workshop's subscription
stack consumes. Work follows the design, in order, so each change builds on the
previous and ends wired into the repo's bootstrap + `mise` lifecycle, with no
hanging or orphaned code:

1. **The foundation stack files** — `versions.tf`, `providers.tf`,
   `variables.tf`, `identity_center.tf` (the single `awscc_sso_instance "this"`),
   `outputs.tf`, `backend.tf`, and `backend.hcl.example`. This re-homes the
   `awscc_sso_instance` + `awscc` provider recovered from history, plus the four
   operator-wiring outputs, offline-validated with `tofu validate`/`console`.
2. **Backend bootstrap extension** — the additive `backend_hcl_foundation`
   output and the `foundation` entry in `_backend_hcl_for`, plus one write line
   in the `backend-bootstrap` mise task. This is the ONLY change outside
   `foundation/`.
3. **mise lifecycle tasks** — `foundation-plan` / `foundation-apply` /
   `foundation-destroy` with the init-time `key=foundation/terraform.tfstate`,
   the `backend.hcl` existence + residual-`key` guards, and the typed-phrase
   `destroy-foundation` guard.
4. **Documentation** — `foundation/README.md` and `foundation/RUNBOOK.md`
   (management-account enablement precondition, create-then-wire order,
   idempotency + `tofu import`, destructive teardown note), linked from the root
   README index/journey.

Each pure derivation or guard called out in the design's **Correctness
Properties** is paired with a property-based test (pytest + Hypothesis, min 100
iterations) driving a pure Python mirror of the HCL/shell logic under `tests/`.
Everything else — the `awscc_sso_instance` creation, provider/region
resolution, backend init, re-apply idempotency — is a configuration fact or
AWS/provider behavior verified by `tofu validate`/`console` offline checks,
static text-fact assertions over the `.tf` sources, and example/fail-closed
shell tests. **Creating the IdC instance itself needs AWS and is out of scope
for the offline tests.**

**Scope boundary:** this plan makes NO changes to the subscription stack's `.tf`
files. The subscription stack keeps consuming the instance through its existing
`var.idc_instance_arn` / `var.identity_store_id` inputs.

Implementation language: **HCL / OpenTofu** for the stack, **Python** (pytest +
Hypothesis) for the pure-mirror tests, and `mise.toml` for the task layer — the
existing languages of the repository. Property-test files follow
`tests/test_*_property.py`; example/text-fact tests follow `tests/test_*.py`,
mirroring the `multi-workshop-provisioning` convention.

## Tasks

- [x] 1. Pillar 1 — The foundation stack files
  - [x] 1.1 Scaffold the backend wiring: `backend.tf` and `backend.hcl.example`
    - Create `foundation/terraform/backend.tf` as a tracked, value-free
      `terraform { backend "s3" {} }` block (identical in intent to the
      subscription stack's), with the comment pointing at the git-ignored
      `backend.hcl` supplied at `tofu init` time
    - Create `foundation/terraform/backend.hcl.example` as the tracked, keyless
      template carrying only `bucket` / `region` / `dynamodb_table` / `encrypt`
      and documenting the foundation init-time key
      `foundation/terraform.tfstate` (NO `key` line in the file body)
    - Ensure `foundation/terraform/backend.hcl` is git-ignored (extend
      `.gitignore` if the existing pattern does not already cover it)
    - _Requirements: 4.1, 4.2, 4.4_

  - [x] 1.2 Declare providers and required versions: `versions.tf`
    - Create `foundation/terraform/versions.tf` with `required_version = ">= 1.6"`
      and `required_providers` declaring `hashicorp/aws` (`>= 5.56.0`) and
      `hashicorp/awscc` (`>= 1.0.0`, the only provider that can CREATE an IdC
      instance), restoring the recovered `awscc` entry
    - Keep the `terraform {}` block to `required_version` + `required_providers`
      only; the `backend "s3" {}` partial lives in `backend.tf` (task 1.1)
    - _Requirements: 5.1, 5.2_

  - [x] 1.3 Configure both providers and the region data source: `providers.tf`
    - Create `foundation/terraform/providers.tf` with `provider "aws"` and
      `provider "awscc"`, each using `region = var.aws_region != "" ? var.aws_region : null`
      and `profile = var.aws_profile != "" ? var.aws_profile : null`
    - Give the `aws` provider a `default_tags { tags = var.default_tags }` block;
      give `awscc` no `default_tags` block (unsupported there)
    - Add `data "aws_region" "current" {}` so the `region` output reports the
      concrete resolved region
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 1.4 Declare input variables: `variables.tf`
    - Create `foundation/terraform/variables.tf` with `aws_region` (string,
      default `""`), `aws_profile` (string, default `""`), `default_tags`
      (`map(string)` with the subscription stack's default
      `Project`/`ManagedBy`/`Purpose` map), and `instance_name` (string, default
      `"kiro-login"`), each mirroring the subscription stack's wording
    - _Requirements: 1.7, 1.8, 5.3, 5.4, 5.5_

  - [x] 1.5 Create the single owned resource and locals: `identity_center.tf`
    - Create `foundation/terraform/identity_center.tf` with exactly one
      `resource "awscc_sso_instance" "this"` setting `name = var.instance_name`
      and `tags = [for k, v in var.default_tags : { key = k, value = v }]` (the
      AWSCC list-of-objects shape), plus the header comment covering the
      management-account precondition and `tofu import` note
    - Add `locals { identity_store_id = awscc_sso_instance.this.identity_store_id;
      instance_arn = awscc_sso_instance.this.instance_arn; resolved_region =
      data.aws_region.current.region }`
    - Create NO users, groups, memberships, permission sets, or account
      assignments; declare NO `data "terraform_remote_state"`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.9, 3.4_

  - [x] 1.6 Emit the four operator-wiring outputs: `outputs.tf`
    - Create `foundation/terraform/outputs.tf` with scalar-string outputs
      `instance_arn` (`local.instance_arn`), `identity_store_id`
      (`local.identity_store_id`), `region` (`local.resolved_region`), and
      `sign_in_url` (`"https://${local.identity_store_id}.awsapps.com/start"`)
    - Expose the ARN and identity store id only as outputs (never anywhere the
      subscription stack reads via remote state)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1_

  - [x] 1.7 Write property test: AWSCC tag transform is a faithful bijection
    - Add `tests/foundation_tag_transform.py` as a pure Python mirror of
      `[for k, v in var.default_tags : { key = k, value = v }]` and
      `tests/test_foundation_tag_transform_property.py`
    - **Feature: foundation-idc-service, Property 1: AWSCC tag transform is a faithful bijection with default_tags** (min 100 iterations over arbitrary `map(string)`; output list length equals map size and the set of `(key, value)` pairs equals the map entries exactly, with no extra objects)
    - **Validates: Requirements 1.9**

  - [x] 1.8 Write property test: sign_in_url is the exact portal format
    - Add `tests/foundation_sign_in_url.py` (pure mirror of the interpolation)
      and `tests/test_foundation_sign_in_url_property.py`
    - **Feature: foundation-idc-service, Property 2: sign_in_url is the exact portal format of the identity store id** (min 100 iterations over arbitrary identity-store-id strings; output equals exactly `"https://" + id + ".awsapps.com/start"` and the id is recoverable by stripping the fixed prefix/suffix)
    - **Validates: Requirements 2.4**

  - [x] 1.9 Write property test: empty-string provider selector passthrough/fallback
    - Add `tests/foundation_provider_selector.py` (pure mirror of `s != "" ? s : null`)
      and `tests/test_foundation_provider_selector_property.py`
    - **Feature: foundation-idc-service, Property 6: The empty-string provider selector passes through or falls back** (min 100 iterations over arbitrary strings; yields `None` for the empty string and the string verbatim otherwise — the same rule for `aws_region` and `aws_profile` on both providers)
    - **Validates: Requirements 5.3, 5.4, 5.5**

  - [x] 1.10 Write text-fact + offline validation test for the stack files
    - Add `tests/test_foundation_terraform_schema.py` asserting over the
      `foundation/terraform/*.tf` sources: exactly one `awscc_sso_instance "this"`;
      none of `aws_identitystore_user` / `aws_identitystore_group` /
      `aws_identitystore_group_membership` / `aws_ssoadmin_permission_set` /
      `aws_ssoadmin_account_assignment`; `required_providers` includes
      `hashicorp/awscc` and `hashicorp/aws` with the recovered constraints;
      `instance_name` default is `kiro-login` and the resource sets
      `name = var.instance_name`; `outputs.tf` declares the four outputs bound to
      the right locals/derivation; `backend.tf` is a value-free `backend "s3" {}`
      and `backend.hcl.example` carries no `key` line; no
      `data "terraform_remote_state"` is declared
    - Run offline `tofu validate` (and `tofu console` over the `sign_in_url`
      interpolation, the tag transform on a sample map, and the region/profile
      ternary on `""` vs a value) against the stack
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.4, 4.2, 4.4, 5.1, 5.2_

- [x] 2. Checkpoint - Pillar 1 (foundation stack files validate)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Pillar 2 — Backend bootstrap extension
  - [x] 3.1 Add the additive foundation backend output
    - In `backend/terraform/outputs.tf` add `foundation = local._backend_hcl_body`
      to `local._backend_hcl_for`, and add a new `output "backend_hcl_foundation"`
      bound to `local._backend_hcl_for["foundation"]` beside the existing
      `backend_hcl` / `backend_hcl_claim_service` outputs
    - Keep the body byte-identical to the other stacks (keyless; isolation comes
      from the init-time key). Make NO other change to the backend stack and NO
      change to the subscription stack
    - _Requirements: 4.5_

  - [x] 3.2 Extend the backend-bootstrap mise task to write the foundation backend.hcl
    - In `mise.toml` `[tasks.backend-bootstrap]` add a line writing
      `tofu output -raw backend_hcl_foundation > ../../foundation/terraform/backend.hcl`
      (with the matching `echo` / `cat` confirmation lines), alongside the
      existing subscription and claim-service writes
    - Update the task `description` to mention it also writes the `foundation/`
      backend.hcl
    - _Requirements: 4.5_

  - [x] 3.3 Write property test: rendered backend.hcl body is keyless and identical
    - Add `tests/foundation_backend_body.py` (pure mirror of `_backend_hcl_body`
      and `_backend_hcl_for`) and `tests/test_foundation_backend_body_property.py`
    - **Feature: foundation-idc-service, Property 3: The rendered backend.hcl body is keyless and identical across stacks** (min 100 iterations over `(bucket, region, dynamodb_table)` triples; the foundation body carries exactly those three values plus `encrypt = true`, contains no `key` line, and is byte-identical to the subscription and claim-service bodies)
    - **Validates: Requirements 4.2, 4.5, 4.7**

  - [x] 3.4 Write text-fact test for the bootstrap extension
    - Add/extend `tests/test_keyless_backend.py` (or a new
      `tests/test_foundation_backend_bootstrap.py`) asserting
      `backend/terraform/outputs.tf` declares `backend_hcl_foundation` and the
      `foundation` entry in `_backend_hcl_for`, and that the `backend-bootstrap`
      task writes `../../foundation/terraform/backend.hcl`
    - _Requirements: 4.5_

- [x] 4. Checkpoint - Pillar 2 (backend bootstrap extension)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Pillar 3 — mise lifecycle tasks
  - [x] 5.1 Add the foundation-plan task
    - In `mise.toml` add `[tasks.foundation-plan]` (`dir = "foundation/terraform"`,
      `set -eu`): `backend.hcl` existence guard (non-zero exit + message naming
      the missing file, pointing at `backend-bootstrap`), residual-`key` grep
      guard (`^[[:space:]]*key[[:space:]]*=` → non-zero exit + message that the
      key is supplied at init time), then
      `tofu init -reconfigure -input=false -backend-config=backend.hcl
      -backend-config="key=foundation/terraform.tfstate"` (fail-closed via `set -eu`
      + explicit guard) followed by `tofu plan`
    - _Requirements: 4.6, 4.7, 6.1, 6.4, 6.5_

  - [x] 5.2 Add the foundation-apply task
    - In `mise.toml` add `[tasks.foundation-apply]` mirroring `foundation-plan`'s
      guards + init, then `tofu apply` (tofu prompts for its own approval), then
      echo the `TF_VAR_idc_instance_arn` / `TF_VAR_identity_store_id` export lines
      and the `sign_in_url` / `region` from `tofu output -raw`
    - _Requirements: 4.6, 4.7, 6.2, 6.4, 6.5_

  - [x] 5.3 Add the foundation-destroy task with the typed-phrase guard
    - In `mise.toml` add `[tasks.foundation-destroy]`: FIRST prompt the operator
      to type exactly `destroy-foundation` and `read -r CONFIRM` — on mismatch
      (any other string, including empty/whitespace) exit non-zero and delete
      nothing; on match fall through to the `backend.hcl` existence + residual-`key`
      guards, the foundation-key init, then `tofu destroy` (tofu's own approval
      prompt still required)
    - Keep this task excluded from — and not referenced by — any `provision*`,
      `teardown*`, or `claim-*` task, so the foundation stays out of the
      per-workshop lifecycle
    - _Requirements: 4.6, 4.7, 6.3, 6.4, 6.5, 7.1, 7.2, 7.3, 7.4, 7.5, 7.7_

  - [x] 5.4 Write property test: residual-key guard flags exactly key-assigning files
    - Add `tests/foundation_residual_key.py` (pure mirror of the grep predicate
      `^[[:space:]]*key[[:space:]]*=`) and
      `tests/test_foundation_residual_key_property.py`
    - **Feature: foundation-idc-service, Property 4: The residual-key guard flags exactly the files that assign a key** (min 100 iterations over arbitrary `backend.hcl` texts; reports present iff a non-comment line assigns `key = ...`, and absent otherwise)
    - **Validates: Requirements 4.7**

  - [x] 5.5 Write property test: foundation state key is the fixed prefix-free constant
    - Add `tests/foundation_state_key.py` (pure mirror of the key constant) and
      `tests/test_foundation_state_key_property.py`
    - **Feature: foundation-idc-service, Property 5: The foundation state key is the fixed, prefix-free constant** (min 100 iterations; the init-time key is exactly `foundation/terraform.tfstate` and never begins with a `workshops/<id>/` segment, distinguishing it from the workshop-scoped keys)
    - **Validates: Requirements 4.3, 4.4, 6.4**

  - [x] 5.6 Write property test: teardown guard accepts exactly the fixed phrase
    - Add `tests/foundation_teardown_guard.py` (pure mirror of
      `[ "$CONFIRM" = "destroy-foundation" ]`) and
      `tests/test_foundation_teardown_guard_property.py`
    - **Feature: foundation-idc-service, Property 7: The teardown guard accepts exactly the fixed phrase** (min 100 iterations over arbitrary strings including case variants, surrounding whitespace, near-misses, and the empty string; proceeds iff the string equals exactly `destroy-foundation`, rejects everything else)
    - **Validates: Requirements 7.2, 7.3, 7.4**

  - [x] 5.7 Write text-fact + example/fail-closed tests for the mise tasks
    - Add `tests/test_foundation_mise_tasks.py` asserting `foundation-plan` /
      `foundation-apply` / `foundation-destroy` exist with the init-key argument
      `key=foundation/terraform.tfstate` and the plan/apply/destroy commands, and
      that no `provision*` / `teardown*` / `claim-*` task references
      `foundation/terraform.tfstate` or `awscc_sso_instance`
    - Add example/fail-closed cases: running a foundation task with no
      `backend.hcl` exits non-zero naming the missing file; a `backend.hcl` with a
      residual `key =` line exits non-zero; piping a non-matching phrase to
      `foundation-destroy` exits non-zero and never reaches `tofu destroy`
    - _Requirements: 4.6, 4.7, 6.1, 6.2, 6.3, 6.4, 6.5, 7.1, 7.4, 7.7_

- [x] 6. Checkpoint - Pillar 3 (mise lifecycle tasks)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Pillar 4 — Documentation and scope-boundary assertion
  - [x] 7.1 Write the foundation README and RUNBOOK
    - Create `foundation/README.md` (concepts: the single owned resource, the
      decoupling-via-variables boundary, the shared backend with the
      foundation-scoped key) and `foundation/RUNBOOK.md` matching the style of
      `backend/README.md` and `subscription/RUNBOOK.md`
    - RUNBOOK must cover: Step 0 management-account enablement precondition
      (one-time, irreversible; a missing enablement surfaces as an authorization
      error on `awscc_sso_instance`); the create-then-wire order (backend-bootstrap
      → foundation-apply → capture `instance_arn` + `identity_store_id` → export
      `TF_VAR_idc_instance_arn` / `TF_VAR_identity_store_id` or tfvars for the
      subscription stack); applied once and reused across every workshop;
      idempotency + `tofu import awscc_sso_instance.this <instance_arn>` with the
      one-instance-per-account statement; and the destructive/irreversible
      teardown note
    - _Requirements: 7.6, 8.2, 8.3, 9.1, 9.2, 9.3, 10.1, 10.2, 10.3, 10.4_

  - [x] 7.2 Link the foundation phase from the root README
    - In the root `README.md` add the foundation stack to the documentation index
      and the journey/phase table so it sits between Phase 1 (backend) and Phase 2
      (subscription), linking `foundation/README.md`
    - _Requirements: 10.1, 10.4_

  - [x] 7.3 Write scope-boundary + doc text-fact test
    - Add `tests/test_foundation_scope_boundary.py` asserting the subscription
      stack's `.tf` is unchanged by this spec and still declares
      `var.idc_instance_arn` / `var.identity_store_id`, that neither stack declares
      a `data "terraform_remote_state"` referencing the other, and (optionally)
      that the RUNBOOK/README carry the create-then-wire, `tofu import`,
      one-instance-per-account, management-account enablement, and
      destructive-teardown statements
    - _Requirements: 3.2, 3.3, 3.4, 7.6, 8.2, 8.3, 9.1, 9.3, 10.1, 10.2, 10.3, 10.4_

- [x] 8. Final checkpoint - full foundation stack + bootstrap + tasks + docs
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster
  MVP; the core stack, backend extension, mise tasks, and docs are not optional.
- Each task references specific requirement clauses for traceability.
- The 7 Correctness Properties map 1:1 to pure-mirror property tests (min 100
  iterations each via Hypothesis): P1 AWSCC tag-transform bijection → 1.9;
  P2 `sign_in_url` exact portal format → 2.4; P3 keyless backend body identical
  across stacks → 4.2/4.5/4.7; P4 residual-`key` guard predicate → 4.7; P5
  foundation state-key constant → 4.3/4.4/6.4; P6 empty-string provider selector
  → 5.3/5.4/5.5; P7 typed-phrase acceptor → 7.2/7.3/7.4.
- Everything else (the `awscc_sso_instance` creation, provider/region resolution,
  backend init, re-apply idempotency, raw-output quoting, per-workshop exclusion,
  scope boundary) is a configuration/AWS fact verified by `tofu validate` /
  `console` offline checks, static text-fact assertions, and example/fail-closed
  shell tests — not by property tests. Creating the IdC instance itself needs AWS
  and is **out of scope for offline tests**.
- `backend/terraform/outputs.tf` and `mise.toml` are the ONLY files touched
  outside `foundation/` (plus the root `README.md` link); the change is additive
  and leaves the subscription stack's `.tf` files untouched.
- Property-test files follow `tests/test_*_property.py` with their pure mirrors
  as plain `tests/foundation_*.py` modules; text-fact / example tests follow
  `tests/test_*.py`, matching the repo convention.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.4"] },
    { "id": 1, "tasks": ["1.3", "1.5"] },
    { "id": 2, "tasks": ["1.6", "1.7", "1.9", "3.1"] },
    { "id": 3, "tasks": ["1.8", "1.10", "3.2", "3.3"] },
    { "id": 4, "tasks": ["3.4", "5.1"] },
    { "id": 5, "tasks": ["5.2"] },
    { "id": 6, "tasks": ["5.3"] },
    { "id": 7, "tasks": ["5.4", "5.5", "5.6", "5.7", "7.1"] },
    { "id": 8, "tasks": ["7.2"] },
    { "id": 9, "tasks": ["7.3"] }
  ]
}
```
