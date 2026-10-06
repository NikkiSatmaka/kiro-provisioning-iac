# Credential Claim Service

Self-serve, race-proof distribution of pre-provisioned Kiro IAM Identity Center
credentials to workshop participants. Participants scan a QR code (or open a
short link), enter their email and a workshop code, and receive exactly one
username + one-time password — with concurrency guarantees that no credential
is handed out twice and no email claims twice.

This is an opt-in, self-contained subtree with its own OpenTofu state. It does
not alter or depend on the `../subscription/` provisioning flow and can be torn
down independently without touching provisioned identities.

It deploys in the AWS Organizations **management account**, alongside every
other stack. Many workshops' claim services coexist there side by side: every
resource name derives from `local.name = credential-claim-<workshop_id>`, so
each workshop gets its own table, Lambda, Function URL, IAM role, and policy
with an independent lifecycle, and its spend is attributable through the
unconditional `workshop_id` cost tag. One Function URL serves one workshop; a
single workshop can serve participants across multiple member accounts.
`AWS_PROFILE` must be a management-account profile.

The full requirements and design live in the specs, not here:

- `.kiro/specs/credential-claim-service/` — the service (table, Lambda, scripts).
- `.kiro/specs/claim-handler-entrypoint/` — the handler entrypoint + wiring.

## Architecture at a glance

One Python 3.12 Lambda behind **exactly one AWS Lambda Function URL** serves the
whole thing: a GET returns the inline claim page, a POST runs the claim. There
is no API Gateway, no WAF, and no separate frontend host — the page and the API
are the same URL. State is one on-demand DynamoDB table (`CRED#` / `EMAIL#` /
`RATE#` items). Cost at workshop scale is ≈ $0.

```
participant ──GET──▶  https://<id>.lambda-url.<region>.on.aws/   ──▶ claim page
            ──POST─▶  (same URL)                                 ──▶ claim result
                                   │
                                   ▼
                        DynamoDB (single table, on-demand)
```

## How participants reach it

After you deploy, AWS assigns a single public HTTPS URL of the form:

```
https://<random-id>.lambda-url.<region>.on.aws/
```

- It is **HTTPS-only** — AWS terminates TLS with its own managed, browser-trusted
  certificate. There is no HTTP variant and nothing to provision.
- The `<random-id>` is assigned at creation and stays stable for the life of the
  Function URL. You don't choose it; print it with `mise run claim-url`.
- The URL is **public** (`authorization_type = NONE`). Access is gated inside the
  handler by the **workshop code** and a **per-IP attempt cap** — so treat the
  URL + workshop code as the only barriers and don't publish them before the
  event.

Because the id is a long random string, put the URL behind a **QR code** or a
**short link** for the workshop — participants scan/click rather than type it.
(There is no custom domain out of the box; adding one would mean CloudFront or
API Gateway + Route 53 + ACM, which this service deliberately avoids.)

## Prerequisites

From the repo root, once:

```bash
mise install          # tools + .venv
mise run setup        # sync Python deps
cp .env.example .env  # then edit .env
```

In `.env` set at least:

- `AWS_PROFILE` / `AWS_REGION` — `AWS_PROFILE` must be a management-account
  profile; region defaults to `us-east-1`. The provider also accepts an explicit
  `aws_profile` variable (empty by default, falling back to `AWS_PROFILE` / the
  SDK chain), mirroring the other stacks.
- `WORKSHOP_CODE` — the shared gate secret for this workshop (required by deploy).

The remote state bucket must already exist (created by the `backend/` stack —
see the root `README.md`). This service **reuses** that shared bucket under a
distinct state key (`claim-service/terraform.tfstate`), so there is no separate
bootstrap. `mise run backend-bootstrap` already writes
`claim-service/terraform/backend.hcl` for you alongside the subscription one —
if you have run it, there is nothing to do here.

Only if you need to create it by hand (e.g. the bucket predates this output):

```bash
cp claim-service/terraform/backend.hcl.example claim-service/terraform/backend.hcl
# then set your 12-digit <account_id> in the bucket name
```

## Run order

Operator steps, in lifecycle order. Each mutating step has a safe `*-plan`
dry-run sibling, and apply/seed/destroy prompt before they change anything.
All are run from the repo root.

| # | Step | Task | What it does |
|---|------|------|--------------|
| 1 | Test | `mise run claim-test` | Run the full suite (pytest + Hypothesis + moto). **No AWS needed.** |
| 2 | Deploy (dry run) | `mise run claim-deploy-plan` | `tofu init` + `plan`; reports changes, applies none. |
| 3 | Deploy | `mise run claim-deploy` | Apply the table, Lambda, and Function URL (prompts), then print the claim URL. |
| — | Get URL | `mise run claim-url` | Print the deployed claim URL any time (for the QR / short link). |
| 4 | Seed (dry run) | `mise run claim-seed-plan` | Classify `otps.csv` rows and report what would be seeded; writes nothing. |
| 5 | Seed | `mise run claim-seed` | Write one `CRED#` item per credential from the `subscription/` outputs. Conditional, so safe to re-run. |
| — | _(workshop runs)_ | — | Participants claim credentials at the URL. |
| 6 | Audit | `mise run claim-audit` | Export who claimed what to a git-ignored CSV under `output/` (contains PII). |
| 7 | Destroy | `mise run claim-destroy` | Tear down the table, Lambda, and Function URL (prompts). Never touches `subscription/` identities. |

### Notes on the steps

- **Deploy** reads `WORKSHOP_CODE` from `.env` and passes it to OpenTofu as the
  sensitive `workshop_code` variable (via `TF_VAR_workshop_code`), so the secret
  is never written to a tracked file or typed on the command line.
- **Seed** reads `../../subscription/output/otps.csv` (header `username,otp`) and
  `../../subscription/output/manifest.json` (for `sign_in_url` and `region`). Run
  the `subscription/` flow first so those files exist. A row missing a username
  or OTP is reported and skipped.
- **Audit** writes `output/audit-<timestamp>.csv`. The `output/` directory is
  git-ignored because the rows contain participant emails (PII).
- **Region** everywhere is derived from `AWS_REGION` (default `us-east-1`); it is
  never hardcoded in the handler, scripts, or Terraform.

## Testing it: local vs. deployed

You do **not** need AWS to validate the service logic.

- **Local, automated (recommended first):** `mise run claim-test` exercises the
  handler end-to-end — routing, the workshop-code gate, the race-proof claim
  transaction, idempotent re-claim, CORS headers, and error mapping — against an
  in-memory DynamoDB (moto). This is the main correctness lever.
- **Local, by hand:** you can import `claim_handler` and call
  `handler(event, context)` with a synthetic Function URL event against a moto
  table for a quick smoke test (see the tests under `tests/` for the event shape
  and the moto fixture pattern).
- **Deployed only:** the live Function URL, its HTTPS certificate, and a real
  browser loading the page can only be verified against an actual deploy. The
  handler logic itself is fully covered locally.

## Layout

```
claim-service/
├── lambda/claim_handler.py   ← the Lambda (entrypoint + correctness core)
├── frontend/index.html       ← self-contained claim page (served inline on GET)
├── terraform/                ← DynamoDB + Lambda + Function URL + IAM
├── scripts/
│   ├── seed_claim_pool.py    ← populate the pool from subscription/ outputs
│   └── export_audit.py       ← export the claimed-email audit CSV
├── tests/                    ← pytest + Hypothesis + moto suite
└── output/                   ← git-ignored audit CSVs (PII)
```
