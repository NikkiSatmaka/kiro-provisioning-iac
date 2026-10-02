# Implementation Plan: Credential Claim Service

## Overview

Build the Credential Claim Service as a self-contained `claim-service/` subtree:
a Python 3.12 Lambda (served by one Function URL) that distributes
pre-provisioned Kiro IdC credentials race-proof, a single-table DynamoDB model,
OpenTofu infrastructure reusing the shared state bucket under a distinct key,
operator scripts for seeding and audit, and mise tasks wiring it together.

The correctness core — a single `TransactWriteItems` with two conditional
writes — is built and tested early (unit + property + concurrency) so every
later layer builds on a proven claim path. Infrastructure is authored after the
handler so the Lambda packaging and IAM scope match the real handler surface.

Each task builds on the previous ones and ends by wiring new code into the
handler, the scripts, or the Terraform graph so there is no orphaned code.

## Tasks

- [x] 1. Scaffold the `claim-service/` subtree
  - [x] 1.1 Create directory structure and placeholder files
    - Create `claim-service/{terraform,lambda,scripts,frontend,output}/`
    - Add `claim-service/output/.gitkeep`
    - Create `claim-service/README.md` skeleton with a "Run order" heading
      (deploy-plan → deploy → seed → audit → destroy), to be filled in task 12.1
    - Create a Python test layout: `claim-service/tests/__init__.py` and a
      `pytest.ini` (or `pyproject` test config) scoped to `claim-service/`
    - _Requirements: 10.1, 14.4_

  - [x] 1.2 Add `.gitignore` entries for local-only artifacts
    - Add `claim-service/output/` (audit CSVs) and
      `claim-service/terraform/backend.hcl` to the repo `.gitignore`
    - Verify the tracked `backend.hcl.example` is NOT ignored
    - _Requirements: 7.2, 13.3_

- [x] 2. DynamoDB single-table infrastructure
  - [x] 2.1 Author `terraform/dynamodb.tf`
    - Define one `aws_dynamodb_table` with partition key `PK` (string),
      `billing_mode = PAY_PER_REQUEST`
    - Enable TTL on the `ttl` attribute (for `RATE#` items)
    - Document the `CRED#`, `EMAIL#`, `RATE#` item shapes in comments
    - Add table name + ARN usage to `locals`/outputs as needed for later IAM
    - _Requirements: 9.2, 12.2_

- [x] 3. Backend wiring (shared bucket, distinct key)
  - [x] 3.1 Author partial backend config
    - Create `terraform/backend.tf` with a value-free `backend "s3" {}` block
    - Create `terraform/backend.hcl.example` setting
      `bucket = "kiro-tofu-state-<account_id>"`,
      `key = "claim-service/terraform.tfstate"`, `region = "ap-southeast-1"`
    - Add a `terraform/providers.tf` / `versions.tf` pinning the AWS provider
      and region `ap-southeast-1`; confirm NO `backend-bootstrap/` directory
      here — the shared bucket is created by the `backend/` stack
    - _Requirements: 10.1, 10.2, 4.2_

- [ ] 4. Core claim path — the correctness core
  - [x] 4.1 Implement email + request helpers in `lambda/claim_handler.py`
    - Implement `normalize_email` (lowercase + strip) and `is_valid_email`
      (non-empty local part, single `@`, non-empty domain)
    - Implement `ClaimError` (carries HTTP status + message) and `parse_post`
      (JSON body parse, missing-field → `ClaimError(400)`)
    - _Requirements: 1.3, 1.4, 1.5, 13.2_

  - [x] 4.2 Write property test for malformed-email rejection
    - **Property 1: Malformed emails are rejected without a write**
    - **Validates: Requirements 1.3**

  - [x] 4.3 Write property test for email normalization
    - **Property 2: Email normalization is idempotent and is the sole key**
    - **Validates: Requirements 1.5, 13.1**

  - [x] 4.4 Implement `pick_available` and the claim transaction
    - `pick_available()`: `Scan` with `FilterExpression status = :available`,
      return one `username` or `None`
    - `claim(email)`: pick → build a single `TransactWriteItems` with a
      conditional `Put` of `EMAIL#` (`attribute_not_exists(PK)`) and a
      conditional `Update` of `CRED#` (`status = "available"`); no
      read-then-write on the uniqueness check
    - _Requirements: 2.1, 2.2, 2.3, 4.1, 4.2, 8.1, 8.2, 8.3_

  - [ ] 4.5 Write unit tests for the single-transaction shape (mocked DynamoDB)
    - Assert exactly one `transact_write_items` call with the two conditional
      writes; assert claim success returns `username`, `otp`, `sign_in_url`,
      `region = ap-southeast-1`
    - _Requirements: 2.3, 4.1, 4.2, 8.3_

  - [ ] 4.6 Write property test for successful-claim contents
    - **Property 7: Successful claims return the assigned credential's fields**
    - **Validates: Requirements 4.1, 4.2**

  - [x] 4.7 Implement `TransactionCanceledException` reason mapping, reclaim, retry
    - Inspect `CancellationReasons`: email-lock `ConditionalCheckFailed` →
      `reclaim(email)` (read `EMAIL#` → load `CRED#` → return same credential,
      200); credential `ConditionalCheckFailed` → retry `pick_available` up to
      `RETRY_BOUND`; both failed → email-lock wins; exhaustion → `ClaimError(409)`
    - _Requirements: 2.4, 2.5, 3.1, 3.2, 5.1, 5.2_

  - [ ] 4.8 Write property test for bounded retry on credential conflict
    - **Property 5: Credential conflicts retry within the bound**
    - **Validates: Requirements 2.4**

  - [ ] 4.9 Write property test for idempotent re-claim
    - **Property 6: Re-claim is idempotent**
    - **Validates: Requirements 2.5, 3.1, 3.2**

  - [ ] 4.10 Write property test for exhaustion
    - **Property 8: Exhaustion returns 409 and mutates nothing**
    - **Validates: Requirements 5.1, 5.2**

  - [ ] 4.11 Write property test for PII placement
    - **Property 14: Email is stored only in the two permitted places**
    - **Validates: Requirements 13.1**

