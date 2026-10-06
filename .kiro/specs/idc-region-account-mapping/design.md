# Design Document

> **⚠️ Superseded in part — management-account consolidation.** This document
> describes the region/account mapping against foundation's old design, in which
> the stack *created* one `awscc_sso_instance.this` **account instance** per run
> in a member/child account. A later locked decision makes foundation **adopt
> (read)** the management account's existing **organization** instance via
> `data "aws_ssoadmin_instances"` instead — it creates no instance. The
> per-user/per-group `account_id` values this mapping produces are now
> **billing/attribution metadata** (and the gated assignment target when
> `enable_account_access` is true), not a console-access grant. Read "account
> instance"/"child account" here against the authoritative current design in
> `.agents/tasks/management-account-consolidation-plan.md`.

## Overview

This design implements two coordinated changes across the kiro-provisioning-iac
repository:

1. **Region split.** The single environment-driven region (`AWS_REGION`) is
   split into two named concepts in the environment layer — `KIRO_REGION`
   (default `us-east-1`, the only region Kiro supports for sign-in) and
   `IDC_REGION` (default `ap-southeast-1`, where all AWS resources are
   provisioned). `AWS_REGION` tracks `IDC_REGION`, so every provider, SDK, and
   CLI call continues to target the resource-deployment region unchanged.
   `KIRO_REGION` is used **only** to tell participants which region to enter
   when signing in to Kiro.

2. **IdC → account mapping.** A new Terraform variable, `idc_account_map`
   (surfaced in requirements as `Idc_Account_Map`), carries the child AWS
   account ID each IdC is associated with. The account ID flows from Terraform
   input into the provisioning manifest, into each user record, into the seeded
   DynamoDB credential item, and finally into operator-facing outputs — the
   credentials document (header field + per-user column) and the claim-audit
   CSV. It is deliberately withheld from `otps.csv` and from the participant
   claim response.

The two changes share the same backbone: **a value is declared once in the
environment or in Terraform, carried through the manifest, and read by scripts
downstream — never hardcoded.** The region change extends the existing
environment-only region rule; the account change extends the existing
Terraform-variable → manifest → script data flow already used for `region`,
`sign_in_url`, and `kiro_tier`.

### Grounding: how region flows today

The current single-region path (confirmed in the codebase) is:

```
.env (AWS_REGION) ──> mise ──┬─> AWS_DEFAULT_REGION (mirror)
                             │
                             ├─> AWS provider (var.aws_region "" => env fallback)
                             │     └─> data.aws_region.current
                             │           └─> local.resolved_region
                             │                 ├─> output "region"
                             │                 └─> provisioning_manifest.region
                             │
                             └─> provision_passwords_and_output.py reads manifest["region"]
                                   ├─> credentials.md "Region code" header
                                   └─> "How to sign in" step 3 (enter region code)

manifest.region ──> seed_claim_pool.py ──> CRED# item.region ──> claim_handler
                                                                   └─> _credential_response {.., region}
export_audit.py ──> REGION = AWS_REGION (its own boto3 client region)
```

The key realization: today **one** region value (`resolved_region`) feeds both
the deployment-region facts (provider target, manifest, S3/Lambda region) *and*
the Kiro sign-in instruction in `credentials.md`. The split separates these two
consumers.

## Architecture

### Region split architecture

```
.env / .env.example:
   KIRO_REGION=us-east-1          (Kiro sign-in region, Kiro-only)
   IDC_REGION=ap-southeast-1      (resource provisioning region)
   AWS_REGION=${IDC_REGION}       (tracks IDC_REGION; drives all AWS calls)

mise.toml [env]:
   AWS_REGION         default = "" then = "{{ env.IDC_REGION }}"  (tracks IDC_REGION)
   AWS_DEFAULT_REGION = "{{ env.AWS_REGION }}"                    (unchanged mirror)
   KIRO_REGION        default = "us-east-1"
   IDC_REGION         default = "ap-southeast-1"

AWS_REGION (= IDC_REGION) ──> providers (subscription + claim-service + backend)
                          ──> data.aws_region.current ──> local.resolved_region
                                ──> output "region"  (deployment region, unchanged meaning)
                                ──> provisioning_manifest.region

KIRO_REGION ──> provisioning_manifest.kiro_region  (NEW manifest field, Terraform reads env)
            ──> provision_passwords_and_output.py reads manifest["kiro_region"]
                  ├─> credentials.md "Kiro sign-in region" header
                  └─> "How to sign in" step 3 (enter KIRO_REGION)
```

