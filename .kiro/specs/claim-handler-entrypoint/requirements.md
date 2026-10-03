# Requirements Document

## Introduction

The Credential Claim Service (`claim-service/`) already carries its complete
correctness core — email helpers, body parsing, per-IP rate counting, and the
race-proof `claim`/`reclaim` transaction — plus a self-contained HTML claim
page, Terraform for a single Python 3.12 Lambda behind one Function URL, a
required+sensitive `workshop_code` variable, and seed/audit scripts. What it
does not have is the one thing that makes all of that reachable: a top-level
`handler(event, context)` entrypoint. The Lambda is wired to
`claim_handler.handler`, but that symbol does not exist, so the service is
currently undeployable.

This feature closes that implementation gap. It specifies the handler
entrypoint and the thin wiring layer around the existing building blocks:
routing the single Function URL (GET serves the page, POST runs the claim),
enforcing the workshop-code eligibility gate (required by the product but not
yet enforced anywhere), composing the POST pipeline from the existing functions,
mapping `ClaimError(status, message)` to the `{"error": message}` JSON envelope,
deriving CORS and response headers from `ALLOWED_ORIGIN`, serving the packaged
`index.html` inline, and reading the two currently-unread env vars
(`WORKSHOP_CODE`, `ALLOWED_ORIGIN`) into the module.

This feature wires an entrypoint *around* the existing correctness core; it
MUST NOT weaken the atomic one-per-email / one-per-credential guarantees or the
idempotent re-claim behavior already proven in `claim_handler.py`. It introduces
no API Gateway, no WAF, and no frontend framework or build step. Raw emails and
OTPs are never logged. The deployment region is read from the `AWS_REGION`
environment variable, defaulting to `us-east-1` when `AWS_REGION` is unset.

The existing function contracts in `claim-service/lambda/claim_handler.py` are
the ground truth for this spec: `parse_post`, `normalize_email`,
`is_valid_email`, `source_ip`, `check_and_increment_ip`, `claim`, `reclaim`, and
`ClaimError` are treated as fixed, and the handler composes them.

## Glossary

- **Claim_Handler**: The Lambda function module (`claim_handler.py`) behind the
  Function_URL. This feature adds its top-level `handler(event, context)`
  entrypoint.
- **Handler_Entrypoint**: The top-level `handler(event, context)` function that
  AWS Lambda invokes per the configured `claim_handler.handler` reference; it
  routes the request and returns a Function_URL response dict.
- **Function_URL**: The single public AWS Lambda Function URL that serves both
  the claim page (GET) and the claim endpoint (POST), authorization type NONE.
- **Function_URL_Response**: The response object the Handler_Entrypoint returns
  for a Function_URL invocation, carrying `statusCode`, `headers`, and `body`.
- **Request_Method**: The HTTP method of the incoming request, read from
  `event["requestContext"]["http"]["method"]`.
- **Claim_Page**: The self-contained `index.html` packaged as a sibling of
  `claim_handler.py` at the deployment-package root and served inline on GET.
- **Claim_Pipeline**: The ordered composition the Handler_Entrypoint runs for a
  POST: per-IP cap check, body parse, email format validation, Workshop_Code
  verification, email normalization, and claim.
- **Workshop_Code**: The shared gate secret a Participant submits with a claim,
  compared against the configured `WORKSHOP_CODE` value.
- **Configured_Workshop_Code**: The value of the `WORKSHOP_CODE` environment
  variable read by the Claim_Handler module at import.
- **Allowed_Origin**: The value of the `ALLOWED_ORIGIN` environment variable
  read by the Claim_Handler module at import; empty string means "unset".
- **Resolved_Origin**: The CORS origin the Handler_Entrypoint echoes in response
  headers — the Allowed_Origin when non-empty, otherwise `"*"` — mirroring the
  Function_URL CORS fallback in `lambda.tf`.
