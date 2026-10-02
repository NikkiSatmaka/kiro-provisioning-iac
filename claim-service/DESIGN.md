# Credential Claim Service — Requirements & Design

Self-serve distribution of Kiro IAM Identity Center (IdC) credentials to
workshop participants. Each participant scans a QR code (or opens a short link),
enters their email, and receives exactly one username + one-time password (OTP).

- **Status:** draft design, not yet built
- **Scope:** distribution only — provisioning and OTP generation stay in `../subscription/`
- **Owner:** workshop host

---

## 1. Problem

The `../subscription/` tooling provisions `N` IdC users and (via a console-only step)
produces a one-time password per user. Today those land in a single
`output/credentials.md` table that shows *every* user's credentials to whoever
opens it. For a workshop with anonymous participants this is wrong on two counts:

1. **No single-claim guarantee.** Anyone can take `kiro-user-01`; two people can
   take the same one. There is no notion of "claimed."
2. **No distribution mechanism.** Handing a shared doc to a room doesn't scale
   and leaks every credential to everyone.

We need a pool of credentials where **each credential is claimable exactly once**
and **each participant (by email) claims exactly once**, self-serve, with no
operator handing them out one at a time, and race-proof under a room full of
people scanning simultaneously.

---

## 2. Requirements

### Functional

| # | Requirement |
|---|---|
| F1 | A participant can claim one credential by submitting an email via a web form reached from a QR code or short link. |
| F2 | Each credential is handed out to **at most one** email, ever. |
| F3 | Each email can claim **at most one** credential, ever. |
| F4 | Re-submitting the same email returns the **same** credential already claimed (idempotent), not an error and not a second credential. |
| F5 | A successful claim returns: username, OTP, sign-in URL, region code. |
| F6 | When the pool is exhausted, the participant sees a clear "all claimed" message. |
| F7 | The host can seed the pool from the existing `otps.csv` + `manifest.json`. |
| F8 | The host can export an audit (email → username → timestamp) before teardown. |

### Non-functional

| # | Requirement |
|---|---|
| N1 | **Race-proof.** Concurrent claims must never double-assign a credential or let one email claim twice. Correctness under contention is the top priority. |
| N2 | **Low cost.** Target ≈ $0 for a workshop; no always-on compute, no API Gateway, no WAF unless opted in. |
| N3 | **Opt-in & isolated.** Must not alter or depend on the existing `../subscription/` provisioning flow. Its own Terraform state. |
| N4 | **Tear-down-able.** Destroy all claim infrastructure after a workshop without touching provisioned identities. |
| N5 | **Abuse-resistant enough** for a workshop: a casual bot shouldn't be able to drain the pool. Full hardening (WAF) is optional. |
| N6 | **PII-aware.** Emails are PII; store minimally, git-ignore any export, secure-delete after use. |

### Out of scope

- Setting or resetting IdC passwords (console-only; stays in `../subscription/`).
- Granting any AWS account access (identities are Kiro-login only).
- Email verification / authentication (email is for audit, not identity proof).
- The workshop-material site itself (this only adds a `/claim` origin to it later).

---

## 3. Repository placement

**Decision: keep in this repo as a self-contained subtree, not a separate repo.**

Rationale: the service's only input is the output of `../subscription/`
(`(username, otp)` pairs + `sign_in_url`/`region`). Splitting repos would create
a cross-repo data contract with no benefit — same owner, same lifecycle (stood
up and torn down with the workshop), not reused elsewhere. A clean subtree gives
separation of concerns without the coordination cost. If it ever needs an
independent release later, extracting a clean subtree is cheap.

```
kiro-provisioning-iac/
├── backend/                ← shared remote-state backend (S3 bucket + lock table)
├── subscription/           ← IdC user/subscription provisioning (was iac/)
└── claim-service/          ← this service (opt-in, own TF state)
    ├── DESIGN.md           ← this document
    ├── README.md           ← run order (to be written)
    ├── terraform/          ← dynamodb, lambda, function url, own backend
    ├── lambda/             ← claim_handler.py
    ├── scripts/            ← seed_claim_pool.py, export_audit.py
    └── frontend/           ← claim page (index.html) + QR
```

**Isolation guarantee (N3/N4):** `claim-service/terraform/` uses its **own
backend/state**, separate from `subscription/terraform/`, so it can be destroyed
independently of the provisioned identities.

---

## 4. Architecture

```
tofu apply ──► reset password per user (console) ──► collect OTPs (otps.csv)
                                                          │
                                     seed_claim_pool.py ──┘
                                                          │
                                                          ▼
                                                   DynamoDB table
                                                          ▲
 participant scans QR ─► claim page (S3+CloudFront) ─► POST /claim ─► Lambda (Function URL)
                                                                          │
                                                      TransactWriteItems (atomic)
                                                                          │
                                                      returns one username + OTP
```

| Piece | Choice | Why |
|---|---|---|
| Data store | DynamoDB, on-demand, single table | Atomic conditional writes = the race-proof primitive (N1). Free tier covers a workshop (N2). |
| Compute | Lambda via **Function URL** | No API Gateway cost. Billed as Lambda; free tier covers it (N2). |
| Frontend | S3 static page + CloudFront | Reuses the planned workshop-material distribution; Function URL added as a `/claim` origin. Works standalone until that exists. |
| Gate | shared workshop code checked in-Lambda + per-IP attempt cap | Abuse resistance (N5) without paying for WAF (N2). |

---

## 5. Data model — single DynamoDB table

Two item types in one table, distinguished by key prefix, so a single
transaction can enforce **both** uniqueness constraints at once.