**Where `KIRO_REGION` reaches the renderer.** The design keeps the hard
env-only region rule: no script hardcodes a region, and no script invents a
region out of band. Two options were considered:

- **(A) New manifest field `kiro_region`.** Terraform reads `KIRO_REGION` from
  the environment (via a new `variable "kiro_region"` with an env fallback,
  mirroring how `aws_region` works) and emits it into `provisioning_manifest`.
  The renderer reads `manifest["kiro_region"]` exactly as it already reads
  `manifest["region"]`.
- **(B) Renderer reads `KIRO_REGION` from `os.environ` directly.**

**Chosen: (A).** It keeps the manifest the single source of truth for every
value the renderer consumes (region, sign_in_url, kiro_tier all flow this way
today), preserves reproducibility (re-rendering from an exported manifest yields
the same document without needing the original shell environment), and keeps the
"region derived only from env" rule intact — the env is still the origin, with
Terraform as the pass-through, identical to the existing `region` flow. Option
(B) would make `credentials.md` depend on ambient shell state at render time,
diverging from how every other manifest value is handled.

**Terraform's own region source for `kiro_region`.** Unlike `aws_region` (which
can be left empty to inherit from the provider's resolved region via
`data.aws_region.current`), there is no AWS data source for "the Kiro region" —
it is purely an operator-declared value. So `variable "kiro_region"` is read
from the `KIRO_REGION` environment variable through OpenTofu's standard
`TF_VAR_kiro_region` mechanism, wired by the mise provisioning task (export
`TF_VAR_kiro_region="$KIRO_REGION"` before `tofu apply`, exactly as
`claim-deploy` already exports `TF_VAR_workshop_code`). The variable defaults to
`us-east-1` so an unset env still yields Kiro's only supported region, and the
value is never a literal in `.tf` beyond that documented default-of-last-resort.

### Account mapping architecture

```
terraform.tfvars / -var:
   idc_account_map = { "default" = "111111111111" }   (per-IdC child account ID)

Subscription_Terraform:
   variable "idc_account_map"  (map(string): IdC key -> 12-digit account ID)
   locals.user_account_id      (resolve each user's account_id from the map)
   output "account_id"         (the account ID surfaced at top level)
   provisioning_manifest:
       account_id              (document-level, the IdC's account)
       users[k].account_id     (per-user, the account that user maps to)

manifest ──> provision_passwords_and_output.py
               ├─> credentials.md header "Account ID"
               └─> per-user "Account ID" column

manifest ──> seed_claim_pool.py ──> CRED# item.account_id  (NEW item attribute)

claim transaction (claim_handler.claim):
   on claim, copy CRED#.account_id onto the EMAIL#<email> lock item
   (so the audit can read it without a second lookup)

export_audit.py:
   reads account_id from each EMAIL# lock item ──> CSV column "account_id"

claim_handler._credential_response:
   returns ONLY {username, otp, sign_in_url, region}  (account_id excluded)
```

**How a user maps to an IdC's account.** This repository provisions a single IdC
account instance per run (`awscc_sso_instance.this`), so in the common case
every provisioned user belongs to that one IdC and therefore to one child
account. `idc_account_map` is a `map(string)` keyed by an **IdC key** rather
than a single scalar, so the shape already supports a future multi-IdC layout
and satisfies "users mapping to different accounts" without a schema change. For
the current single-instance topology the map carries one entry under a stable
key (`"default"`), and every user resolves to that account. The per-user
`account_id` in the manifest makes the mapping explicit at the row level, so the
credentials document and audit can show a user's account even if a later change
introduces more than one IdC.

## Components and Interfaces

### 1. Environment layer (`Environment_Config`)

**`.env.example` and `.env`** — add the two new variables and make `AWS_REGION`
track `IDC_REGION`:

```bash
# Kiro sign-in region. Kiro supports only us-east-1 today; this is the region a
# participant enters during Kiro sign-in. It does NOT affect where AWS resources
# are created.
KIRO_REGION=us-east-1

# Region in which ALL AWS resources are provisioned (IdC account instance, S3,
# Lambda). AWS_REGION tracks this value, so the AWS CLI/SDKs/OpenTofu all target it.
IDC_REGION=ap-southeast-1

# AWS_REGION tracks IDC_REGION — set IDC_REGION above, not this.
AWS_REGION=${IDC_REGION}
```

> Note: `.env` is a flat dotenv file. If literal `${IDC_REGION}` interpolation
> is not reliably expanded by every consumer that reads `.env` directly, the
> tracking is instead enforced in `mise.toml` (below), which is the authoritative
> env assembler for all tasks. The `.env.example` comment documents the intent;
> `mise.toml` guarantees it.

**`mise.toml` `[env]`** — define defaults and the tracking relationship:

```toml
# Kiro sign-in region (Kiro-only). Default is Kiro's single supported region.
KIRO_REGION = { default = "us-east-1" }
# Resource-provisioning region. Default is the operator's target region.
IDC_REGION  = { default = "ap-southeast-1" }
# AWS_REGION tracks IDC_REGION so every AWS CLI/SDK/OpenTofu call targets the
# provisioning region. `.env` (or the shell) may still override IDC_REGION.
AWS_REGION  = "{{ env.IDC_REGION }}"
# Unchanged: AWS_DEFAULT_REGION mirrors AWS_REGION.
AWS_DEFAULT_REGION = "{{ env.AWS_REGION }}"
```

This preserves the existing invariant that `AWS_DEFAULT_REGION == AWS_REGION`,
and adds `AWS_REGION == IDC_REGION`. The provisioning mise tasks additionally
export `TF_VAR_kiro_region="$KIRO_REGION"` (and continue to let `AWS_REGION`
drive the provider), so Terraform receives the Kiro region without any `.tf`
literal.

### 2. Subscription Terraform (`Subscription_Terraform`)

**`variables.tf`** — add two variables:

```hcl
variable "kiro_region" {
  description = <<-EOT
    Region a participant enters when signing in to Kiro. Kiro supports only
    us-east-1 today. Inherited from KIRO_REGION in the environment via
    TF_VAR_kiro_region (the provisioning task exports it). This value is used
    ONLY for the Kiro sign-in instruction in credentials.md; it never changes
    where AWS resources are created (that is AWS_REGION / IDC_REGION).
  EOT
  type    = string
  default = "us-east-1"
}

variable "idc_account_map" {
  description = <<-EOT
    Maps each IdC to its child AWS account ID (12-digit string). Supports
    management-account-style IdC creation where a child account is associated.
    Keyed by an IdC key; this repo provisions one IdC account instance per run,
    so the common case is a single entry under the key "default". Every
    provisioned user resolves to the account of the IdC they belong to.
  EOT
  type    = map(string)
  default = {}

  validation {
    condition = alltrue([
      for v in values(var.idc_account_map) : can(regex("^[0-9]{12}$", v))
    ])
    error_message = "Every idc_account_map value must be a 12-digit AWS account ID."
  }
}
```

**`locals.tf`** — resolve the account ID for the single IdC and per user. The
`"default"` key names the one account instance this stack creates; every user
maps to it:

```hcl
locals {
  # The IdC key for the single account instance this stack provisions.
  idc_key = "default"

  # The account_id for this IdC, or "" when the map has no entry (keeps the
  # pipeline running with an empty cell rather than failing render).
  account_id = lookup(var.idc_account_map, local.idc_key, "")

  # Per-user account_id. Today every user belongs to the single IdC, so each
  # resolves to local.account_id. Keyed per user so a future multi-IdC layout
  # can vary it by user without changing downstream consumers.
  user_account_id = { for k, _ in local.users : k => local.account_id }
}
```

**`outputs.tf`** — add an `account_id` output and extend the manifest. The
manifest gains `kiro_region`, a document-level `account_id`, and a per-user
`account_id`:

```hcl
output "account_id" {
  description = "Child AWS account ID associated with the provisioned IdC (from idc_account_map)."
  value       = local.account_id
}

output "provisioning_manifest" {
  value = {
    region      = local.resolved_region          # deployment region (unchanged meaning)
    kiro_region = var.kiro_region                 # NEW: Kiro sign-in region
    account_id  = local.account_id                # NEW: document-level account ID
    # ... existing instance_arn, identity_store_id, kiro_tier, sign_in_url ...
    users = {
      for k, u in aws_identitystore_user.this :
      k => {
        username   = u.user_name
        email      = local.users[k].email
        user_id    = u.user_id
        account_id = local.user_account_id[k]     # NEW: per-user account ID
      }
    }
    # groups, memberships unchanged
  }
}
```