- **Error_Envelope**: The JSON response body `{"error": "<message>"}` returned
  for any failed request.
- **Credential_Response**: The JSON success body containing exactly the four
  fields `username`, `otp`, `sign_in_url`, and `region`.
- **ClaimError**: The existing pipeline exception carrying an HTTP `status` and
  a human-readable `message`, raised by the building-block functions.
- **Participant**: A workshop attendee who claims one credential.
- **Operator**: The workshop host who deploys, seeds, audits, and tears down the
  service, and who runs the mise tasks.

## Requirements

### Requirement 1: Handler entrypoint existence

**User Story:** As an Operator, I want a top-level handler entrypoint that AWS
Lambda can invoke, so that the service the Terraform points at is actually
deployable and runnable.

#### Acceptance Criteria

1. THE Claim_Handler SHALL expose a module-level `handler` function accepting an `event` argument and a `context` argument, resolvable as `claim_handler.handler`.
2. WHEN the Handler_Entrypoint is invoked with a Function_URL event, THE Handler_Entrypoint SHALL return a Function_URL_Response containing a `statusCode`, a `headers` map, and a `body` string.
3. WHEN the Handler_Entrypoint completes any request, THE Handler_Entrypoint SHALL return a `body` that is a string, so the Function_URL serializes it without further processing.

### Requirement 2: Request routing on the single Function URL

**User Story:** As a Participant, I want the one link to both show me the claim
page and accept my submission, so that a single QR code or URL serves the whole
flow.

#### Acceptance Criteria

1. WHEN a request arrives whose Request_Method, read from `event["requestContext"]["http"]["method"]` and compared case-insensitively, equals `GET`, THE Handler_Entrypoint SHALL return the Claim_Page with HTTP 200 and a `Content-Type` header of `text/html; charset=utf-8`.
2. WHEN a request arrives whose Request_Method, read from `event["requestContext"]["http"]["method"]` and compared case-insensitively, equals `POST`, THE Handler_Entrypoint SHALL run the Claim_Pipeline and return a JSON Function_URL_Response with HTTP 200 on successful completion of the pipeline.
3. WHEN a request arrives whose Request_Method, read from `event["requestContext"]["http"]["method"]` and compared case-insensitively, equals `OPTIONS`, THE Handler_Entrypoint SHALL return HTTP 204 with the CORS response headers and an empty body.
4. IF a request arrives whose Request_Method, read from `event["requestContext"]["http"]["method"]` and compared case-insensitively, is a non-empty value other than `GET`, `POST`, or `OPTIONS`, THEN THE Handler_Entrypoint SHALL return HTTP 405 with an Error_Envelope indicating the method is not allowed.
5. IF the Request_Method cannot be read because `event["requestContext"]["http"]["method"]` is absent, empty, or not a string, THEN THE Handler_Entrypoint SHALL treat the request as a `GET` and return the Claim_Page with HTTP 200 and a `Content-Type` header of `text/html; charset=utf-8`.

### Requirement 3: Serve the inline claim page

**User Story:** As a Participant, I want the GET response to be the full claim
page, so that I can enter my email and workshop code in a browser.

#### Acceptance Criteria

1. WHEN the Handler_Entrypoint serves a GET request, THE Handler_Entrypoint SHALL read the Claim_Page from the `index.html` file packaged as a sibling of `claim_handler.py` at the deployment-package root.
2. WHEN the Handler_Entrypoint serves a GET request, THE Handler_Entrypoint SHALL return the Claim_Page contents as the response `body`.
3. IF the `index.html` file cannot be read, THEN THE Handler_Entrypoint SHALL return HTTP 500 with an Error_Envelope.

### Requirement 4: Read the previously-unread configuration

**User Story:** As an Operator, I want the handler to read the workshop code and
allowed origin the Terraform already injects, so that the eligibility gate and
CORS policy actually take effect.

#### Acceptance Criteria

