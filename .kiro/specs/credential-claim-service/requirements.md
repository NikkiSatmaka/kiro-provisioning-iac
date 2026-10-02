# Requirements Document

## Introduction

The Credential Claim Service is a self-serve, opt-in distribution mechanism for
Kiro IAM Identity Center (IdC) credentials at a workshop. A pool of
pre-provisioned credentials is seeded into a DynamoDB table; each participant
scans a QR code or opens a short link, enters an email, and receives exactly one
username and one-time password (OTP). Correctness under contention is the top
priority: concurrent claims must never double-assign a credential, and no email
may claim more than one credential.

This service is a self-contained subtree inside the existing
`kiro-provisioning-iac` repository. It must not alter or depend on the existing
`subscription/` provisioning flow, and it must be independently destroyable without
touching provisioned identities. The claim page and the claim API are served
from a single AWS Lambda Function URL (one URL, one QR). Terraform/OpenTofu
state for this service reuses the existing shared S3 state bucket under a
distinct key so the service remains isolated and independently destroyable.
Operator actions are wrapped as mise tasks in the root `mise.toml`, mirroring
the `subscription/` dry-run-first conventions.

Provisioning IdC users and generating OTPs are out of scope; they remain in
`subscription/`. The deployment region is `ap-southeast-1`.

## Glossary

- **Claim_Service**: The deployed system comprising the DynamoDB table, the
  Lambda function, and the Lambda Function URL that together distribute
  credentials to participants.
- **Claim_Handler**: The Lambda function behind the Function URL that serves the
  claim page on GET and processes a claim on POST.
- **Function_URL**: The single public AWS Lambda Function URL that serves both
  the claim page (GET) and the claim endpoint (POST).
- **Claim_Pool**: The set of credential items in the DynamoDB table, each
  representing one IdC user available to be claimed.
- **Credential_Item**: A DynamoDB item keyed `CRED#<username>` holding
  `username`, `otp`, `sign_in_url`, `region`, `status`, and (once claimed)
  `claimed_by_email` and `claimed_at`.
- **Email_Lock_Item**: A DynamoDB item keyed `EMAIL#<normalized_email>` written
  at claim time to enforce one claim per email, holding `username` and
  `claimed_at`.
- **Normalized_Email**: A participant email lowercased and trimmed of leading
  and trailing whitespace, used as the uniqueness key for an email.
- **Workshop_Code**: A shared secret string checked inside the Claim_Handler to
  gate access to the claim operation.
- **Seed_Script**: The operator script that populates the Claim_Pool from
  `manifest.json` and `otps.csv`.
- **Audit_Export**: A CSV produced by the operator mapping each claimed email to
  its username and claim timestamp.
- **Operator**: The workshop host who seeds the pool, deploys the service,
  exports the audit, and tears the service down.
- **Participant**: A workshop attendee who claims one credential.
- **Claim_Transaction**: A single DynamoDB `TransactWriteItems` operation
  containing two conditional writes that commit or fail together.

## Requirements

### Requirement 1: Claim a credential via the web form

**User Story:** As a participant, I want to claim one credential by submitting
my email on a web form reached from a QR code or short link, so that I receive
my own Kiro sign-in details without an operator handing them out.

#### Acceptance Criteria

1. WHEN a GET request is received at the Function_URL, THE Claim_Handler SHALL return an HTML claim page containing an email input field.
2. WHEN a Participant submits the claim form with an email and the configured Workshop_Code, THE Claim_Handler SHALL process the submission as a POST request to the Function_URL.
3. WHERE a submitted email omits a local part, an "@" separator, or a domain part, THE Claim_Handler SHALL return HTTP 400 with an error body and SHALL NOT create an Email_Lock_Item.
4. IF a POST request omits the email field or the Workshop_Code field, THEN THE Claim_Handler SHALL return HTTP 400 with an error body.
5. THE Claim_Handler SHALL normalize a submitted email to a Normalized_Email before using the email in any DynamoDB operation.

### Requirement 2: One credential per credential, one claim per email

**User Story:** As a workshop host, I want each credential claimed by at most
one email and each email to claim at most one credential, so that credentials
are distributed uniquely and fairly.