The standalone `output "region"` keeps its current meaning (deployment / IdC
region). The design does **not** repurpose `region` to mean the Kiro region;
instead the Kiro region is carried as the new `kiro_region` field. This keeps
every existing consumer of `region` (the seed script, the credentials "Region
code") correct, and localizes the sign-in change to the new field.

### 3. Credentials renderer (`provision_passwords_and_output.py`)

Changes to `_load_manifest`, `_render`:

- **`_load_manifest`**: `kiro_region` is read from the manifest. For backward
  compatibility with manifests exported before this change, it falls back to
  the existing `region` when `kiro_region` is absent (so an old manifest still
  renders a sign-in region — the previous behavior). `account_id` is read with a
  default of `""`. Neither new field is added to the hard `required` set, so an
  older manifest does not fail to load.
- **`_render`**: two region-related edits plus the account column.

```python
# In _load_manifest, after loading `data`:
# kiro_region is new; fall back to the deployment region for old manifests so
# the sign-in instruction still renders.
# (region stays the deployment-region fact.)

# In _render:
region       = manifest["region"]                       # deployment region
kiro_region  = manifest.get("kiro_region") or region    # Kiro sign-in region
account_id   = manifest.get("account_id") or "—"

# Header block:
lines.append(f"- **Account ID:** `{account_id}`")       # R6.1 document-level
lines.append(f"- **Region code (resources):** `{region}`")
lines.append(f"- **Kiro sign-in region:** `{kiro_region}`")  # R2.1

# How to sign in — the region a user ENTERS is the Kiro region (R2.2, R1.6):
lines.append(f"3. Enter the sign-in URL above and the region code `{kiro_region}`.")

# Per-user table gains an Account ID column (R6.2, R6.3):
# | # | Username | Email | Account ID | Group(s) | Password / OTP | Status |
# each row reads u.get("account_id") or "—"
```

The distinction surfaced to the operator is explicit: a **Kiro sign-in region**
field (what participants type into Kiro) and a **resources region** field (where
IdC/S3/Lambda live). The sign-in step uses the Kiro region; the deployment facts
use the resources region.

### 4. Seed script (`seed_claim_pool.py`)

- **`load_manifest`**: additionally read `account_id` from the manifest (default
  `""`), returning it alongside `sign_in_url` and `region`. `region` continues
  to be the deployment region stamped on each credential (the claim response's
  `region` field is unchanged — see below).
- **Per-credential account**: the seed reads `account_id` for each user from the
  manifest's `users[k].account_id`. Because the OTP CSV is keyed by `username`
  (not by sequence key), the seed builds a `username -> account_id` lookup from
  the manifest `users` map, so each `CRED#` item gets the account its user maps
  to. When a username has no manifest entry (OTP-only row), the account falls
  back to the document-level `account_id`, then to `""`.
- **`credential_item`**: add `account_id` to the written item.

```python
def credential_item(row, sign_in_url, region, account_id):
    return {
        "PK": f"CRED#{row.username}",
        "username": row.username,
        "otp": row.otp,
        "sign_in_url": sign_in_url,
        "region": region,
        "account_id": account_id,   # NEW — operator-facing only, never in the claim response
        "status": "available",
    }
```

**`otps.csv` is unchanged** — its header stays `username,otp`. `account_id` is
sourced from the manifest, never from the OTP CSV, so `load_rows` and
`classify_rows` are untouched (R8.1).

### 5. Claim handler (`claim_handler.py`)

- **`_credential_response`**: unchanged — still returns exactly
  `{username, otp, sign_in_url, region}`. `account_id` is intentionally not
  projected, so it never reaches a participant (R8.2, R8.3).
- **`region` field semantics**: the `region` returned to a participant is the
  value seeded onto the `CRED#` item (the deployment region today). This change
  does not alter the four-field contract; whether that `region` should become
  the Kiro region is out of scope here because the requirements fix the response
  to the existing four fields and locate the Kiro-region surfacing in
  `credentials.md`. The handler contract is preserved verbatim.
- **Claim transaction**: when a credential is claimed, copy its `account_id`
  onto the `EMAIL#<email>` lock item (alongside the existing `username` and
  `claimed_at`). This is the key enabler for the audit: the audit scans
  `EMAIL#` items, which today carry only `username` and `claimed_at`. Writing
  `account_id` onto the lock at claim time lets the audit read it directly
  without a second `GetItem` per row.

```python
# In claim(), the EMAIL# Put item (and the reclaim fast-path lock creation) gains
# the account_id read from the picked CRED# item before the transaction:
"Item": {
    "PK": f"EMAIL#{email}",
    "username": username,
    "claimed_at": claimed_at,
    "account_id": cred_account_id,   # copied from the CRED# item (operator audit only)
}
```

`cred_account_id` is read from the picked `CRED#` item (which the seed stamped).
It never enters `_credential_response`, so the participant response is unchanged.

### 6. Audit export (`export_audit.py`)

- **`CSV_HEADER`**: `("email", "username", "account_id", "claimed_at")` — new
  `account_id` column (R7.1).
- **`email_item_to_row`**: read `account_id` from the `EMAIL#` item (default
  `""` for a malformed or pre-change item), so each audit row carries the
  account the claimed credential belonged to (R7.2).

```python
CSV_HEADER = ("email", "username", "account_id", "claimed_at")

def email_item_to_row(item):
    pk = str(item.get("PK", ""))
    return {
        "email": pk.removeprefix(EMAIL_PREFIX),
        "username": str(item.get("username", "")),
        "account_id": str(item.get("account_id", "")),  # NEW (R7.2)
        "claimed_at": str(item.get("claimed_at", "")),
    }
```

The audit's own boto3 client region still comes from `AWS_REGION` (now =
`IDC_REGION`), which is correct — the table lives in the deployment region.

