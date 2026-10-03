# Implementation Plan: Claim Handler Entrypoint

## Overview

This plan adds the missing `claim_handler.handler` entrypoint and its thin
wiring layer **inside the existing** `claim-service/lambda/claim_handler.py`.
Every step composes the fixed correctness core (`normalize_email`,
`is_valid_email`, `parse_post`, `ClaimError`, `source_ip`,
`check_and_increment_ip`, `pick_available`, `claim`, `reclaim`,
`_credential_response`, the lazy `_get_table`/`_table` memoization) rather than
modifying it.

The work is test-driven and incremental: first stand up the test helper
(`make_event`) and a module-level config/page scaffold, then build each wiring
function alongside its property/unit tests, then wire the `handler` dispatch
together, and finally run the whole `claim-service` suite plus `ruff` so the
change is green before it is considered done.

All new tests live under `claim-service/tests/` and reuse the existing pytest +
Hypothesis + moto harness: `conftest.py` already puts `claim-service/lambda/`
on `sys.path` and pins `AWS_REGION` (to the `us-east-1` default
fallback) before import. POST-path
tests reuse the moto DynamoDB fixture pattern, the memoized-state reset
(`claim_handler.TABLE_NAME` / `._dynamodb` / `._table`), and the moto-5
`transact_write_items` standalone-client workaround demonstrated in
`test_claim_success_contents_property.py` and `test_per_ip_cap_property.py`.

No new third-party dependency is introduced: the handler uses only stdlib
`json`/`os`/`hmac` plus the already-present `boto3`; tests use the
already-present `pytest`/`hypothesis`/`moto`.

**Out of scope (R11):** this plan does NOT define or wire the
`deploy-plan`/`deploy`/`seed`/`audit`/`destroy` mise tasks — those belong to the
`credential-claim-service` spec (its Requirement 14). No such tasks appear
below.

## Tasks

- [x] 1. Add the Function URL event test helper
  - Add `claim-service/tests/_handler_events.py` (or a shared helper module the
    handler tests import) providing `make_event(method=None, body=None,
    source_ip="203.0.113.1", is_base64=False)` that builds the Function URL
    event shape: `{"requestContext": {"http": {...}}}`, setting
    `http["method"]` only when `method is not None` (so absent/non-string
    method cases are expressible for R2.5), always setting `http["sourceIp"]`,
    and adding `body` + `isBase64Encoded` only when a body is supplied.
  - Keep it additive and importable under the existing `sys.path` shim (no
    change to `conftest.py` required).
  - _Requirements: 1.2, 2.5_
  - _Design: Testing Strategy > "Simulating Function URL events"_

- [x] 2. Add module-level config reads and the page-cache scaffold
  - [x] 2.1 Add the config/page module-level additions to `claim_handler.py`
    - Add `CONFIGURED_WORKSHOP_CODE = os.environ.get("WORKSHOP_CODE", "")` and
      `ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "")` at import time,
      alongside the existing config reads.
    - Add `_PAGE_PATH = os.path.join(os.path.dirname(__file__), "index.html")`
      and `_PAGE_HTML: str | None = None` for the read-once page cache.
    - Add `import hmac` to the stdlib imports; do not add any new dependency.
    - _Requirements: 4.1, 4.2_
    - _Design: Components and Interfaces > "Module-level additions"; Data Models > "Module configuration"_

  - [x] 2.2 Write unit/example tests for the import-time config reads
    - Assert `claim_handler.CONFIGURED_WORKSHOP_CODE` reflects `WORKSHOP_CODE`
      and `claim_handler.ALLOWED_ORIGIN` reflects `ALLOWED_ORIGIN`, including
      the unset -> `""` default for `ALLOWED_ORIGIN` (reload the module under a
      patched environment, or assert the documented default when unset).
    - _Requirements: 4.1, 4.2_
    - _Design: Testing Strategy > "Dual approach" (import-time config reads)_

