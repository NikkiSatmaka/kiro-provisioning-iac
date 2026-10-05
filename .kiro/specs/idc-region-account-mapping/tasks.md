# Implementation Plan: idc-region-account-mapping

## Overview

This plan implements two coordinated changes end-to-end: (1) splitting the single
region into `KIRO_REGION` (Kiro sign-in) and `IDC_REGION` (resource provisioning,
tracked by `AWS_REGION`), and (2) threading a child AWS `account_id` from a new
Terraform variable through the manifest into the seed/claim/audit pipeline and the
credentials document, while keeping it out of `otps.csv` and the participant claim
response.

Work proceeds from the environment layer inward: env config → Terraform variables,
locals, outputs, and manifest → the credentials renderer → the seed script → the
claim handler → the audit export. Each code change is paired with property-based
tests (for the 8 pure-function Correctness Properties, min 100 iterations each) or
smoke/example/integration tests (for config, schema, and wiring facts). Backward
compatibility is handled explicitly throughout: manifest fallbacks (`kiro_region`
→ `region`, `account_id` → `""`), pre-change `EMAIL#` lock items default to `""`,
and `otps.csv` stays `username,otp` unchanged.

Implementation language: **Python** (scripts, Lambda, tests via pytest + hypothesis)
and **HCL / OpenTofu** (Terraform), with `.env`/`.env.example`/`mise.toml` for the
environment layer — the existing languages of the repository.

## Tasks

- [x] 1. Environment layer: region split
  - [x] 1.1 Add region variables to `.env.example` and `.env`
    - Add `KIRO_REGION=us-east-1` with the Kiro-sign-in-only comment
    - Add `IDC_REGION=ap-southeast-1` with the resource-provisioning comment
    - Set `AWS_REGION=${IDC_REGION}` with the "tracks IDC_REGION" comment; preserve the existing `AWS_DEFAULT_REGION` mirror behavior
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 1.2 Wire region defaults and tracking in `mise.toml` `[env]`
    - `KIRO_REGION = { default = "us-east-1" }`, `IDC_REGION = { default = "ap-southeast-1" }`
    - `AWS_REGION = "{{ env.IDC_REGION }}"` (tracks IDC_REGION); keep `AWS_DEFAULT_REGION = "{{ env.AWS_REGION }}"` mirror unchanged
    - In the provisioning task(s), export `TF_VAR_kiro_region="$KIRO_REGION"` before `tofu apply` (mirror the existing `TF_VAR_workshop_code` pattern); keep `AWS_REGION` driving the provider
    - _Requirements: 1.3, 1.4, 1.5, 3.1, 3.2_

  - [x] 1.3 Write smoke/example test for env config facts
    - Assert `KIRO_REGION`/`IDC_REGION` presence and defaults, `AWS_REGION` resolving to `IDC_REGION`, and `AWS_DEFAULT_REGION` mirroring `AWS_REGION` as assembled by the task layer
    - **Property 1: AWS_REGION tracks IDC_REGION** (min 100 iterations over arbitrary region strings supplied as `IDC_REGION`)
    - **Validates: Requirements 1.3**

- [x] 2. Subscription Terraform: variables, locals, outputs, manifest
  - [x] 2.1 Add `kiro_region` and `idc_account_map` variables in `subscription/terraform/variables.tf`
    - `kiro_region` (string, default `us-east-1`) read from env via `TF_VAR_kiro_region`; documented as sign-in-only, never affecting resource region
    - `idc_account_map` (`map(string)`, default `{}`) with a `validation` block rejecting any present value not matching `^[0-9]{12}$`; absent entries allowed
    - _Requirements: 1.5, 1.6, 3.1, 3.2, 4.1, 4.2, 4.3_

  - [x] 2.2 Add account-resolution locals in `subscription/terraform/locals.tf`
    - `idc_key = "default"`; `account_id = lookup(var.idc_account_map, local.idc_key, "")`
    - `user_account_id = { for k, _ in local.users : k => local.account_id }` (per-user, map-keyed for future multi-IdC)
    - _Requirements: 5.3_

  - [x] 2.3 Add `account_id` output and extend the manifest in `subscription/terraform/outputs.tf`
    - Add `output "account_id"` = `local.account_id`
    - Add `kiro_region = var.kiro_region` and document-level `account_id = local.account_id` to `provisioning_manifest`
    - Add per-user `account_id = local.user_account_id[k]` to each `users[k]` entry; keep standalone `output "region"` meaning deployment region (do not repurpose)
    - _Requirements: 5.1, 5.2, 5.3, 2.3_

  - [x] 2.4 Write integration/example test for Terraform schema and manifest wiring
    - `tofu validate` (or plan on a fixture tfvars) asserting: both variables exist, `idc_account_map` validation rejects a non-12-digit value and accepts a valid one and `{}`; manifest JSON carries `kiro_region`, document-level `account_id`, and per-user `account_id`
    - _Requirements: 4.1, 4.2, 5.1, 5.2, 5.3_