1. THE Claim_Handler SHALL read the `WORKSHOP_CODE` environment variable into the Configured_Workshop_Code at module import.
2. THE Claim_Handler SHALL read the `ALLOWED_ORIGIN` environment variable into the Allowed_Origin at module import, defaulting to an empty string when the variable is unset.

### Requirement 5: Workshop-code eligibility gate

**User Story:** As an Operator, I want a submission with the wrong or missing
workshop code rejected before any credential is touched, so that only eligible
participants from my workshop can claim.

#### Acceptance Criteria

1. WHEN a POST submission carries a Workshop_Code that is byte-for-byte equal to the Configured_Workshop_Code after trimming leading and trailing whitespace from the submitted value, THE Handler_Entrypoint SHALL permit the Claim_Pipeline to proceed to the claim step.
2. WHILE comparing the submitted Workshop_Code against the Configured_Workshop_Code, THE Handler_Entrypoint SHALL use a constant-time string comparison so that elapsed comparison time does not vary with the number of matching leading characters.
3. IF a POST submission carries a Workshop_Code that is empty after trimming leading and trailing whitespace, or carries a Workshop_Code not equal to the Configured_Workshop_Code, THEN THE Handler_Entrypoint SHALL return HTTP 403 with an Error_Envelope whose body indicates the workshop code is invalid, and SHALL NOT read or otherwise access any credential, SHALL NOT claim or normalize-for-claim the submitted email, and SHALL NOT create an email lock.
4. THE Handler_Entrypoint SHALL verify the Workshop_Code only after the per-IP cap check and after email format validation have both passed, and before the claim step begins.

### Requirement 6: POST pipeline composition and ordering

**User Story:** As a Participant, I want each failure reason reported as its own
clear status, so that a bad request, a wrong code, a rate block, and an
exhausted pool are distinguishable.

#### Acceptance Criteria

1. WHEN the Handler_Entrypoint processes a POST request, THE Handler_Entrypoint SHALL run the Claim_Pipeline in the order: per-IP cap check, body parse, email format validation, Workshop_Code verification, email normalization, claim.
2. WHEN the per-IP cap check determines the source IP has exceeded the configured per-IP cap, THE Handler_Entrypoint SHALL return HTTP 429 with an Error_Envelope and SHALL NOT parse the body, verify the Workshop_Code, or claim a credential.
3. IF body parsing determines the request body is absent, is not valid JSON, is not a JSON object, or omits the email or workshop_code field, THEN THE Handler_Entrypoint SHALL return HTTP 400 with an Error_Envelope.
4. IF the submitted email fails format validation, THEN THE Handler_Entrypoint SHALL return HTTP 400 with an Error_Envelope and SHALL NOT create an email lock or modify a credential.
5. THE Handler_Entrypoint SHALL normalize the submitted email to its canonical key form before passing the email to the claim step.
6. WHEN the claim step succeeds, THE Handler_Entrypoint SHALL return HTTP 200 with a Credential_Response.

### Requirement 7: Map pipeline errors to the JSON envelope

**User Story:** As a Participant, I want a failed claim to come back as a clear
error message the page can show, so that I know what went wrong.

#### Acceptance Criteria

1. IF any Claim_Pipeline step raises a ClaimError, THEN THE Handler_Entrypoint SHALL return a Function_URL_Response whose `statusCode` equals the ClaimError status (one of 400, 403, 409, or 429) and whose `body` is an Error_Envelope whose `error` field carries the ClaimError message verbatim.
2. IF a Claim_Pipeline step raises an exception that is not a ClaimError, THEN THE Handler_Entrypoint SHALL return a Function_URL_Response with `statusCode` 500 and a `body` that is an Error_Envelope whose `error` field carries a fixed message that excludes the raised exception's type, detail, stack trace, the submitted email, and any OTP.
3. WHEN the Handler_Entrypoint returns any Function_URL_Response carrying a JSON body, whether a success response or an Error_Envelope, THE Handler_Entrypoint SHALL set the response `Content-Type` header to `application/json`.
4. WHEN the Handler_Entrypoint returns an Error_Envelope, THE Handler_Entrypoint SHALL exclude the submitted raw email and any OTP value from both the response body and every log entry it emits for that request.