- [x] 3. Implement the read-once page loader `_load_page`
  - [x] 3.1 Add `_load_page() -> str` to `claim_handler.py`
    - Populate the module global `_PAGE_HTML` on first call by reading
      `_PAGE_PATH` with `encoding="utf-8"`; return the cached value thereafter
      (same memoization style as `_table`).
    - Let an unreadable file raise `OSError` (caught later by `html_response`);
      do not swallow it here.
    - _Requirements: 3.1, 3.2, 3.3_
    - _Design: Components and Interfaces > "`_load_page()`"_

  - [x] 3.2 Write unit/example tests for `_load_page` and the on-disk GET body
    - Resolve the expected page the same way the handler does
      (`os.path.join(os.path.dirname(claim_handler.__file__), "index.html")`)
      and assert `_load_page()` returns byte-identical contents.
    - Reset `claim_handler._PAGE_HTML = None` between read tests to re-exercise
      the first-read path.
    - _Requirements: 3.1, 3.2_
    - _Design: Testing Strategy > "Reading index.html in tests"_

- [x] 4. Implement the response builders and origin resolution
  - [x] 4.1 Add `resolve_origin`, `cors_headers`, `json_response`, `html_response`, `preflight_response`
    - `resolve_origin() -> str`: return `ALLOWED_ORIGIN` when non-empty, else
      `"*"`.
    - `cors_headers(origin)`: return a dict with exactly one
      `Access-Control-Allow-Origin` set to `origin` (the single ACAO source).
    - `json_response(status, obj, origin)`: funnel through `cors_headers`, set
      `Content-Type: application/json`, body = `json.dumps(obj)`.
    - `html_response(origin)`: call `_load_page()`; on `OSError` return
      `json_response(500, {"error": "internal error"}, origin)`; otherwise
      return 200 with `Content-Type: text/html; charset=utf-8` and the page as
      body.
    - `preflight_response(origin)`: 204, empty-string body,
      `Access-Control-Allow-Methods: GET, POST`,
      `Access-Control-Allow-Headers: content-type`, ACAO via `cors_headers`.
    - _Requirements: 3.3, 7.3, 8.2, 9.1, 9.2, 9.3, 9.4, 9.5_
    - _Design: Components and Interfaces > "Response builders"_

  - [x] 4.2 Write property test — Property 3 (OPTIONS preflight)
    - `@settings(max_examples=100, deadline=None)`.
    - Comment tag: `Feature: claim-handler-entrypoint, Property 3: OPTIONS yields the preflight response`.
    - Drive `OPTIONS` in mixed case and any `ALLOWED_ORIGIN`; assert
      `statusCode == 204`, empty-string body, ACAO == resolved origin,
      `Access-Control-Allow-Methods == "GET, POST"`,
      `Access-Control-Allow-Headers == "content-type"`.
    - _Requirements: 2.3, 9.4_
    - _Design: Correctness Properties > Property 3_

  - [x] 4.3 Write unit/example test — index.html-unreadable -> 500 (R3.3)
    - Monkeypatch `claim_handler._PAGE_HTML = None` and
      `claim_handler._PAGE_PATH` to a non-existent path, then assert the GET
      response is a 500 `Error_Envelope` with CORS + `application/json`.
    - _Requirements: 3.3_
    - _Design: Testing Strategy > "Reading index.html in tests" (read-failure edge)_

- [x] 5. Implement request-method extraction `request_method`
  - [x] 5.1 Add `request_method(event) -> str`
    - Read `event["requestContext"]["http"]["method"]` defensively; when it is
      absent, empty, or not a `str`, return the `""` sentinel; otherwise return
      `raw.upper()` for case-insensitive matching.
    - _Requirements: 2.5_
    - _Design: Components and Interfaces > "`request_method(event)`"_

  - [x] 5.2 Write property test — Property 2 (GET / unreadable method serves page, no DynamoDB)
    - `@settings(max_examples=100, deadline=None)`.
    - Comment tag: `Feature: claim-handler-entrypoint, Property 2: GET (and any unreadable method) serves the page without touching DynamoDB`.
    - Draw `GET` in mixed case plus absent/empty/non-string method values;
      assert 200, `Content-Type: text/html; charset=utf-8`, body == on-disk
      `index.html`. Assert **no DynamoDB call**: spy on
      `claim_handler._get_table` (or `claim_handler.claim`) and assert it was
      never invoked (no moto table needed on this path).
    - _Requirements: 2.1, 2.5, 3.2_
    - _Design: Correctness Properties > Property 2; Testing Strategy > "no DB call" assertions_