- [x] 3. Checkpoint - env + Terraform
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Credentials renderer (`subscription/scripts/provision_passwords_and_output.py`)
  - [x] 4.1 Read new manifest fields in `_load_manifest`
    - Read `kiro_region` with fallback to `region` for old manifests; read `account_id` with default `""`
    - Do NOT add either field to the hard `required` set (older manifests must still load)
    - _Requirements: 2.1, 6.1_

  - [x] 4.2 Render region split and account fields in `_render`
    - Header: `Account ID` (document-level, `account_id or "—"`), `Region code (resources)` = `region`, `Kiro sign-in region` = `kiro_region`
    - "How to sign in" step: instruct the participant to enter the Kiro sign-in region (`kiro_region`), not the resources region
    - Per-user table: add an `Account ID` column reading `u.get("account_id") or "—"`
    - _Requirements: 1.6, 2.1, 2.2, 2.3, 6.1, 6.2, 6.3_

  - [x] 4.3 Write property test: Kiro sign-in region surfaces as KIRO_REGION
    - **Property 2** — for any manifest `kiro_region`, `_render` output presents it as the sign-in-region header AND in the sign-in instruction (min 100 iterations)
    - **Validates: Requirements 1.6, 2.1, 2.2**

  - [x] 4.4 Write property test: resource region surfaces as the deployment region
    - **Property 3** — for any manifest `region`, `_render` presents it as the resources-region field, distinct from the Kiro sign-in region (min 100 iterations)
    - **Validates: Requirements 2.3**

  - [x] 4.5 Write property test: account ID appears as a document-level header field
    - **Property 5** — for any manifest `account_id`, `_render` presents it as a document-level header field (min 100 iterations)
    - **Validates: Requirements 6.1**

  - [x] 4.6 Write property test: per-user account column reflects each user's account
    - **Property 6** — for any set of users each annotated with `account_id`, each rendered row shows that specific user's `account_id` (min 100 iterations; include divergent per-user values)
    - **Validates: Requirements 6.2, 6.3**

  - [x] 4.7 Write example test for renderer backward compatibility
    - A pre-change manifest (no `kiro_region`, no `account_id`) still loads and renders: sign-in region falls back to `region`, account cells render `—`
    - _Requirements: 2.1, 6.1_

- [x] 5. Seed script (`claim-service/scripts/seed_claim_pool.py`)
  - [x] 5.1 Read `account_id` from the manifest in `load_manifest`
    - Return `account_id` (default `""`) alongside `sign_in_url` and `region`; `region` stays the deployment region stamped on each credential
    - Build a `username -> account_id` lookup from the manifest `users` map
    - _Requirements: 5.1, 5.3_

  - [x] 5.2 Stamp `account_id` onto each `CRED#` item in `credential_item`
    - Add `account_id` to the written item; resolve per-user via the lookup, falling back to document-level `account_id`, then `""` for OTP-only rows
    - Leave `load_rows`/`classify_rows` and the `otps.csv` header (`username,otp`) untouched
    - _Requirements: 5.3, 8.1_

  - [x] 5.3 Write property test: each user record carries its IdC's account ID
    - **Property 4** — for any users + IdC-to-account mapping, each produced `CRED#` item (and the account-join lookup result) carries the user's IdC `account_id` (min 100 iterations)
    - **Validates: Requirements 5.3**

  - [x] 5.4 Write example test for seed backward compatibility
    - `otps.csv` header unchanged; a username absent from the manifest falls back to document-level `account_id` then `""`; existing OTP CSVs seed as before
    - _Requirements: 8.1_

