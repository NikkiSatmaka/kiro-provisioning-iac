# Design Document

> **⚠️ Superseded in part — management-account consolidation.** This document
> describes the ORIGINAL design in which `foundation/` *created and owned* an
> account-level IdC instance via the `awscc_sso_instance` resource (with an
> `instance_name` variable and the AWSCC list-of-objects tag shape) in a
> member/child account. That design was changed by a later locked decision:
> `foundation/` now runs in the **AWS Organizations management account** and
> **adopts (reads)** the management account's existing **organization** IdC
> instance via `data "aws_ssoadmin_instances"`. It creates and owns nothing —
> no `awscc` provider, no `instance_name` variable, and no destroyable instance
> (`foundation-destroy` is a documented no-op). Where this document says
> "account instance", "create/own the instance", "awscc", "instance_name", or
> "member-account enablement toggle", read the current behavior from
> `.agents/tasks/management-account-consolidation-plan.md`, which is
> authoritative. The outputs (`instance_arn`, `identity_store_id`, `region`,
> `sign_in_url`) and the decoupling-via-variables boundary are unchanged.

## Overview

This design adds the **Foundation IdC service** — a new, standalone
OpenTofu/Terraform stack at `foundation/terraform/` whose sole job is to CREATE
and OWN the account-level IAM Identity Center (IdC) instance for this AWS
account. It re-homes a responsibility the `multi-workshop-provisioning` work
deliberately removed from the subscription stack: that stack stopped creating
`awscc_sso_instance.this` and now CONSUMES the instance through two
operator-supplied inputs (`var.idc_instance_arn`, `var.identity_store_id`). This
spec gives that creation a single, long-lived home.

The IdC instance is a shared foundation resource reused across every workshop.
It is applied **once** and reused — never per workshop (R10.4). The Foundation
IdC service EMITS the instance ARN, identity store id, region, and sign-in URL
as outputs; the operator copies/exports those values into the subscription
stack's inputs. The two stacks are wired together by the operator through
explicit variables, **never** by a remote-state reference (R3.3, R3.4). This
preserves the decoupling boundary the subscription stack already established.

**Scope.** This spec adds ONLY the `foundation/terraform/` stack, its `mise`
tasks, and its runbook/documentation, plus one additive output in the shared
`backend/terraform` stack so the bootstrap also writes
`foundation/terraform/backend.hcl` (R4.5). It makes **no changes to the
subscription stack's `.tf` files** — the subscription stack keeps consuming the
instance through its existing `var.idc_instance_arn` / `var.identity_store_id`
inputs (see "Scope boundary" at the end of this document).

### How the foundation stack fits the multi-stack architecture

The repo is split into independent top-level stacks, each with its own OpenTofu
state in the one shared S3 backend. The foundation stack slots in between the
backend bootstrap and the subscription stack:

```
backend/terraform        (LOCAL state; run once)
   creates: S3 state bucket + DynamoDB lock table
   writes:  each consuming stack's git-ignored backend.hcl from a bootstrap output
                 │
                 ▼
foundation/terraform     (NEW; state key: foundation/terraform.tfstate)
   creates: ONE awscc_sso_instance "this"  (the account-level IdC instance)
   emits:   instance_arn / identity_store_id / region / sign_in_url
                 │  operator copies/exports the two IDs (NOT remote state)
                 │  TF_VAR_idc_instance_arn / TF_VAR_identity_store_id
                 ▼
subscription/terraform   (state key: workshops/<id>/subscription/terraform.tfstate)
   consumes: var.idc_instance_arn + var.identity_store_id
   creates:  users, groups, memberships, permission set, account assignments
                 │  manifest -> otps.csv + manifest.json
                 ▼
claim-service/terraform  (state key: workshops/<id>/claim-service/terraform.tfstate)
   optional self-serve distribution
```

The ordering is **backend → foundation → subscription → claim-service**. The
foundation stack sits outside the per-workshop loop entirely: a single apply, up
front, that every workshop then consumes. Nothing in the per-workshop
provision/teardown tasks touches it (R7.1, R7.7).

### Grounding: the resource recovered from history

The `awscc_sso_instance` resource and the `awscc` provider used to live in
`subscription/terraform/identity_center.tf` and `versions.tf`. The
`multi-workshop-provisioning` task 1.1 removed them. Recovered verbatim from
commit `0f4ada7` (`git log -S "awscc_sso_instance" -p -- subscription/terraform/`),
the removed shapes were:

```hcl
# subscription/terraform/identity_center.tf  (REMOVED by multi-workshop task 1.1)
resource "awscc_sso_instance" "this" {
  # name is optional; helps identify the instance in the console.
  name = var.instance_name

  # AWSCC uses a list-of-objects tag shape (no provider default_tags support).
  tags = [for k, v in var.default_tags : { key = k, value = v }]
}

locals {
  identity_store_id = awscc_sso_instance.this.identity_store_id
  instance_arn      = awscc_sso_instance.this.instance_arn
}
```

```hcl
# subscription/terraform/versions.tf  required_providers (REMOVED awscc entry)
awscc = {
  source  = "hashicorp/awscc"
  version = ">= 1.0.0"
}
```

The foundation stack re-homes exactly these shapes, unchanged except for the
file/stack they live in and the addition of the four outputs the operator wires
forward. This is a faithful move, not a redesign.

## Architecture

### The single owned resource