## Data Models

### Manifest (`provisioning_manifest`) — new/changed fields

| Field                 | Type            | Meaning                                             | Status  |
| --------------------- | --------------- | --------------------------------------------------- | ------- |
| `region`              | string          | Deployment / IdC resource region (`IDC_REGION`)     | existing|
| `kiro_region`         | string          | Kiro sign-in region (`KIRO_REGION`)                 | NEW     |
| `account_id`          | string          | Document-level child AWS account ID                 | NEW     |
| `users[k].account_id` | string          | Per-user child AWS account ID                       | NEW     |

### DynamoDB items

| Item        | Attribute     | Status | Notes                                              |
| ----------- | ------------- | ------ | -------------------------------------------------- |
| `CRED#<u>`  | `account_id`  | NEW    | Seeded from manifest; never in the claim response. |
| `EMAIL#<e>` | `account_id`  | NEW    | Copied from the CRED# item at claim time; audit source. |

### Credentials document (`credentials.md`)

- Header: `Account ID`, `Kiro sign-in region`, `Region code (resources)`.
- Per-user table: new `Account ID` column.

### Audit CSV

- Header: `email,username,account_id,claimed_at`.

### Claim response (unchanged)

- `{username, otp, sign_in_url, region}` — four fields, no `account_id`.

## Error Handling & Edge Cases

- **Missing `account_id` for an IdC.** `idc_account_map` defaults to `{}` and
  `local.account_id` resolves to `""`. Manifest, outputs, seed items, the
  credentials cell, and the audit cell all tolerate an empty account by
  rendering `—` (documents) or `""` (CSV / item), so the pipeline never fails
  for an unmapped IdC. The Terraform `validation` only rejects a *present*
  value that is not 12 digits — an absent entry is allowed.

- **Users mapping to different accounts.** The per-user `account_id` in the
  manifest and the per-user credentials column mean each row shows its own
  account. For the current single-IdC topology all users resolve to the same
  account; the data path already supports divergent values without a schema
  change.

- **Backward compatibility of manifest consumers.** `kiro_region` and
  `account_id` are read with fallbacks (`kiro_region` → `region`; `account_id`
  → `""`) and are *not* added to the renderer's hard `required` set or the seed
  script's required manifest keys. An older `manifest.json` therefore still
  loads and renders — it simply shows the deployment region as the sign-in
  region (prior behavior) and an empty account cell. New manifests populate both.