- [ ] 5. Checkpoint - claim core
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Per-IP attempt cap
  - [x] 6.1 Implement `check_and_increment_ip` in `claim_handler.py`
    - Atomic `UpdateItem` ADD on `RATE#<source_ip>` with a `ttl` set on first
      write; raise `ClaimError(429)` when count exceeds `PER_IP_CAP`
    - Source the IP from the Function URL event; wire the call into the pipeline
      before `claim()`
    - _Requirements: 12.2_

  - [ ] 6.2 Write property test for the per-IP cap
    - **Property 13: The per-IP cap triggers 429**
    - **Validates: Requirements 12.2**

- [ ] 7. Handler HTTP layer and gate ordering
  - [ ] 7.1 Implement `check_workshop_code` and the top-level `handler` routing
    - `check_workshop_code` → `ClaimError(403)` when absent/incorrect
    - `handler`: route on HTTP method (GET → page, POST → claim, else 405);
      enforce pipeline order parse(400) → workshop code(403) → email format(400)
      → per-IP cap(429) → claim(200/409/idempotent 200); convert `ClaimError`
      to the JSON error envelope; catch-all → 500 with no PII in logs
    - _Requirements: 1.2, 1.4, 12.1_

  - [ ] 7.2 Write unit tests for each gate branch and response shape
    - Missing field → 400; bad/absent code → 403; malformed email → 400; over
      cap → 429; non-GET/POST → 405; assert rejected requests perform zero
      credential/email writes
    - _Requirements: 1.4, 5.2, 12.1_

  - [ ] 7.3 Write property test for the workshop-code gate
    - **Property 12: A bad workshop code is rejected without a write**
    - **Validates: Requirements 12.1**

- [ ] 8. Frontend page served inline
  - [x] 8.1 Create `frontend/index.html`
    - Email input + workshop-code input; `fetch` POST of the two fields as JSON
      to the same URL; render credential (username, OTP, sign-in URL, region) or
      the error message from the response body; no external assets
    - _Requirements: 1.1_

  - [ ] 8.2 Wire `render_page` to serve the inlined HTML on GET
    - Read `index.html` at import time from the sibling file bundled in the zip;
      `render_page(allowed_origin)` returns 200 `text/html`
    - _Requirements: 1.1_

  - [ ] 8.3 Write unit test for the GET branch
    - Assert 200 `text/html` containing an email field and a workshop-code field
    - _Requirements: 1.1_