```
foundation/terraform:
   var.instance_name   (OPTIONAL; default "kiro-login")     ─┐
   var.default_tags    (map(string))                          ├─> awscc_sso_instance "this"
                                                               │       name = var.instance_name
                                                               │       tags = [for k,v in var.default_tags : {key=k, value=v}]
                                                               ▼
   locals.instance_arn      = awscc_sso_instance.this.instance_arn
   locals.identity_store_id = awscc_sso_instance.this.identity_store_id
   locals.resolved_region   = data.aws_region.current.region   (hashicorp/aws)
         │
         ├─> output "instance_arn"      = local.instance_arn
         ├─> output "identity_store_id" = local.identity_store_id
         ├─> output "region"            = local.resolved_region
         └─> output "sign_in_url"       = "https://${local.identity_store_id}.awsapps.com/start"

   NO users / groups / memberships / permission sets / account assignments  (R1.2-R1.6)
   NO remote_state reference to subscription                                 (R3.4)
```

The stack creates **exactly one** account-level IdC instance via
`awscc_sso_instance` (R1.1) and nothing else from the Identity Center surface
(R1.2–R1.6). The `awscc` (AWS Cloud Control) provider is the only provider that
can CREATE an IdC instance — `awscc_sso_instance` maps to the
`AWS::SSO::Instance` CloudFormation type (R5.1). The `hashicorp/aws` provider is
present only to resolve the concrete region for the `region` output via
`data.aws_region.current` (R5.2, R5.6), mirroring the subscription and backend
stacks.

### Provider / region resolution (mirrors the subscription stack)

Region and credentials come from the environment so the same config is reusable
across accounts, exactly as `subscription/terraform/providers.tf` does today:

```
AWS_REGION  (mise sources it from IDC_REGION in the git-ignored .env)
     │  var.aws_region == ""  ->  provider inherits AWS_REGION (R5.3)
     │  var.aws_region != ""  ->  provider uses that value     (R5.4)
     ▼
provider "aws"   { region = var.aws_region != "" ? var.aws_region : null
                   profile = var.aws_profile != "" ? var.aws_profile : null  (R5.5)
                   default_tags { tags = var.default_tags } }
provider "awscc" { region = var.aws_region != "" ? var.aws_region : null
                   profile = var.aws_profile != "" ? var.aws_profile : null  (R5.5) }

data "aws_region" "current" {}   ->  local.resolved_region  (the concrete region, R5.6)
```

The IdC instance lands in whatever region the `awscc` provider targets. Both
providers read the same `var.aws_region` / `var.aws_profile`, so the `aws`
data-source region and the `awscc` creation region are always the same concrete
value — the `region` output reports it (R5.6). The `awscc` provider has no
`default_tags` block (it is unsupported there); tags reach the instance through
the list-of-objects `tags` argument instead (R1.9).

### Shared remote-state backend with a foundation-scoped key

The foundation stack uses the same shared S3 backend as the other stacks (R4.1),
with a tracked, value-free `backend "s3" {}` block and a git-ignored, keyless
`backend.hcl` whose values are supplied at init time (R4.2):

```
backend.tf (tracked, value-free):   terraform { backend "s3" {} }

backend.hcl (git-ignored, KEYLESS; written by backend-bootstrap or copied from .example):
   bucket         = "kiro-tofu-state-<account_id>"
   region         = "<AWS_REGION>"
   dynamodb_table = "kiro-tofu-locks"
   encrypt        = true
   # NO key line — supplied at init (R4.2, R4.7)

init (foundation):
   tofu init -reconfigure -input=false \
     -backend-config=backend.hcl \
     -backend-config="key=foundation/terraform.tfstate"       (R4.3, R6.4)

state layout in the one shared bucket:
   foundation/terraform.tfstate            ← this stack (NO workshops/<id>/ prefix, R4.4)
   workshops/<id>/subscription/terraform.tfstate
   workshops/<id>/claim-service/terraform.tfstate
```

Because the IdC instance is a single shared foundation resource — not
workshop-scoped — the state key is the bare `foundation/terraform.tfstate`,
carrying no `workshops/<id>/` prefix (R4.3, R4.4). This is the one difference
from the subscription/claim-service keys, which are workshop-namespaced.

### Backend bootstrap extension

The `backend/terraform` stack already renders keyless `backend.hcl` bodies for
the subscription and claim-service stacks from a shared `local._backend_hcl_body`
and the `mise run backend-bootstrap` task writes each one via
`tofu output -raw`. The foundation stack joins that pattern: a new
`backend_hcl_foundation` output (identical keyless body) plus one more write line
in the bootstrap task (R4.5). This is the ONLY change outside `foundation/` and
it lives in the backend stack, not the subscription stack.

### Guarded, deliberate teardown

Destroying the shared IdC instance must never happen by accident during a
routine per-workshop teardown. Two guards stand in front of it:

```
mise run foundation-destroy
   1. backend.hcl existence + residual-key guards (R4.6, R4.7)
   2. typed-phrase guard: operator must type exactly "destroy-foundation"   (R7.2)
         mismatch -> non-zero exit, delete nothing                          (R7.4)
         match    -> proceed to step 3                                      (R7.3)
   3. tofu init -reconfigure (foundation key) ; tofu destroy
         tofu's OWN apply/destroy approval prompt still required            (R7.5)
```

The foundation stack is excluded from every per-workshop task — the
`provision*`, `teardown*`, and `claim-*` tasks never reference the foundation
key or resource (R7.1, R7.7). Only the dedicated `foundation-destroy` task can
reach the instance, and only past both the typed phrase and tofu's own prompt.

## Components and Interfaces

The stack mirrors the file layout of `subscription/terraform` and
`backend/terraform`. All files live under `foundation/terraform/`.

### 1. `versions.tf`

Declares both required providers and the value-free backend block:

```hcl
terraform {
  # OpenTofu is pinned in the project mise.toml. Creating the IdC account
  # instance needs the hashicorp/awscc provider (Cloud Control); the region
  # output resolves through hashicorp/aws >= 5.56.0.
  required_version = ">= 1.6"

  required_providers {
    # Resolves the concrete region for the `region` output. hashicorp/aws has
    # NO resource to *create* an Identity Center instance.
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.56.0"
    }
    # Cloud Control provider: the only way to CREATE an IdC *instance*
    # (awscc_sso_instance maps to the AWS::SSO::Instance CloudFormation type,
    # which creates an account instance in a standalone or member account).
    awscc = {
      source  = "hashicorp/awscc"
      version = ">= 1.0.0"
    }
  }

  # Remote S3 state is REQUIRED (it is what makes teardown work from a different
  # machine later). The backend block lives in the tracked backend.tf; the
  # account-specific values come from the git-ignored, keyless backend.hcl at
  # `tofu init` time. See RUNBOOK and backend/README.md.
  backend "s3" {}
}
```

The `required_providers` block restores the exact `awscc` entry recovered from
history (`hashicorp/awscc >= 1.0.0`) and keeps `hashicorp/aws >= 5.56.0`
consistent with the sibling stacks (R5.1, R5.2).

> Note: the `backend "s3" {}` partial block may live in `versions.tf` or a
> separate `backend.tf`. The subscription stack keeps it in a dedicated
> `backend.tf`; the foundation stack follows that split (see §4) so the two
> stacks read identically. The `terraform {}` block in `versions.tf` carries
> only `required_version` + `required_providers`.

### 2. `providers.tf`

Configures both providers from the environment, with the same region/profile
precedence as the subscription stack, plus the region data source:

```hcl
# Region and credentials come from the environment so the same config is
# reusable across accounts: AWS_PROFILE / AWS_REGION (set by mise from .env), an
# explicit `-var aws_region=...`, or the standard AWS SDK credential chain.
#
# Region precedence: an explicit -var/tfvars wins; when aws_region is empty (the
# default) the providers inherit AWS_REGION from the environment. The IdC account
# instance is created in whatever region these providers target.

provider "aws" {
  region  = var.aws_region != "" ? var.aws_region : null
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = var.default_tags
  }
}

# The Cloud Control provider that creates the IdC instance. Same region/profile
# resolution as the aws provider so the instance lands in the configured region.
# awscc has no default_tags block; tags are passed on the resource (list shape).
provider "awscc" {
  region  = var.aws_region != "" ? var.aws_region : null
  profile = var.aws_profile != "" ? var.aws_profile : null
}

# Resolve the region the providers actually used (var.aws_region or the
# AWS_REGION env fallback), so the region output reports a concrete value.
data "aws_region" "current" {}
```

(R5.2–R5.6). The `aws` provider carries `default_tags` to match the sibling
stacks; the IdC instance itself is tagged through the `awscc` resource argument,
since `awscc` does not honor `default_tags`.

### 3. `variables.tf`

Provider/environment variables mirror the subscription stack verbatim, plus the
one optional `instance_name`:

```hcl
variable "aws_region" {
  description = <<-EOT
    Region to create the IAM Identity Center account instance in. Must be a
    region Kiro supports for IdC.

    Leave empty (the default) to inherit AWS_REGION from the environment — mise
    sources it from the git-ignored .env file, so change the region there
    (`cp .env.example .env`) rather than editing committed files. Set a value
    here or via `-var`/tfvars only to pin it explicitly.
  EOT
  type        = string
  default     = ""
}

variable "aws_profile" {
  description = "AWS CLI/SDK profile to use. Empty string falls back to the default SDK credential chain / AWS_PROFILE env var."
  type        = string
  default     = ""
}

variable "default_tags" {
  description = "Tags applied to every taggable resource, including the IdC instance (via the AWSCC list-of-objects tag shape)."
  type        = map(string)
  default = {
    Project   = "kiro-subscriptions"
    ManagedBy = "opentofu"
    Purpose   = "kiro-login-only"
  }
}

variable "instance_name" {
  description = <<-EOT
    Optional name applied to the IdC account instance (helps identify it in the
    console). Supply via tfvars or TF_VAR_instance_name to override. Defaults to
    "kiro-login" when not supplied.
  EOT
  type        = string
  default     = "kiro-login"
}
```

`instance_name` is OPTIONAL with the default `kiro-login` (R1.7, R1.8). When the
operator supplies a value it is applied to the instance (R1.7); when omitted the
default is applied (R1.8). The `default_tags` default matches the subscription
stack so the two stacks tag identically.

### 4. `backend.tf` and `backend.hcl.example`

`backend.tf` is tracked and value-free, identical in intent to the subscription
stack's:

```hcl
# Remote S3 state backend — REQUIRED. This file is TRACKED and value-free. The
# account-specific values (bucket, region, lock table) live in the git-ignored
# backend.hcl and are supplied at init time:
#   tofu init -backend-config=backend.hcl
# backend.hcl is normally written by `mise run backend-bootstrap`; the
# backend.hcl.example escape hatch exists for editing by hand.
terraform {
  backend "s3" {}
}
```

`backend.hcl.example` is the tracked, keyless template (R4.2, R4.4). It mirrors
the subscription template but documents the foundation init-time key:

```hcl
# Template for the git-ignored backend.hcl. You normally DON'T touch this:
# `mise run backend-bootstrap` creates the bucket + lock table AND writes
# backend.hcl for you (bucket name derived from your account id). This .example
# is the escape hatch — copy it and fill in the values if editing by hand:
#
#   cp backend.hcl.example backend.hcl   # then edit
#   tofu init -backend-config=backend.hcl \
#     -backend-config="key=foundation/terraform.tfstate"
#
# This stack REUSES the shared state bucket created by the backend/ stack — do
# NOT create a new bucket. The state key is supplied at init time and is NOT in
# this file; the foundation key is `foundation/terraform.tfstate` (no
# workshops/<id>/ prefix, since the IdC instance is a single shared resource).

bucket         = "kiro-tofu-state-<account_id>"   # shared bucket; your 12-digit account id
region         = "<AWS_REGION>"                    # match AWS_REGION in .env (e.g. us-east-1)
dynamodb_table = "kiro-tofu-locks"
encrypt        = true
```

The file carries no `key` line; the key is an init-time argument (R4.2, R4.4,
R4.7).

### 5. `identity_center.tf` (the single owned resource)

Re-homes the resource recovered from history, plus the locals that surface the
outputs:

```hcl
# ===========================================================================
# IAM Identity Center — ACCOUNT instance owned by the Foundation IdC service
# ===========================================================================
#
# awscc_sso_instance creates an *account* instance of Identity Center in the
# account/region the provider targets (maps to AWS::SSO::Instance). This is the
# single, long-lived, shared instance every workshop's subscription stack
# consumes via var.idc_instance_arn / var.identity_store_id.
#
# PRECONDITION (cannot be enforced from here): the org management account must
# have permitted member-account instance creation. If it has not, apply fails
# with an authorization error on this resource. See RUNBOOK step 0.
#
# One account instance per account (across all regions). Import an existing one:
#   tofu import awscc_sso_instance.this <instance_arn>

resource "awscc_sso_instance" "this" {
  # name is optional; helps identify the instance in the console. Defaults to
  # "kiro-login" (var.instance_name).
  name = var.instance_name

  # AWSCC uses a list-of-objects tag shape (no provider default_tags support).
  tags = [for k, v in var.default_tags : { key = k, value = v }]
}

locals {
  identity_store_id = awscc_sso_instance.this.identity_store_id
  instance_arn      = awscc_sso_instance.this.instance_arn
  resolved_region   = data.aws_region.current.region
}
```

The resource shape (`name`, the list-of-objects `tags`) is identical to the
recovered history (R1.1, R1.7–R1.9). The locals surface the ARN and identity
store id from the created resource (not from a variable, unlike the subscription
stack, which now reads them from variables).

> File naming: `identity_center.tf` matches the subscription stack's filename
> for the IdC surface; `main.tf` would be equally acceptable. This design uses
> `identity_center.tf` for continuity with the recovered source.

### 6. `outputs.tf`

Emits the four values the operator wires into the subscription stack (R2.1–R2.4),
each as a plain string so `tofu output -raw` emits it without quotes (R2.5):

```hcl
output "instance_arn" {
  description = "ARN of the IAM Identity Center account instance. Export into the subscription stack as TF_VAR_idc_instance_arn."
  value       = local.instance_arn
}

output "identity_store_id" {
  description = "Identity store ID backing the account instance (d-xxxxxxxxxx). Export into the subscription stack as TF_VAR_identity_store_id."
  value       = local.identity_store_id
}

output "region" {
  description = "Region the IdC instance was created in (the concrete region the providers resolved to)."
  value       = local.resolved_region
}

# The default AWS access portal sign-in URL is derived directly from the
# identity store id (format: d-xxxxxxxxxx.awsapps.com/start). Same derivation the
# subscription stack uses, so a vanity-subdomain caveat applies there too.
output "sign_in_url" {
  description = "Default AWS access portal sign-in URL derived from the identity store id."
  value       = "https://${local.identity_store_id}.awsapps.com/start"
}
```

The `sign_in_url` is derived from `identity_store_id` with the exact format
`https://<identity-store-id>.awsapps.com/start`, matching the subscription
stack's `outputs.tf` derivation (R2.4). All four outputs are scalar strings, so
`tofu output -raw <name>` emits a bare value assignable to a `TF_VAR_*`
(R2.5). The ARN and identity store id are exposed only as outputs — never
written anywhere the subscription stack reads via remote state (R3.1).

### 7. Backend bootstrap extension (`backend/terraform/outputs.tf`)

The backend stack renders keyless `backend.hcl` bodies from the shared
`local._backend_hcl_body`. Add the foundation to `_backend_hcl_for` and a new
output beside the existing `backend_hcl` / `backend_hcl_claim_service`:

```hcl
locals {
  # existing _backend_hcl_body (keyless: bucket, region, dynamodb_table, encrypt)
  _backend_hcl_for = {
    subscription  = local._backend_hcl_body
    claim_service = local._backend_hcl_body
    foundation    = local._backend_hcl_body   # NEW — identical keyless body
  }
}

# Ready-to-use backend.hcl body for the foundation stack. `mise run
# backend-bootstrap` writes this to ../../foundation/terraform/backend.hcl via
# `tofu output -raw backend_hcl_foundation`.
output "backend_hcl_foundation" {
  description = "The full foundation/terraform/backend.hcl body (mise writes it for you; tofu init -backend-config=backend.hcl reads it)."
  value       = local._backend_hcl_for["foundation"]
}
```

The body is identical to the other stacks' (keyless) — isolation comes from the
init-time key, not from the file (R4.2, R4.5). This is the only change to the
backend stack and is purely additive.

### 8. mise tasks (`mise.toml`)

Three tasks mirror the subscription/claim-service plan/apply/destroy conventions
(`set -eu`, `dir=`, the `tofu init -reconfigure -input=false
-backend-config=backend.hcl -backend-config="key=..."` pattern, the backend.hcl
existence + residual-`key` grep guards, and prompt-before-mutate). The foundation
key is the bare `foundation/terraform.tfstate` (R6.4), and `foundation-destroy`
adds the typed-phrase guard.

A shared preamble (used by all three) enforces the backend guards (R4.6, R4.7):

```toml
# =============================================================================
# === foundation/ stack ===
# =============================================================================
# Creates and owns the account-level IdC instance — the single, long-lived,
# shared resource every workshop's subscription stack consumes. Applied ONCE and
# reused across every workshop (NOT per workshop). Excluded from every
# per-workshop provision/teardown task. backend.hcl must exist first (written by
# `mise run backend-bootstrap`, same shared bucket as the other stacks).