#### Acceptance Criteria

1. THE Claim_Service SHALL assign each Credential_Item to at most one Normalized_Email for the lifetime of the Claim_Pool.
2. THE Claim_Service SHALL permit each Normalized_Email to claim at most one Credential_Item for the lifetime of the Claim_Pool.
3. WHEN a Participant submits a claim, THE Claim_Handler SHALL execute a single Claim_Transaction containing a conditional Put of the Email_Lock_Item with condition `attribute_not_exists(PK)` and a conditional Update of the selected Credential_Item with condition `status = "available"`.
4. IF the conditional Update of the Credential_Item fails because its `status` is not `"available"`, THEN THE Claim_Handler SHALL retry the claim against another available Credential_Item up to a bounded retry limit.
5. IF the Claim_Transaction fails because the Email_Lock_Item already exists, THEN THE Claim_Handler SHALL treat the submission as an idempotent re-claim per Requirement 4.

### Requirement 3: Idempotent re-submission

**User Story:** As a participant who closed the tab and re-scanned the QR code,
I want submitting my email again to return the same credential, so that I do not
lose access or consume a second credential.

#### Acceptance Criteria

1. WHEN a Participant submits an email whose Normalized_Email already has an Email_Lock_Item, THE Claim_Handler SHALL read the `username` from that Email_Lock_Item, load the matching Credential_Item, and return that same Credential_Item.
2. WHEN the Claim_Handler returns an idempotent re-claim, THE Claim_Handler SHALL return HTTP 200 and SHALL NOT assign a second Credential_Item to the Normalized_Email.

### Requirement 4: Successful-claim response contents

**User Story:** As a participant, I want a successful claim to show me my
username, OTP, sign-in URL, and region, so that I can sign in to Kiro.

#### Acceptance Criteria

1. WHEN a claim succeeds, THE Claim_Handler SHALL return HTTP 200 with a body containing the `username`, `otp`, `sign_in_url`, and `region` of the assigned Credential_Item.
2. THE Claim_Handler SHALL set the `region` returned in a successful claim to `ap-southeast-1`.

### Requirement 5: Pool exhaustion

**User Story:** As a participant arriving after all credentials are taken, I want
a clear "all claimed" message, so that I understand no credential is available.

#### Acceptance Criteria

1. IF no Credential_Item with `status = "available"` remains after the bounded retry limit is reached, THEN THE Claim_Handler SHALL return HTTP 409 with an "all claimed" error message.
2. WHEN the Claim_Handler returns an exhaustion response, THE Claim_Handler SHALL NOT create or modify any Credential_Item or Email_Lock_Item.

### Requirement 6: Seed the claim pool

**User Story:** As a workshop host, I want to seed the pool from the existing
`otps.csv` and `manifest.json`, so that provisioned credentials become
claimable.

#### Acceptance Criteria

1. WHEN the Operator runs the Seed_Script, THE Seed_Script SHALL read usernames and OTPs from `otps.csv` and the sign-in URL and region from `manifest.json`.
2. WHEN the Seed_Script seeds the Claim_Pool, THE Seed_Script SHALL write one Credential_Item per IdC user with `status = "available"`.
3. IF a row in `otps.csv` lacks a username or an OTP, THEN THE Seed_Script SHALL report the invalid row and SHALL NOT write a Credential_Item for that row.

### Requirement 7: Export audit before teardown

**User Story:** As a workshop host, I want to export who claimed what before
teardown, so that I retain a record of credential distribution.

#### Acceptance Criteria

1. WHEN the Operator runs the audit export, THE Claim_Service SHALL produce an Audit_Export mapping each claimed Normalized_Email to its `username` and `claimed_at` timestamp.
2. THE Claim_Service SHALL write the Audit_Export to a path that is excluded from version control.

### Requirement 8: Race-proof concurrency

**User Story:** As a workshop host running a room full of simultaneous scans, I
want claims to be correct under contention, so that no credential is
double-assigned and no email claims twice even during a burst.

#### Acceptance Criteria