- [x] 6. Implement the workshop-code gate `verify_workshop_code`
  - [x] 6.1 Add `verify_workshop_code(submitted: str) -> None`
    - Trim the submitted value; raise `ClaimError(403, "invalid workshop
      code")` when empty-after-trim.
    - Compare the trimmed candidate against `CONFIGURED_WORKSHOP_CODE` with
      `hmac.compare_digest`; raise `ClaimError(403, "invalid workshop code")`
      on mismatch. Raise before any normalize/claim so a wrong code touches no
      credential.
    - _Requirements: 5.1, 5.2, 5.3_
    - _Design: Components and Interfaces > "`verify_workshop_code`"_

  - [x] 6.2 Write unit/example test — structural check that the gate uses `hmac.compare_digest` (R5.2)
    - Assert constant-time comparison is used (e.g. inspect
      `verify_workshop_code`'s source via `inspect.getsource` for
      `hmac.compare_digest`, or monkeypatch `claim_handler.hmac.compare_digest`
      with a spy and assert it is called on a present code). Wall-clock timing
      is not asserted.
    - _Requirements: 5.2_
    - _Design: Testing Strategy > "Dual approach" (structural compare_digest check)_

- [x] 7. Implement the POST pipeline `run_claim_pipeline`
  - [x] 7.1 Add `run_claim_pipeline(event) -> dict`
    - Compose in the fixed order: `source_ip(event)` ->
      `check_and_increment_ip(ip, PER_IP_CAP)` -> `parse_post(event)` ->
      `is_valid_email(fields["email"])` (raise `ClaimError(400, "email is not
      valid")` on failure) -> `verify_workshop_code(fields["workshop_code"])`
      -> `email = normalize_email(fields["email"])` -> `return claim(email)`.
    - Cap check runs **before** parse; pass only the normalized email to
      `claim`; add no read-then-write.
    - _Requirements: 5.4, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 10.1, 10.3_
    - _Design: Components and Interfaces > "`run_claim_pipeline`"_

  - [x] 7.2 Write property test — Property 5 (first-failing-step ordering)
    - `@settings(max_examples=100, deadline=None)`; moto fixture + memoized-state
      reset + `transact_write_items` workaround.
    - Comment tag: `Feature: claim-handler-entrypoint, Property 5: The pipeline fails at the first failing step, in fixed order`.
    - Construct events that fail at a chosen earliest stage (over-cap IP -> 429;
      malformed body -> 400 before gate; invalid email -> 400 before gate) and
      assert the returned status matches the earliest failing stage and later
      stages produced no side effect.
    - _Requirements: 5.4, 6.1, 6.2, 6.3, 6.4_
    - _Design: Correctness Properties > Property 5_

  - [x] 7.3 Write property test — Property 6 (wrong/empty code never writes; whitespace-padded correct code accepted)
    - `@settings(max_examples=100, deadline=None)`; moto fixture + reset +
      workaround.
    - Comment tag: `Feature: claim-handler-entrypoint, Property 6: A wrong or empty workshop code never writes`.
    - For any valid email and any empty-after-trim or wrong code: assert 403
      and the table is unchanged (scan before/after) and `claim` is never
      invoked (spy on `claim_handler.claim`). For whitespace-padded correct
      code: assert the pipeline proceeds to the claim step.
    - _Requirements: 5.1, 5.3_
    - _Design: Correctness Properties > Property 6; Testing Strategy > "no write" assertions_

  - [x] 7.4 Write property test — Property 7 (only a normalized email reaches `claim`)
    - `@settings(max_examples=100, deadline=None)`; moto fixture + reset +
      workaround (or spy on `claim_handler.claim`).
    - Comment tag: `Feature: claim-handler-entrypoint, Property 7: Only a normalized email reaches claim`.
    - For any valid email with varied case/whitespace, assert the value passed
      to `claim` equals `normalize_email(submitted_email)`.
    - _Requirements: 6.5, 10.3_
    - _Design: Correctness Properties > Property 7_