- [x] 6. Checkpoint - renderer + seed
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Claim handler (`claim-service/lambda/claim_handler.py`)
  - [x] 7.1 Copy `account_id` onto the `EMAIL#` lock item at claim time
    - Read `cred_account_id` from the picked `CRED#` item before the transaction; add `account_id` to the `EMAIL#<email>` Put item (and the reclaim fast-path lock creation), alongside `username` and `claimed_at`
    - Keep `_credential_response` unchanged — exactly `{username, otp, sign_in_url, region}`, no `account_id`
    - _Requirements: 7.2, 8.2, 8.3_

  - [x] 7.2 Write property test: claim response excludes the account ID
    - **Property 8** — for any `CRED#` item (including one with `account_id`), `_credential_response` returns exactly `username, otp, sign_in_url, region` and no `account_id` or other internal attribute (min 100 iterations)
    - **Validates: Requirements 8.2, 8.3**

  - [x] 7.3 Write integration test: claim transaction writes account_id onto the lock
    - Simulate a claim and assert the `EMAIL#` lock item carries the picked `CRED#` item's `account_id`; confirm the participant response is still four fields
    - _Requirements: 7.2, 8.2, 8.3_

- [x] 8. Audit export (`claim-service/scripts/export_audit.py`)
  - [x] 8.1 Add `account_id` to `CSV_HEADER` and `email_item_to_row`
    - `CSV_HEADER = ("email", "username", "account_id", "claimed_at")`
    - `email_item_to_row` reads `account_id` from the `EMAIL#` item, defaulting to `""` for malformed or pre-change items
    - _Requirements: 7.1, 7.2_

  - [x] 8.2 Write property test: audit row carries the claimed credential's account ID
    - **Property 7** — for any `EMAIL#` lock item, the produced row's `account_id` equals the item's `account_id`, defaulting to `""` when absent (min 100 iterations)
    - **Validates: Requirements 7.2**

  - [x] 8.3 Write example test for audit backward compatibility
    - A pre-change `EMAIL#` item (no `account_id`) yields a row with an empty `account_id` rather than crashing; header includes the new column
    - _Requirements: 7.1_

- [x] 9. Final checkpoint - full pipeline
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster MVP.
- Each task references specific requirement clauses for traceability.
- The 8 Correctness Properties map to pure-function property tests (min 100
  iterations each) via hypothesis: Property 1 (env tracking) → 1.3; Property 2
  (`_render` sign-in region) → 4.3; Property 3 (`_render` resources region) → 4.4;
  Property 4 (account-join lookup / `credential_item`) → 5.3; Property 5
  (`_render` header account) → 4.5; Property 6 (`_render` per-user column) → 4.6;
  Property 7 (`email_item_to_row`) → 8.2; Property 8 (`_credential_response`) → 7.2.
- Config/schema/wiring facts (env presence/defaults, Terraform variable existence
  and validation, CSV column presence, provider region resolution) are covered by
  smoke/example/integration tasks, not property tasks.
- Backward compatibility is explicit: manifest fallbacks (`kiro_region` → `region`,
  `account_id` → `""`), pre-change `EMAIL#` items default `account_id` to `""`, and
  `otps.csv` stays `username,otp` with no consumer change.
- Property-test files follow the repo convention `tests/test_*_property.py`;
  example/integration tests follow `tests/test_*.py`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2"] },
    { "id": 2, "tasks": ["2.3", "1.3", "2.4"] },
    { "id": 3, "tasks": ["4.1", "5.1"] },
    { "id": 4, "tasks": ["4.2", "5.2", "7.1", "8.1"] },
    { "id": 5, "tasks": ["4.3", "4.4", "4.5", "4.6", "4.7", "5.3", "5.4", "7.2", "7.3", "8.2", "8.3"] }
  ]
}
```