[tasks.foundation-plan]
description = "DRY RUN: tofu init + plan for the Foundation IdC instance (creates nothing)"
dir = "foundation/terraform"
run = """
set -eu
if [ ! -f backend.hcl ]; then
  echo "ERROR: foundation/terraform/backend.hcl not found." >&2
  echo "Run the backend bootstrap first (it writes this file):" >&2
  echo "  mise run backend-bootstrap" >&2
  echo "or copy the template by hand: cp backend.hcl.example backend.hcl" >&2
  exit 1
fi
# A residual 'key' in backend.hcl conflicts with the init-time key (R4.7).
if grep -Eq '^[[:space:]]*key[[:space:]]*=' backend.hcl; then
  echo "ERROR: remove the 'key' line from backend.hcl; it is supplied at init time." >&2
  exit 1
fi
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=foundation/terraform.tfstate" \
  || { echo "ERROR: backend init failed; not planning." >&2; exit 1; }
tofu plan
"""

[tasks.foundation-apply]
description = "Apply: create (or re-converge) the Foundation IdC instance (prompts to approve)"
dir = "foundation/terraform"
run = """
set -eu
if [ ! -f backend.hcl ]; then
  echo "ERROR: foundation/terraform/backend.hcl not found (see foundation-plan)." >&2
  exit 1
fi
if grep -Eq '^[[:space:]]*key[[:space:]]*=' backend.hcl; then
  echo "ERROR: remove the 'key' line from backend.hcl; it is supplied at init time." >&2
  exit 1
fi
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=foundation/terraform.tfstate" \
  || { echo "ERROR: backend init failed; not applying." >&2; exit 1; }
tofu apply
# Only reached after a clean apply (set -eu). Surface the values to wire forward.
echo ""
echo "Foundation IdC applied. Wire these into the subscription stack:"
echo "  export TF_VAR_idc_instance_arn=\\"$(tofu output -raw instance_arn)\\""
echo "  export TF_VAR_identity_store_id=\\"$(tofu output -raw identity_store_id)\\""
echo "Sign-in URL: $(tofu output -raw sign_in_url)  (region: $(tofu output -raw region))"
"""

[tasks.foundation-destroy]
description = "DESTRUCTIVE: delete the shared Foundation IdC instance. Requires typing 'destroy-foundation'; then prompts tofu's own approval."
dir = "foundation/terraform"
run = """
set -eu
# --- Typed-phrase guard (R7.2-R7.5) --------------------------------------------
# The IdC instance is shared across every workshop; deleting it is deliberate.
# Require the operator to type the fixed phrase before anything proceeds. A
# mismatch exits non-zero and deletes nothing; a match proceeds to tofu's OWN
# apply/destroy approval prompt (a second, independent gate).
printf 'This DELETES the shared Foundation IdC instance.\\n'
printf 'Type exactly "destroy-foundation" to proceed: '
read -r CONFIRM
if [ "$CONFIRM" != "destroy-foundation" ]; then
  echo "ERROR: confirmation phrase did not match 'destroy-foundation'; deleting nothing." >&2
  exit 1
fi

if [ ! -f backend.hcl ]; then
  echo "ERROR: foundation/terraform/backend.hcl not found (see foundation-plan)." >&2
  exit 1
fi
if grep -Eq '^[[:space:]]*key[[:space:]]*=' backend.hcl; then
  echo "ERROR: remove the 'key' line from backend.hcl; it is supplied at init time." >&2
  exit 1
fi
tofu init -reconfigure -input=false -backend-config=backend.hcl \
  -backend-config="key=foundation/terraform.tfstate" \
  || { echo "ERROR: backend init failed; not destroying." >&2; exit 1; }
# tofu destroy still prompts for its own approval before deleting (R7.5).
tofu destroy
"""
```

`foundation-plan` runs init + plan and changes no AWS resources (R6.1).
`foundation-apply` runs init + apply and prompts before mutating (R6.2).
`foundation-destroy` runs destroy and prompts before mutating (R6.3), behind the
typed-phrase guard (R7.2–R7.5). Every init supplies the foundation key via
`-backend-config="key=foundation/terraform.tfstate"` (R6.4), and `set -eu`
propagates a non-zero `tofu init` so apply/destroy run only after a clean init
(R6.5). None of the existing `provision*`, `teardown*`, or `claim-*` tasks are
changed, so the foundation stack stays excluded from the per-workshop lifecycle
(R7.1, R7.7).

### 9. Documentation (`foundation/README.md` + `foundation/RUNBOOK.md`)

A README (concepts) and a RUNBOOK (run order) matching the style of
`backend/README.md` and `subscription/RUNBOOK.md`. The RUNBOOK covers:

- **Step 0 — management-account enablement precondition** (R9.1–R9.3): creating
  an account instance requires the AWS Organizations management account to have
  enabled member-account IdC instances; this is a one-time, irreversible toggle;
  if it is not enabled the apply fails with an authorization error on
  `awscc_sso_instance`, and that error IS the missing enablement.
- **Create-then-wire order** (R10.1–R10.4): run `backend-bootstrap`, then
  `foundation-apply`, then capture `instance_arn` + `identity_store_id`, then
  export `TF_VAR_idc_instance_arn` / `TF_VAR_identity_store_id` (or write tfvars)
  for the subscription stack — the foundation stack is applied once and reused
  across every workshop.
- **Idempotency + import** (R8.1–R8.3): a re-apply makes no changes absent a
  config change; AWS permits one account instance per account across all regions;
  if one already exists outside this stack's state, import it with
  `tofu import awscc_sso_instance.this <instance_arn>`.
- **Destructive teardown note** (R7.6): deleting the IdC instance is destructive,
  and the management-account enablement of account instances cannot be reversed.

The README links from the root README's documentation index and journey table so
the foundation phase sits between Phase 1 (backend) and Phase 2 (subscription).

## Data Models

### `instance_name` variable

```hcl
string, optional, default "kiro-login"
# supplied via tfvars or TF_VAR_instance_name; applied to awscc_sso_instance.this.name
```

### `awscc_sso_instance.this` arguments

| Argument | Type                               | Source                                             |
| -------- | ---------------------------------- | -------------------------------------------------- |
| `name`   | string                             | `var.instance_name` (default `kiro-login`)         |
| `tags`   | list(object({ key, value }))       | `[for k, v in var.default_tags : {key=k, value=v}]`|

The `tags` argument is the AWS Cloud Control list-of-objects shape — a list of
`{ key, value }` objects, not a map (R1.9). This is distinct from the
`hashicorp/aws` provider's `default_tags`/`tags` map shape.

### Outputs (all scalar strings; `tofu output -raw` emits unquoted — R2.5)

| Output              | Value                                                   | Requirement |
| ------------------- | ------------------------------------------------------- | ----------- |
| `instance_arn`      | `local.instance_arn`                                    | R2.1        |
| `identity_store_id` | `local.identity_store_id`                               | R2.2        |
| `region`            | `local.resolved_region` (`data.aws_region.current.region`) | R2.3     |
| `sign_in_url`       | `https://${local.identity_store_id}.awsapps.com/start`  | R2.4        |