**Credential item** — one per IdC user, seeded up front:
```
PK = "CRED#<username>"
username, otp, sign_in_url, region
status            = "available" | "claimed"
claimed_by_email  = <email>        (absent until claimed)
claimed_at        = <iso8601>      (absent until claimed)
```

**Email-lock item** — written at claim time to enforce one-per-email:
```
PK = "EMAIL#<lowercased, trimmed email>"
username   = <the credential they got>
claimed_at = <iso8601>
```

A GSI or a filtered query on `status = "available"` lets the Lambda find a free
credential to offer. For workshop-scale (tens of items) a bounded scan is fine;
a GSI is optional.

---

## 6. The claim operation (the correctness core — N1)

A single DynamoDB **`TransactWriteItems`** with two conditional writes that
commit or fail together:

1. **Put** `EMAIL#<email>` with `ConditionExpression: attribute_not_exists(PK)`
   → fails if this email already claimed (enforces F3).
2. **Update** `CRED#<username>` setting `status = "claimed"`, `claimed_by_email`,
   `claimed_at`, with `ConditionExpression: status = "available"`
   → fails if that credential was already taken (enforces F2).

Both in one transaction ⇒ concurrent requests can neither double-assign a
credential nor let an email claim twice. There is **no read-then-write** on the
claim itself, so no check-then-act race.

### Selecting which credential to hand out

Optimistic claim with bounded retry:

1. Query/scan for one `status = "available"` credential.
2. Attempt the transaction (section 6) on it.
3. If the transaction is cancelled because that credential was taken between
   pick and write (a lost race), retry from step 1 with the next available one,
   up to a small bound.
4. If no available credential remains → `409` pool exhausted (F6).

The atomicity guarantee lives in the step-2 condition; the retry only makes
contention graceful.

### Idempotent re-scan (F4)

If the `EMAIL#` put fails its condition, the email already claimed. The handler
catches the transaction-cancelled reason, reads the existing `EMAIL#<email>`
item to find the username, loads that `CRED#` item, and **returns the same
credential**. A participant who closes the tab and re-scans gets their
credential back, not an error.

---

## 7. API

`POST /claim`
```json
{ "email": "a@b.com", "workshop_code": "KIRO-WS-7F3A" }
```

| Status | Meaning | Body |
|---|---|---|
| `200` | claimed (or idempotent re-claim) | `{ "username", "otp", "sign_in_url", "region" }` |
| `400` | malformed email / missing field | `{ "error" }` |
| `403` | bad or missing workshop code | `{ "error" }` |
| `409` | pool exhausted | `{ "error" }` |
| `429` | per-IP attempt cap exceeded | `{ "error" }` |

CORS allows the CloudFront claim-page origin only.

---

## 8. Components to build

| Path | What |
|---|---|
| `claim-service/terraform/dynamodb.tf` | the table (on-demand) |
| `claim-service/terraform/lambda.tf` | function + Function URL + IAM role (least-privilege to the one table) |
| `claim-service/terraform/backend.tf` | **own** remote state (isolated from `subscription/`) |
| `claim-service/terraform/variables.tf` | workshop_code, table name, allowed origin |
| `claim-service/terraform/outputs.tf` | Function URL, claim-page URL |
| `claim-service/lambda/claim_handler.py` | the `TransactWriteItems` logic + gate + retry |
| `claim-service/scripts/seed_claim_pool.py` | manifest.json + otps.csv → `PutItem` the `CRED#` items |
| `claim-service/scripts/export_audit.py` | dump email → username → time to CSV (F8) before teardown |
| `claim-service/frontend/index.html` | email form, posts to `/claim`, renders the credential |
| QR | generated pointing at the CloudFront short link |

---

## 9. Decisions

| # | Decision | Choice |
|---|---|---|
| D1 | Gate strength | Shared workshop code in-Lambda + per-IP attempt cap. (Alt: nothing; or WAF ~$5/mo.) |
| D2 | Email handling | Format-check and store only; no verification round trip. |
| D3 | Exhaustion UX | Plain "all claimed" message; no waitlist. |
| D4 | TF state | Own backend, isolated from `subscription/`. |
| D5 | PII | Emails git-ignored anywhere exported; audit-export then destroy. |

> D1–D3 are defaults pending host confirmation; flip any before build.

---

## 10. Cost (ap-southeast-1, ~50 creds / ~500 requests)

| Service | Usage | Cost |
|---|---|---|
| Lambda | ~500 invocations, 128 MB | $0.00 (free tier) |
| DynamoDB on-demand | ~500 writes + reads, <1 MB | < $0.01 |
| CloudFront | rides existing distribution | $0.00 marginal (1 TB/10M req free tier) |
| Function URL | billed as Lambda | $0.00 |

**Total ≈ $0**, dominated by rounding. WAF (if D1 → WAF) is the only real line
item at ~$5/mo + ~$1/rule.

---

## 11. Teardown

1. Run `export_audit.py` → CSV of who claimed what (keep per N6, secure-delete after).
2. `tofu destroy` in `claim-service/terraform/` (own state ⇒ identities untouched).
3. Delete the exported audit + any seeded local artifacts.

---

## 12. Open risks

- **Pick-then-claim contention** at the instant a room scans together: mitigated
  by the bounded retry; worst case a participant retries once.
- **Function URL is public**: the D1 gate + per-IP cap is the only barrier
  unless WAF is added. Acceptable for a time-boxed workshop; revisit for larger.
- **OTP freshness**: console OTPs may expire. Seed close to the event; document
  the expiry window in the README.