1. WHEN multiple claims target the same Credential_Item concurrently, THE Claim_Service SHALL assign that Credential_Item to at most one Normalized_Email.
2. WHEN multiple claims submit the same Normalized_Email concurrently, THE Claim_Service SHALL create at most one Email_Lock_Item for that Normalized_Email.
3. THE Claim_Handler SHALL enforce both uniqueness constraints through the conditional writes of a single Claim_Transaction without a read-then-write check on the claim path.

### Requirement 9: Low cost, no always-on compute

**User Story:** As a workshop host on a tight budget, I want the service to cost
approximately zero, so that running a workshop incurs negligible AWS charges.

#### Acceptance Criteria

1. THE Claim_Service SHALL serve both the claim page and the claim endpoint from a single Function_URL without using Amazon API Gateway.
2. THE Claim_Service SHALL use a DynamoDB table in on-demand capacity mode.
3. THE Claim_Service SHALL operate without any always-on compute component and without AWS WAF.

### Requirement 10: Opt-in isolation from provisioning

**User Story:** As a workshop host, I want the claim service isolated from the
`subscription/` provisioning flow, so that deploying or destroying it never affects
provisioned identities.

#### Acceptance Criteria

1. THE Claim_Service SHALL store its OpenTofu state in the existing shared S3 state bucket named `kiro-tofu-state-<account_id>` under the key `claim-service/terraform.tfstate`.
2. THE Claim_Service SHALL configure its backend via partial backend configuration supplied through a `backend.hcl` file, without creating a new backend bootstrap.
3. THE Claim_Service SHALL NOT modify any resource defined by the `subscription/` provisioning configuration.

### Requirement 11: Independent teardown

**User Story:** As a workshop host, I want to tear down the claim service after a
workshop, so that its infrastructure is removed while provisioned identities
remain intact.

#### Acceptance Criteria

1. WHEN the Operator destroys the Claim_Service, THE Claim_Service SHALL remove the DynamoDB table, the Lambda function, and the Function_URL.
2. WHEN the Operator destroys the Claim_Service, THE Claim_Service SHALL NOT delete or modify any IdC user, group, or membership provisioned by `subscription/`.

### Requirement 12: Abuse resistance

**User Story:** As a workshop host, I want casual abuse blocked, so that a bot or
a stray script cannot drain the pool.

#### Acceptance Criteria

1. IF a POST request carries an absent or incorrect Workshop_Code, THEN THE Claim_Handler SHALL return HTTP 403 with an error body and SHALL NOT create an Email_Lock_Item or modify a Credential_Item.
2. WHEN the number of claim attempts from a single source IP address exceeds the configured per-IP attempt cap, THE Claim_Handler SHALL return HTTP 429 with an error body.
3. THE Claim_Handler SHALL restrict cross-origin requests to the origin of the Function_URL.

### Requirement 13: PII-aware email handling

**User Story:** As a workshop host handling participant emails, I want emails
stored minimally and exports kept out of version control, so that participant
PII is protected.

#### Acceptance Criteria

1. THE Claim_Service SHALL store a Normalized_Email only in the Email_Lock_Item and in the `claimed_by_email` attribute of the assigned Credential_Item.
2. THE Claim_Handler SHALL validate a submitted email by format only and SHALL NOT perform an email verification round trip.
3. THE Claim_Service SHALL exclude the Audit_Export from version control.

### Requirement 14: Operator tasks via mise

**User Story:** As a workshop host, I want operator steps wrapped as mise tasks
in the root `mise.toml`, so that seeding, deploying, auditing, and teardown use
the same `mise run <task>` UX and dry-run-first conventions as `subscription/`.

#### Acceptance Criteria

1. THE Claim_Service SHALL provide mise tasks in the root `mise.toml` for seeding the Claim_Pool, exporting the audit, planning a deploy, applying a deploy, and destroying the service.
2. WHEN the Operator runs the deploy-plan mise task, THE deploy-plan task SHALL perform an OpenTofu plan that reports changes and applies none.
3. WHERE a mise task applies or destroys infrastructure, THE task SHALL prompt the Operator for approval before mutating any resource.
4. THE Claim_Service SHALL document the operator run order in the service README.