### Requirement 8: Successful-claim response contents

**User Story:** As a Participant, I want a successful claim to return my
username, OTP, sign-in URL, and region, so that the page can render my Kiro
sign-in details.

#### Acceptance Criteria

1. WHEN the claim step succeeds, THE Handler_Entrypoint SHALL return a Credential_Response containing exactly the `username`, `otp`, `sign_in_url`, and `region` fields.
2. THE Handler_Entrypoint SHALL return the Credential_Response as a JSON-encoded `body` string with HTTP 200.
3. THE Handler_Entrypoint SHALL exclude every credential attribute other than `username`, `otp`, `sign_in_url`, and `region` from the Credential_Response.

### Requirement 9: CORS and response headers

**User Story:** As a Participant whose browser enforces CORS, I want consistent
CORS headers on every response, so that the form submission and the page load
succeed from the Function URL origin.

#### Acceptance Criteria

1. WHILE the Allowed_Origin is a non-empty string, THE Handler_Entrypoint SHALL set the Resolved_Origin to the exact value of the Allowed_Origin.
2. WHILE the Allowed_Origin is an empty string, THE Handler_Entrypoint SHALL set the Resolved_Origin to the single-character value `"*"`.
3. WHEN the Handler_Entrypoint returns any response, THE Handler_Entrypoint SHALL include exactly one `Access-Control-Allow-Origin` header whose value equals the Resolved_Origin, applied identically to GET page responses, POST success responses, and all error responses.
4. WHEN the Handler_Entrypoint returns a response to an `OPTIONS` request, THE Handler_Entrypoint SHALL include an `Access-Control-Allow-Methods` header listing exactly `GET` and `POST`, and an `Access-Control-Allow-Headers` header listing exactly `content-type`.
5. WHEN the Handler_Entrypoint sets the `Access-Control-Allow-Origin` header, THE Handler_Entrypoint SHALL emit that header such that the response carries a single `Access-Control-Allow-Origin` value equal to the Resolved_Origin and no second, conflicting `Access-Control-Allow-Origin` value.

### Requirement 10: Preserve the correctness core

**User Story:** As an Operator, I want the entrypoint to wire around the existing
claim logic without altering it, so that the proven race-proof and idempotent
guarantees still hold.

#### Acceptance Criteria

1. THE Handler_Entrypoint SHALL delegate credential assignment to the existing `claim` function without adding a read-then-write uniqueness check on the claim path.
2. WHEN a Participant re-submits an email that already holds a claim, THE Handler_Entrypoint SHALL return the same Credential_Response the Participant first received, via the existing idempotent re-claim path, with HTTP 200.
3. THE Handler_Entrypoint SHALL pass only a normalized email to the claim step, preserving the email as the sole key-derivation.

### Requirement 11: Scope of operability wiring

**User Story:** As an Operator, I want this feature's scope to be explicit about
the mise tasks the README references, so that I know whether deploy/seed/audit
task wiring is delivered here or elsewhere.

#### Acceptance Criteria

1. THE claim-handler-entrypoint feature SHALL limit its scope to the Handler_Entrypoint, request routing, the Claim_Pipeline composition, response and CORS header derivation, inline Claim_Page serving, and reading the `WORKSHOP_CODE` and `ALLOWED_ORIGIN` environment variables.
2. THE claim-handler-entrypoint feature SHALL exclude the definition of the `deploy-plan`, `deploy`, `seed`, `audit`, and `destroy` mise tasks from its scope.
3. THE claim-handler-entrypoint feature SHALL record that the mise task wiring is tracked by the existing credential-claim-service spec (Requirement 14) rather than by this feature.