- [x] 8. Checkpoint - helpers and pipeline
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implement the `handler(event, context)` entrypoint and wire dispatch
  - [x] 9.1 Add `handler(event, context)` composing the wiring layer
    - Resolve origin **outside** the `try` so even a 500 carries CORS.
    - Route by `request_method`: `OPTIONS` -> `preflight_response`; `POST` ->
      `json_response(200, run_claim_pipeline(event), origin)`; `GET` or `""`
      (unreadable) -> `html_response`; any other non-empty method ->
      `json_response(405, {"error": "method not allowed"}, origin)`.
    - Single `try/except`: map `ClaimError` -> `json_response(exc.status,
      {"error": exc.message}, origin)`; map any other `Exception` ->
      `json_response(500, {"error": "internal error"}, origin)` with no type,
      detail, trace, email, or OTP. Body is always a string; CORS on every
      response.
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 7.1, 7.2, 7.4, 9.3_
    - _Design: Components and Interfaces > "`handler(event, context)`"_

  - [x] 9.2 Write unit/example test — handler existence + arity (R1.1)
    - Assert `claim_handler.handler` is callable and accepts an `event` and a
      `context` argument (inspect signature / call with `make_event()` and
      `None`).
    - _Requirements: 1.1_
    - _Design: Testing Strategy > "Dual approach" (handler existence and arity)_

  - [x] 9.3 Write property test — Property 1 (every response is well-formed)
    - `@settings(max_examples=100, deadline=None)`.
    - Comment tag: `Feature: claim-handler-entrypoint, Property 1: Every response is well-formed`.
    - For any method/body/`ALLOWED_ORIGIN`: assert `statusCode` is `int`,
      `headers` carries exactly one ACAO == resolved origin, `body` is `str`,
      and JSON bodies carry `Content-Type: application/json`.
    - _Requirements: 1.2, 1.3, 7.3, 8.2, 9.1, 9.2, 9.3, 9.5_
    - _Design: Correctness Properties > Property 1_

  - [x] 9.4 Write property test — Property 4 (unknown methods -> 405, no DynamoDB)
    - `@settings(max_examples=100, deadline=None)`.
    - Comment tag: `Feature: claim-handler-entrypoint, Property 4: Unknown methods are rejected with 405`.
    - For any non-empty method not in {GET, POST, OPTIONS} (case-insensitive):
      assert 405 with an `Error_Envelope` and spy-assert no DynamoDB call.
    - _Requirements: 2.4_
    - _Design: Correctness Properties > Property 4; Testing Strategy > "no DB call" assertions_

  - [x] 9.5 Write property test — Property 10 (`ClaimError` maps to status + verbatim message)
    - `@settings(max_examples=100, deadline=None)`.
    - Comment tag: `Feature: claim-handler-entrypoint, Property 10: ClaimError maps to its status and verbatim message`.
    - Monkeypatch a pipeline step to raise `ClaimError(status, message)` for
      status in {400, 403, 409, 429}; assert the response `statusCode == status`
      and body == `{"error": message}` verbatim.
    - _Requirements: 7.1_
    - _Design: Correctness Properties > Property 10_

  - [x] 9.6 Write property test — Property 11 (errors never leak detail, email, or OTP)
    - `@settings(max_examples=100, deadline=None)`.
    - Comment tag: `Feature: claim-handler-entrypoint, Property 11: Errors never leak exception detail, email, or OTP`.
    - Monkeypatch a step to raise a non-`ClaimError` whose message embeds the
      submitted email/OTP; assert 500 with the fixed `{"error": "internal
      error"}` and that the body (and any captured log output) contains none of
      the exception type/detail/trace, email, or OTP.
    - _Requirements: 7.2, 7.4_
    - _Design: Correctness Properties > Property 11; Error Handling > "PII discipline"_

- [x] 10. Checkpoint - handler dispatch
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Cover the success and idempotency properties end-to-end through the handler
  - [x] 11.1 Write property test — Property 8 (success returns exactly the four fields)
    - `@settings(max_examples=100, deadline=None)`; moto fixture + reset +
      `transact_write_items` workaround; seed a pool with >= 1 available
      credential and set `claim_handler.CONFIGURED_WORKSHOP_CODE`.
    - Comment tag: `Feature: claim-handler-entrypoint, Property 8: A successful claim returns exactly the four credential fields`.
    - Invoke `handler(make_event("POST", ...))`; assert 200 and the JSON body
      key set is exactly `{username, otp, sign_in_url, region}` matching the
      assigned credential's seeded values.
    - _Requirements: 6.6, 8.1, 8.3_
    - _Design: Correctness Properties > Property 8_

  - [x] 11.2 Write property test — Property 9 (re-claim is idempotent)
    - `@settings(max_examples=100, deadline=None)`; moto fixture + reset +
      workaround.
    - Comment tag: `Feature: claim-handler-entrypoint, Property 9: Re-claim is idempotent`.
    - Two POSTs with the same email + correct code (varying case/whitespace
      between submissions) each return 200 with byte-identical credential
      bodies via the existing re-claim path.
    - _Requirements: 10.2_
    - _Design: Correctness Properties > Property 9_