- **Backward compatibility of `otps.csv`.** The header stays `username,otp`.
  No consumer of `otps.csv` changes, so an existing OTP CSV seeds exactly as
  before; the account is joined in from the manifest, not the CSV.

- **Pre-change `EMAIL#` lock items in the audit.** A credential claimed before
  this change has no `account_id` on its lock item; `email_item_to_row` defaults
  it to `""`, so the audit still produces a row (empty account) rather than
  crashing — consistent with the existing defensive handling of absent
  `username`/`claimed_at`.

- **Region tracking divergence.** `AWS_REGION` is derived from `IDC_REGION` in
  `mise.toml`; `AWS_DEFAULT_REGION` mirrors `AWS_REGION`. An operator who sets
  only `IDC_REGION` gets all three aligned. Setting `AWS_REGION` directly in
  `.env` still works (it overrides the mise default), but the documented path is
  to set `IDC_REGION`.

- **No region literal anywhere.** Every region value originates in the
  environment (`KIRO_REGION`, `IDC_REGION`, `AWS_REGION`). Terraform exposes
  `kiro_region` via `TF_VAR_kiro_region` with a documented `us-east-1`
  default-of-last-resort (Kiro's only supported region); scripts that accept a
  `--region` argument continue to default it from `AWS_REGION`. No region is a
  literal constant in handler/IaC/script logic (R3.1–R3.3).

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

Each property below is testable with a minimum of 100 randomized iterations and
references the requirement(s) it validates. Properties over the credentials
renderer and the pure script/handler functions (`_render`, `credential_item`,
`email_item_to_row`, `_credential_response`, the account-join lookup) are
exercised directly, since those functions are pure and AWS-free. Configuration
facts (env-variable presence/defaults, Terraform variable existence, CSV column
presence) and infrastructure wiring (provider region resolution) are verified by
smoke/example/integration tests, not property tests, and are not listed here.

### Property 1: AWS_REGION tracks IDC_REGION

*For any* region string supplied as `IDC_REGION`, the environment the task layer
assembles SHALL resolve `AWS_REGION` to that same value (and `AWS_DEFAULT_REGION`
SHALL mirror `AWS_REGION`), so the resource-provisioning region always drives
every AWS CLI/SDK/OpenTofu call.

**Validates: Requirements 1.3**

### Property 2: Kiro sign-in region surfaces as KIRO_REGION

*For any* manifest carrying a `kiro_region` value, the rendered credentials
document SHALL present that value both as the Kiro-sign-in-region header field
and in the "how to sign in" instruction that tells a participant which region to
enter.

**Validates: Requirements 1.6, 2.1, 2.2**

### Property 3: Resource region surfaces as the deployment region

*For any* manifest carrying a `region` value, the rendered credentials document
SHALL present that value as the resource-provisioning region field, distinct
from the Kiro sign-in region.

**Validates: Requirements 2.3**

### Property 4: Each user record carries its IdC's account ID

*For any* set of provisioned users and any IdC-to-account mapping, each user's
produced record (manifest user entry and seeded `CRED#` credential item) SHALL
carry the `account_id` of the IdC that user belongs to.

**Validates: Requirements 5.3**

### Property 5: Account ID appears as a document-level header field

*For any* manifest carrying an `account_id` value, the rendered credentials
document SHALL present that value as a document-level header field.

**Validates: Requirements 6.1**

### Property 6: Per-user account column reflects each user's account

*For any* set of users each annotated with an `account_id`, the rendered
credentials document SHALL display, in each user's row, that specific user's
`account_id` — so users mapping to different accounts show their respective
values.

**Validates: Requirements 6.2, 6.3**

### Property 7: Audit row carries the claimed credential's account ID

*For any* `EMAIL#` lock item, the audit row produced from it SHALL set its
`account_id` column to the item's `account_id` (defaulting to an empty value
when the item has none), so the audit records which account each claimed
credential belonged to.

**Validates: Requirements 7.2**

### Property 8: Claim response excludes the account ID

*For any* `CRED#` item — including one that carries an `account_id` attribute —
the credential response returned to a claiming participant SHALL contain exactly
the keys `username`, `otp`, `sign_in_url`, and `region`, and SHALL NOT contain
`account_id` or any other internal attribute.

**Validates: Requirements 8.2, 8.3**
