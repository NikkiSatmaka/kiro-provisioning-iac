# Claim-service (step 6 of the flow) — optional self-serve credential distribution

> Phase link: this is **Step 6** of the root [`README.md`](../README.md) flow.
> Prerequisites: Step 5 subscription
> ([`../subscription/README.md`](../subscription/README.md)) — it produces the
> credential files this stack hands out · Next: none; this is the last step.

## What it is

The claim-service is an **opt-in** way to hand each workshop participant exactly
one of the Kiro credentials that Step 5 (subscription) created. Participants
scan a QR code or open a short link, enter their email and a workshop code, and
get back one username and one one-time password. Two guarantees hold even when
many people claim at once: no credential is handed out twice, and no email
claims twice.

The whole service is **one Python Lambda behind exactly one AWS Lambda Function
URL** — a single public HTTPS address AWS gives you when you deploy. A browser
`GET` to that URL returns the claim page; a form `POST` to the *same* URL runs
the claim. There is no API Gateway, no separate web host, and no WAF — the page
and the API share one URL. State is a single on-demand DynamoDB table, so the
cost at workshop scale is about zero.

The URL AWS assigns looks like
`https://<random-id>.lambda-url.<region>.on.aws/`. It is HTTPS-only (AWS
terminates TLS with its own browser-trusted certificate — nothing to provision),
and the `<random-id>` is fixed for the life of the Function URL. Because the URL
is public, the only barriers are the **workshop code** and a **per-IP attempt
cap** enforced inside the handler, so don't publish the URL or the code before
the event. The random id is long, so put the URL behind a **QR code** or a
**short link** rather than asking people to type it. There is no custom domain
out of the box; adding one would require CloudFront or API Gateway plus Route 53
and ACM, which this service deliberately avoids.

This is a self-contained subtree with its **own** OpenTofu state. It does not
alter or depend on the running of the `../subscription/` stack and can be torn
down on its own without touching any provisioned identity. It deploys in the AWS
Organizations **management account**, alongside every other stack, so
`AWS_PROFILE` must be a management-account profile. Many workshops' claim
services coexist there side by side: every resource name derives from
`credential-claim-<workshop_id>`, so each workshop gets its own table, Lambda,
Function URL, IAM role, and policy with an independent lifecycle, and its spend
is attributable through the `workshop_id` cost tag. One Function URL serves one
workshop; a single workshop can serve participants across multiple member
accounts.

The full requirements and design live in the specs, not here:
`.kiro/specs/credential-claim-service/` (the service — table, Lambda, scripts)
and `.kiro/specs/claim-handler-entrypoint/` (the handler entrypoint and wiring).

## Prerequisites

Before you run this step, these must be true:

1. **Phase 0 toolchain + AWS auth done** (root [`README.md`](../README.md)), and
   `AWS_PROFILE` is a **management-account** profile. The region comes from
   `AWS_REGION` (default `us-east-1`) and is never hardcoded.
2. **Step 1 backend done** — the shared S3 remote-state bucket from the
   `backend/` stack exists, and `mise run backend-bootstrap` has written
   `claim-service/terraform/backend.hcl` for you (this stack reuses the shared
   bucket under its own state key, so there is no separate bootstrap). See
   [`../backend/README.md`](../backend/README.md). Only if you must create the
   file by hand — e.g. the bucket predates that output — copy
   `claim-service/terraform/backend.hcl.example` to
   `claim-service/terraform/backend.hcl` and set your 12-digit account id in the
   bucket name.
3. **Step 5 subscription done** — the seed step consumes the subscription step's
   handoff files, `../subscription/output/otps.csv` (header `username,otp`) and
   `../subscription/output/manifest.json` (for the sign-in URL and region), so
   those must already exist. Run Step 5 first
   ([`../subscription/README.md`](../subscription/README.md)).
4. **`WORKSHOP_CODE` set in `.env`** — the shared gate secret for this workshop;
   deploy requires it.
5. **`WORKSHOP_ID` set in `.env`** — the per-workshop namespace. The deploy,
   seed, and audit tasks fail closed without it, because every resource and the
   state key are derived from it (`credential-claim-<WORKSHOP_ID>`).

## How to run

Follow these in order, all from the repo root. Each mutating step has a safe
`*-plan` dry-run sibling listed before it; apply, seed, and destroy prompt before
they change anything.

1. **Deploy (dry run) — review what will be created.** Runs `tofu init` and
   `plan`; reports the table, Lambda, and Function URL it would create and
   changes nothing.

   ```bash
   mise run claim-deploy-plan
   ```

2. **Deploy — create the table, Lambda, and Function URL.** Reads `WORKSHOP_CODE`
   from `.env` and passes it to OpenTofu as the sensitive `workshop_code`
   variable (so the secret is never typed on the command line or written to a
   tracked file). Prompts to approve, then prints the claim URL. Expect the three
   resources to exist and a public HTTPS URL to be printed.

   ```bash
   mise run claim-deploy
   ```

3. **Get the URL — any time after deploy.** Prints the deployed claim URL so you
   can put it behind the workshop QR code or short link.

   ```bash
   mise run claim-url
   ```

4. **Seed (dry run) — classify what would be seeded.** Reads
   `../subscription/output/otps.csv` and `manifest.json`, classifies each row,
   and reports what it would write — writing nothing. A row missing a username or
   OTP is reported and skipped.

   ```bash
   mise run claim-seed-plan
   ```

5. **Seed — populate the claim pool.** Writes one `CRED#` item per credential
   from the subscription outputs into this workshop's table. The write is
   conditional, so it is safe to re-run.

   ```bash
   mise run claim-seed
   ```

   The participants then claim their credentials at the URL during the workshop.

6. **Audit — export who claimed what.** After the workshop, exports the claimed
   records to a timestamped CSV under `output/`. That directory is git-ignored
   because the rows contain participant emails (PII).

   ```bash
   mise run claim-audit
   ```

### Testing it: local vs. deployed

You do **not** need AWS to validate the service logic. `mise run claim-test`
(step 1 above) exercises the handler end to end — routing, the workshop-code
gate, the race-proof claim transaction, idempotent re-claim, CORS headers, and
error mapping — against an in-memory DynamoDB, and is the main correctness lever.
Only the live Function URL, its HTTPS certificate, and a real browser loading the
page require an actual deploy to verify; the handler logic itself is fully
covered locally.

### Layout

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

## Teardown

See the root [`TEARDOWN.md`](../TEARDOWN.md) for how to remove this stack.