### State-key scheme

```
foundation/terraform.tfstate            ← this stack (NO workshops/<id>/ prefix, R4.3/R4.4)
bucket:     kiro-tofu-state-<account_id> (shared with the other stacks, R4.1)
lock table: kiro-tofu-locks              (shared)
```

### Keyless `backend.hcl` body (rendered by the backend bootstrap, R4.5)

```
bucket         = "kiro-tofu-state-<account_id>"
region         = "<AWS_REGION>"
dynamodb_table = "kiro-tofu-locks"
encrypt        = true
# NO key line — supplied at init time (R4.2, R4.7)
```

### Typed-phrase guard

```
fixed phrase: "destroy-foundation"
match  -> proceed to tofu's own destroy approval prompt (R7.3, R7.5)
mismatch (anything else, including empty/whitespace) -> exit non-zero, delete nothing (R7.4)
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all
valid executions of a system — essentially, a formal statement about what the
system should do. Properties serve as the bridge between human-readable
specifications and machine-verifiable correctness guarantees.*

This feature is primarily an IaC stack. The `awscc_sso_instance` creation,
provider/region resolution, backend init, and re-apply idempotency are
configuration facts or AWS/provider behaviors — verified by `tofu validate` /
`tofu console` offline checks, static text-fact assertions over the `.tf`
sources, and (where AWS is available) integration/smoke tests. **Creating the
IdC instance itself needs AWS and is out of scope for offline tests.** They do
not appear below.

What remains are a handful of **pure derivations and guards** that vary with
input and carry universal properties. Following the repo's established pattern
(as in `multi-workshop-provisioning`), each is modelled as a **pure Python
mirror** of the HCL/shell logic under `foundation/tests/` (or a shared
`tests/`), driven with randomized inputs via Hypothesis at a minimum of **100
iterations** each. Each property test is tagged
`**Feature: foundation-idc-service, Property N: <text>**`.

### Property 1: AWSCC tag transform is a faithful bijection with default_tags

*For any* `default_tags` map of string keys to string values, the AWSCC
list-of-objects transform (`[for k, v in var.default_tags : { key = k, value = v }]`)
SHALL produce a list containing exactly one `{ key: k, value: v }` object for
every `(k, v)` entry in the map and no other objects — so the list length equals
the map size and the set of `(key, value)` pairs equals the map's entries
exactly.

**Validates: Requirements 1.9**

### Property 2: sign_in_url is the exact portal format of the identity store id

*For any* identity store id string, the `sign_in_url` output SHALL equal exactly
`"https://" + identity_store_id + ".awsapps.com/start"` — the prefix and suffix
are fixed and the identity store id is spliced in verbatim, so the id can be
recovered by stripping the fixed prefix and suffix.

**Validates: Requirements 2.4**

### Property 3: The rendered backend.hcl body is keyless and identical across stacks

*For any* `(bucket, region, dynamodb_table)` triple, the backend bootstrap's
rendered `backend.hcl` body for the foundation stack SHALL carry exactly those
three values plus `encrypt = true`, SHALL contain no `key` line, and SHALL be
byte-identical to the rendered subscription and claim-service bodies.

**Validates: Requirements 4.2, 4.5, 4.7**

### Property 4: The residual-key guard flags exactly the files that assign a key

*For any* `backend.hcl` text, the residual-`key` guard predicate (grep
`^[[:space:]]*key[[:space:]]*=`) SHALL report present if and only if the text
contains a non-comment line that assigns `key = ...`, so the plan/apply/destroy
tasks stop with a non-zero exit on exactly those files and proceed on exactly
the files that omit a `key` assignment.

**Validates: Requirements 4.7**

### Property 5: The foundation state key is the fixed, prefix-free constant

*For any* invocation of a foundation task, the init-time state key SHALL be
exactly `foundation/terraform.tfstate` and SHALL NOT begin with a
`workshops/<id>/` segment — distinguishing it from the workshop-scoped
subscription and claim-service keys.

**Validates: Requirements 4.3, 4.4, 6.4**

### Property 6: The empty-string provider selector passes through or falls back

*For any* string `s`, the provider region/profile selector
(`s != "" ? s : null`) SHALL yield `null` when `s` is the empty string (so the
provider falls back to the environment) and SHALL yield `s` verbatim for every
non-empty string — the identical rule governs both `var.aws_region` and
`var.aws_profile` on both the `aws` and `awscc` providers.

**Validates: Requirements 5.3, 5.4, 5.5**

### Property 7: The teardown guard accepts exactly the fixed phrase

*For any* typed confirmation string `s`, the `foundation-destroy` typed-phrase
guard SHALL proceed if and only if `s` equals exactly `destroy-foundation`, and
SHALL stop with a non-zero exit (deleting nothing) for every other string —
including case variants, surrounding whitespace, near-misses, and the empty
string. (On accept, `tofu destroy`'s own approval prompt is still required — a
layered gate verified by smoke test, not part of this acceptor.)

**Validates: Requirements 7.2, 7.3, 7.4**

## Error Handling

- **Management-account enablement missing (R9.1–R9.3).** Creating an account
  instance requires the AWS Organizations management account to have enabled
  member-account IdC instances — a one-time, irreversible toggle this stack
  cannot enforce. If it is not enabled, `tofu apply` fails with an authorization
  error on the `awscc_sso_instance.this` resource. The RUNBOOK (Step 0)
  identifies that specific authorization error as the missing enablement so an
  operator can diagnose it without guesswork.

- **An account instance already exists outside this stack's state (R8.2, R8.3).**
  AWS permits exactly one account instance per account across all regions. If one
  already exists but is not yet tracked here, a fresh apply would conflict. The
  RUNBOOK directs the operator to adopt it instead:
  `tofu import awscc_sso_instance.this <instance_arn>`. After import, a plan
  shows no changes (R8.1).

- **Re-apply with no config change (R8.1).** Because the stack owns a single
  resource whose arguments (`name`, `tags`) are deterministic from the inputs,
  re-applying after a successful apply produces an empty plan — no churn, no
  duplicate (AWS would reject a second account instance anyway).

- **`backend.hcl` missing (R4.6).** Each foundation task greps for `backend.hcl`
  before init; if absent it exits non-zero and names the missing file, pointing
  the operator at `mise run backend-bootstrap` (or the `backend.hcl.example`
  escape hatch). No init, plan, apply, or destroy runs.

- **Residual `key` in `backend.hcl` (R4.7).** The key is supplied at init time;
  a `key =` line left in `backend.hcl` conflicts with it. Each task greps for a
  `key =` line and exits non-zero with a message that the key is supplied at init
  time, before running init. The rendered body and the `.example` template never
  include one.

- **`tofu init` fails (R6.5).** `set -eu` propagates a non-zero `tofu init`, and
  the explicit `|| { echo ...; exit 1; }` guard stops the task before apply or
  destroy, so a backend failure changes nothing.

- **Teardown confirmation mismatch (R7.4).** `foundation-destroy` reads the typed
  phrase and compares it for exact equality with `destroy-foundation`. Any
  mismatch exits non-zero before init/destroy, deleting nothing. A match still
  faces `tofu destroy`'s own approval prompt (R7.5).

- **Foundation instance never reachable from a per-workshop task (R7.1, R7.7).**
  No `provision*`, `teardown*`, or `claim-*` task references the foundation state
  key or the `awscc_sso_instance` resource, so a routine per-workshop teardown
  can never enumerate or delete the shared instance. The subscription stack holds
  no managed foundation resource (it only consumes the ARN/id via variables), so
  its `tofu destroy` has nothing to target.

## Testing Strategy

The testable surfaces are the pure derivations and guards called out in
Correctness Properties; everything else is Terraform configuration, AWS wiring,
or documentation, verified by offline validation, static text-facts, and
(where AWS is available) smoke/integration tests. The IdC instance creation
itself requires AWS and is **out of scope for offline tests**.

Property tests follow the repo convention `tests/test_*_property.py`
(pytest + Hypothesis, min 100 iterations); example/smoke/text-fact tests follow
`tests/test_*.py`. Property tests drive **pure Python mirrors** of the HCL/shell
logic (no AWS). Implementation languages are the repo's existing ones — HCL /
OpenTofu for the stack, Python for the test mirrors, and `mise.toml` for the
task layer.

### Property-based tests (pytest + Hypothesis, min 100 iterations each)

Each maps 1:1 to a Correctness Property above and is tagged
`**Feature: foundation-idc-service, Property N: <text>**`:

- **AWSCC tag transform** (pure mirror of `[for k, v in default_tags : {key, value}]`)
  → Property 1 (bijection with the tag map).
- **`sign_in_url` derivation** (pure mirror of the string interpolation) →
  Property 2 (exact portal format; id recoverable).
- **Keyless backend body** (pure mirror of `_backend_hcl_body`) → Property 3
  (keyless, three values + `encrypt`, identical across all three stacks).
- **Residual-key predicate** (pure mirror of the grep guard) → Property 4
  (flags exactly files that assign `key`).
- **State-key scheme** (pure mirror of the foundation key constant) → Property 5
  (equals `foundation/terraform.tfstate`; no `workshops/` prefix).
- **Provider empty-string selector** (pure mirror of `s != "" ? s : null`) →
  Property 6 (empty → null fallback; else verbatim; region and profile alike).
- **Typed-phrase acceptor** (pure mirror of `[ "$CONFIRM" = "destroy-foundation" ]`)
  → Property 7 (accept iff exact match; reject case/whitespace/near-miss/empty).

### Offline validation and static text-fact tests (no AWS)

- **`tofu validate` / `tofu console`.** `tofu validate` passes for the stack;
  `tofu console` confirms the pure expressions offline where possible (e.g. the
  `sign_in_url` interpolation and the tag transform over a sample map, the
  region/profile ternary over `""` and a value).
- **Single owned resource (R1.1).** Assert `identity_center.tf` declares exactly
  one `awscc_sso_instance "this"` block.
- **No extra IdC resources (R1.2–R1.6).** Assert the `foundation/terraform/*.tf`
  sources contain none of `aws_identitystore_user`, `aws_identitystore_group`,
  `aws_identitystore_group_membership`, `aws_ssoadmin_permission_set`,
  `aws_ssoadmin_account_assignment`.
- **`instance_name` default + wiring (R1.7, R1.8).** Assert the variable default
  is `kiro-login` and the resource sets `name = var.instance_name`; a
  `tofu console`/plan over two fixtures (unset → `kiro-login`; set → the value)
  confirms the passthrough.
- **Outputs exist and are scalar strings (R2.1–R2.3, R2.5).** Assert `outputs.tf`
  declares `instance_arn`, `identity_store_id`, `region`, and `sign_in_url` bound
  to the right locals/derivation, and that each output value is a scalar string
  (so `tofu output -raw` emits a bare, assignable value).
- **Decoupling / no remote state (R3.1, R3.3, R3.4).** Assert neither stack
  declares a `data "terraform_remote_state"` referencing the other; the
  foundation exposes the ARN/id only as outputs.
- **Required providers (R5.1, R5.2).** Assert `versions.tf` `required_providers`
  includes `hashicorp/awscc` and `hashicorp/aws` with the recovered constraints.
- **Backend config facts (R4.1, R4.2, R4.4).** Assert `backend.tf` is a
  value-free `backend "s3" {}` and `backend.hcl.example` carries no `key` line.
- **mise task facts (R6.1–R6.4).** Assert `foundation-plan` / `foundation-apply`
  / `foundation-destroy` exist with the init-key argument
  `key=foundation/terraform.tfstate` and the plan/apply/destroy commands, and
  that `backend-bootstrap` writes `../../foundation/terraform/backend.hcl`.
- **Per-workshop exclusion (R7.1, R7.7).** Assert no `provision*`, `teardown*`,
  or `claim-*` task references `foundation/terraform.tfstate` or
  `awscc_sso_instance`.
- **Scope boundary (R3.2).** Assert the subscription stack's `.tf` is unchanged
  by this spec and still declares `var.idc_instance_arn` / `var.identity_store_id`
  (see "Scope boundary" below).

### Example / fail-closed tests (shell task behavior; no AWS)

- **Missing `backend.hcl` (R4.6).** Run a foundation task with no `backend.hcl`;
  assert a non-zero exit and a message naming the missing file.
- **`tofu init` fail-closed (R6.5).** Simulate a failing init; assert the task
  stops before apply/destroy.
- **Teardown guard reject (R7.4).** Pipe a non-matching phrase to
  `foundation-destroy`; assert a non-zero exit and that `tofu destroy` is never
  reached.

### Integration / smoke tests (require AWS; out of scope offline)

These require AWS and the management-account enablement, so they are documented
but not run in the offline suite:

- **Instance creation (R1.1), region resolution (R5.3–R5.6), raw outputs
  (R2.5).** An apply in a test account creates one instance, the `region` output
  reports the concrete region, and `tofu output -raw` emits bare values.
- **Idempotent re-apply (R8.1).** Apply, then plan expects "no changes".
- **Enablement-missing authorization error (R9.2).** Effectively unprovokable
  offline (enablement is irreversible once on); covered by the RUNBOOK's
  diagnosis guidance rather than an automated test.

### Documentation review (R7.6, R8.2, R8.3, R9.1, R9.3, R10.1–R10.4)

The RUNBOOK/README content is verified by review (optionally by text-fact
assertions): the create-then-wire order, capturing and exporting
`instance_arn` / `identity_store_id` via `TF_VAR_*` or tfvars, "applied once and
reused across every workshop", the `tofu import awscc_sso_instance.this <arn>`
path, the one-instance-per-account statement, the management-account enablement
precondition and its authorization-error diagnosis, and the
destructive/irreversible teardown note.

### Note on configuration facts

Terraform provider wiring, the `-reconfigure` backend behavior, `set -eu`
fail-closed semantics, and `tofu output -raw` quoting are tool/configuration
facts, not universal properties — they are verified by the offline-validation,
text-fact, example, and smoke tests above, not by property-based tests.

## Scope boundary — no changes to the subscription stack

This spec explicitly makes **no changes to the subscription stack's `.tf`
files**. The subscription stack continues to:

- read the instance ARN from `var.idc_instance_arn` and the identity store id
  from `var.identity_store_id` (R3.2), with `local.identity_store_id` /
  `local.instance_arn` resolving from those variables (unchanged from the
  `multi-workshop-provisioning` state); and
- create users, groups, memberships, the shared permission set, and the account
  assignments against the consumed instance.

The only change outside `foundation/terraform/` is the **additive**
`backend_hcl_foundation` output and the one extra write line in the
`backend-bootstrap` task — both in the shared `backend/terraform` stack, not the
subscription stack (R4.5). The two stacks remain wired solely through
operator-supplied variables, never through a remote-state reference (R3.3, R3.4).