- [ ] 9. Lambda and IAM infrastructure
  - [ ] 9.1 Author `terraform/variables.tf` and `terraform/lambda.tf`
    - `variables.tf`: table name, `workshop_code`, `allowed_origin`,
      `retry_bound`, `per_ip_cap`
    - `lambda.tf`: zip packaging of `claim_handler.py` + `index.html`, Python
      3.12 function (128 MB, ~10 s timeout), env vars (`TABLE_NAME`,
      `WORKSHOP_CODE`, `ALLOWED_ORIGIN`, `RETRY_BOUND`, `PER_IP_CAP`), an
      `aws_lambda_function_url` (`authorization_type = NONE`) with CORS
      `allow_origins` = the Function URL origin, and a least-privilege IAM role
      (5 DynamoDB actions scoped to the one table ARN + basic execution)
    - _Requirements: 9.1, 12.3, 10.3, 2.4, 5.1, 12.1, 12.2_

  - [ ] 9.2 Author `terraform/outputs.tf`
    - Output `function_url`
    - _Requirements: 1.1, 9.1_

  - [ ] 9.3 Write infrastructure smoke assertions (plan/snapshot inspection)
    - Exactly one `aws_lambda_function_url` and no API Gateway resources;
      `billing_mode = PAY_PER_REQUEST`; no WAF; backend key
      `claim-service/terraform.tfstate` with value-free `backend.tf` and tracked
      `backend.hcl.example`; no bootstrap directory
    - _Requirements: 9.1, 9.2, 9.3, 10.1, 10.2_

- [x] 10. Operator scripts
  - [x] 10.1 Implement `scripts/seed_claim_pool.py`
    - Read `username,otp` from `otps.csv` and `sign_in_url` + `region` from
      `manifest.json`; conditional `PutItem` (`attribute_not_exists(PK)`) a
      `CRED#<username>` with `status = "available"` per valid row; report + skip
      rows missing a username or OTP
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 10.2 Write property test for seeding valid rows
    - **Property 9: Seeding writes one available credential per valid row**
    - **Validates: Requirements 6.2**

  - [x] 10.3 Write property test for invalid-row handling
    - **Property 10: Invalid seed rows are reported and skipped**
    - **Validates: Requirements 6.3**

  - [x] 10.4 Implement `scripts/export_audit.py`
    - `Scan` with `FilterExpression begins_with(PK, "EMAIL#")`; write
      `email,username,claimed_at` rows to
      `claim-service/output/audit-<timestamp>.csv` (git-ignored); recover email
      by stripping the `EMAIL#` prefix
    - _Requirements: 7.1, 7.2, 13.3_

  - [x] 10.5 Write property test for the audit export
    - **Property 11: The audit export covers every claimed email**
    - **Validates: Requirements 7.1**

- [ ] 11. Checkpoint - scripts and infrastructure
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Operator wiring and concurrency validation
  - [ ] 12.1 Add mise tasks to the root `mise.toml` and finish the README
    - Tasks: `claim-seed` (seed_claim_pool.py), `claim-audit`
      (export_audit.py), `claim-deploy-plan`
      (`tofu init -backend-config=backend.hcl && tofu plan`, applies nothing),
      `claim-deploy` (`tofu apply`, prompts — no `-auto-approve`),
      `claim-destroy` (`tofu destroy`, prompts)
    - Fill in `claim-service/README.md` run order:
      deploy-plan → deploy → seed → (workshop) → audit → destroy
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 11.1_

  - [ ] 12.2 Write the race / concurrency test for the claim path
    - Launch many claims from a thread pool against a small pool: half the same
      email, half contending for the same credential; assert no username bound
      to two emails and at most one `EMAIL#` item per email
    - **Property 3: No credential is double-assigned** (Requirements 2.1, 8.1)
    - **Property 4: No email claims twice** (Requirements 2.2, 8.2)
    - _Requirements: 8.1, 8.2, 8.3_

- [ ] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; they
  are the unit, property, and smoke tests.
- Each task references specific requirements for traceability.
- Checkpoints ensure incremental validation of the claim core, scripts, and
  infrastructure.
- Property tests validate the universal correctness properties from the design
  (run ≥ 100 iterations, tagged `Feature: credential-claim-service, Property n`).
- The concurrency test (12.2) is the correctness core and is NOT optional — it
  backs the race-proofness guarantee, so it is left unmarked.
- Infrastructure correctness is checked by plan/snapshot smoke assertions, not
  property tests (declarative, not input-varying).
- No manual AWS console steps appear as tasks; deploy/seed/audit/destroy are all
  code (mise tasks + scripts).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1", "3.1"] },
    { "id": 1, "tasks": ["4.1", "8.1", "10.1", "10.4"] },
    { "id": 2, "tasks": ["4.2", "4.3", "4.4", "6.1", "10.2", "10.3", "10.5"] },
    { "id": 3, "tasks": ["4.5", "4.6", "4.7", "6.2"] },
    { "id": 4, "tasks": ["4.8", "4.9", "4.10", "4.11", "7.1"] },
    { "id": 5, "tasks": ["7.2", "7.3", "8.2"] },
    { "id": 6, "tasks": ["8.3", "9.1"] },
    { "id": 7, "tasks": ["9.2", "9.3", "12.1"] },
    { "id": 8, "tasks": ["12.2"] }
  ]
}
```