- [x] 12. (Optional) Reconcile the Function URL CORS block so exactly one ACAO reaches the wire
  - [x] 12.1 Make the handler the single CORS authority in `terraform/lambda.tf`
    - **NOTE — flagged consideration (R9.5), possibly outside this module's
      edit scope.** The handler already emits exactly one
      `Access-Control-Allow-Origin` (Property 1). The
      `aws_lambda_function_url.claim_handler` resource ALSO defines a `cors`
      block, so the Function URL service can inject a second, conflicting ACAO
      at the edge. The design's preferred fix (option a) is to make the handler
      authoritative by removing the `cors` block from the
      `aws_lambda_function_url` resource.
    - Scope guard: this is a Terraform edit with a deploy-time blast radius and
      cannot be verified by a Python unit/property test (only an integration
      request against a deployed Function URL could confirm a single on-the-wire
      ACAO). It is therefore marked optional. Do **not** silently expand scope:
      if the TF edit is deferred, record it as a follow-up in the spec rather
      than editing `lambda.tf`. If undertaken, remove only the `cors { ... }`
      block from `aws_lambda_function_url.claim_handler` and leave the rest of
      the file unchanged.
    - _Requirements: 9.5_
    - _Design: Testing Strategy > "Infrastructure consideration: duplicate Access-Control-Allow-Origin"_

- [x] 13. Final checkpoint - run the full claim-service suite and linter
  - Run the complete `claim-service` test suite with a single, non-watch run
    (e.g. `uv run --group dev pytest` from `claim-service/`, or
    `pytest claim-service/tests`) and confirm every test, including all 11
    property tests, is green.
  - Run `ruff check` over the changed Python (handler + new tests) and resolve
    any findings, honoring the repo's build-before-commit norm.
  - Clean up any temporary files; do not commit anything.
  - _Requirements: 1.1, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 4.1, 4.2, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.1, 7.2, 7.3, 7.4, 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3_
    - _Design: Testing Strategy_

## Notes

- Tasks marked with `*` are optional (all testing sub-tasks and the Terraform
  CORS reconciliation) and can be skipped for a faster MVP; core implementation
  tasks are never optional.
- The design has a Correctness Properties section (11 properties), so each
  property is realized by its own property-based test, tagged
  `Feature: claim-handler-entrypoint, Property {N}: {property text}` and run at
  `@settings(max_examples=100, deadline=None)`.
- POST-path property tests (5, 6, 7, 8, 9) reuse the moto DynamoDB fixture, the
  memoized-state reset, and the `transact_write_items` standalone-client
  workaround from the sibling tests. The "no write"/"no DB call" properties
  (2, 4, 6) use scan-before/after and/or a spy on
  `_get_table`/`claim`.
- Structural criteria that are poor fits for property tests use unit/example
  tests: handler existence + arity (R1.1), import-time config reads + unset ->
  `""` default (R4), GET body equals on-disk `index.html` (R3.1/3.2),
  `index.html`-unreadable -> 500 (R3.3), and the `hmac.compare_digest`
  structural check (R5.2).
- Out of scope per R11: the `deploy-plan`/`deploy`/`seed`/`audit`/`destroy` mise
  tasks (owned by the `credential-claim-service` spec, Requirement 14).
- This workflow produces planning artifacts only; implementing the tasks is a
  separate step the user starts from `tasks.md`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2.1"] },
    { "id": 1, "tasks": ["2.2", "3.1", "5.1", "6.1"] },
    { "id": 2, "tasks": ["3.2", "4.1", "5.2", "6.2"] },
    { "id": 3, "tasks": ["4.2", "4.3", "7.1"] },
    { "id": 4, "tasks": ["7.2", "7.3", "7.4", "9.1"] },
    { "id": 5, "tasks": ["9.2", "9.3", "9.4", "9.5", "9.6"] },
    { "id": 6, "tasks": ["11.1", "11.2"] },
    { "id": 7, "tasks": ["12.1"] }
  ]
}
```
