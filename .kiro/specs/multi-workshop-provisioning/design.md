# Design Document

## Overview

This design turns the kiro-provisioning-iac repository from a single-run
provisioner into a **per-workshop provisioning module**. One long-lived
management account hosts a shared, org-level IAM Identity Center (IdC) instance
and a shared S3 state backend; many short-lived Kiro workshops are provisioned
and torn down independently on top of them, coexisting without interference.

The design rests on five pillars that extend the `idc-region-account-mapping`
baseline (region split `KIRO_REGION`/`IDC_REGION` with `AWS_REGION` tracking
`IDC_REGION`; `account_id` flowing manifest → `credentials.md` header + per-user
column → claim-audit CSV, excluded from `otps.csv` and the participant claim
response; region derived only from the environment). That baseline is assumed in
place — the current `seed_claim_pool.py` already carries `account_id`,
confirming its shape.

1. **Consume the Foundation IdC (R1, R2).** `subscription/terraform` stops
   creating `awscc_sso_instance.this`. The foundation's `instance_arn` and
   `identity_store_id` become operator-supplied variables. OpenTofu now also
   owns the account access: a shared permission set and one account assignment
   per group binding that group to its child account.

2. **Explicit nested account > groups > users map (R3, R4).** A new
   `workshop_accounts` variable — `map(object)` keyed by 12-digit account id,
   each holding a `groups` map keyed by group name, each group holding a
   `user_count` — replaces the count/prefix/strategy generators. `locals.tf`
   flattens it into the exact `local.users` / `local.groups` /
   `local.memberships` shapes the existing `for_each` resources already consume.
   Each participant's `account_id` resolves through user → group → owning
   account.

3. **Workshop-keyed state in the shared S3 backend (R5, R6, R8).** The `key` is
   removed from both `backend.hcl` files and supplied at init time from
   `WORKSHOP_ID`:
   `tofu init -reconfigure -backend-config=backend.hcl -backend-config="key=workshops/<id>/subscription/terraform.tfstate"`.
   The mise tasks require `WORKSHOP_ID`, reconfigure before every mutating
   operation, export `TF_VAR_workshop_id`, and warn on a state-key collision.

4. **One claim service per workshop (R7, R9).** `claim-service/terraform`
   derives all resource names from `local.name = "credential-claim-<workshop_id>"`
   so two workshops never share a table, Lambda, Function URL, role, or policy —
   and never share a state key. `workshop_code` (the handler access-gate secret)
   stays a distinct value from `workshop_id` (the namespace).

5. **Teardown + cross-workshop isolation (R10).** `tofu destroy` on a workshop's
   state removes only that workshop's resources; it never touches the foundation
   IdC (not in state), the shared backend bucket/lock table (a separate stack),
   or any other workshop (a separate state key). A verification check snapshots
   another workshop's resources before a destroy and asserts they are unchanged
   after.

The backbone is unchanged from the baseline: **a value is declared once — in the
environment, in tfvars, or as a state key — carried through the manifest, and
read downstream, never hardcoded.** This spec extends that discipline to the
workshop namespace (`WORKSHOP_ID` → state key + resource names) and to the
foundation identity (`idc_instance_arn` / `identity_store_id` → every IdC
resource).

### Out of scope (explicit)

**Creating the Foundation IdC instance is out of scope** and belongs to a future
spec. This module *consumes* the foundation through operator-supplied inputs and
neither creates nor destroys it. Assigning the Kiro **tier** to the created
groups remains a console/API step (as today); OpenTofu owns the account
*assignment*, not the Kiro subscription tier.

### Grounding: how provisioning works today

The current single-run path (confirmed in the codebase):

```
awscc_sso_instance.this  (CREATED here)
   └─> local.identity_store_id / local.instance_arn
         └─> aws_identitystore_user/group/group_membership (for_each)

variables: user_count/group_count/user_prefix/group_prefix/
           sequence_start/sequence_padding/membership_strategy/user_emails
   └─> locals.tf generators -> local.users / local.groups / local.memberships
         └─> the for_each resources above

backend.hcl: key = "subscription/terraform.tfstate"   (hardcoded, one workshop)
claim-service: var.table_name (default credential-claim-service)
   └─> table / function_name / ${name}-lambda / ${name}-table-access
```

Three facts this spec changes: the instance is **created** (becomes consumed);
the user/group structure is **generated from counts** (becomes an explicit map);
and both the state key and the claim resource names are **fixed/single**
(become workshop-namespaced).

## Architecture

### Pillar 1 — Consume the Foundation IdC

```
operator inputs (tfvars / TF_VAR):
   idc_instance_arn   = "arn:aws:sso:::instance/ssoins-xxxxxxxxxxxx"
   identity_store_id  = "d-xxxxxxxxxx"

subscription/terraform:
   (REMOVED) resource "awscc_sso_instance" "this"
   (REMOVED) var.instance_name

   locals.identity_store_id = var.identity_store_id   (was awscc_sso_instance.this.identity_store_id)
   locals.instance_arn      = var.idc_instance_arn     (was awscc_sso_instance.this.instance_arn)

   locals.identity_store_id ──> aws_identitystore_user/group/group_membership (unchanged)
   var.idc_instance_arn     ──> aws_ssoadmin_permission_set.this.instance_arn
                            ──> aws_ssoadmin_account_assignment.this[*].instance_arn

   aws_ssoadmin_permission_set.this            (ONE shared permission set)
        │
        └─> aws_ssoadmin_account_assignment.this  (one per group)
              principal_type = "GROUP"
              principal_id   = aws_identitystore_group.this[gk].group_id
              target_type    = "AWS_ACCOUNT"
              target_id       = <account_id that owns the group>
              permission_set_arn = aws_ssoadmin_permission_set.this.arn
              instance_arn        = var.idc_instance_arn

   NO data-source discovery, NO remote_state  (R1.6)
```

The validation gate: `idc_instance_arn` and `identity_store_id` have no default
and a `length(...) > 0` validation, so an empty or unsupplied value halts the
plan before any user/group/assignment is created (R1.7).

**Permission set design — one shared vs per-group.** Two options:

- **(A) One shared permission set, reused across every group.** A single
  `aws_ssoadmin_permission_set.this`; each group gets its own
  `aws_ssoadmin_account_assignment` referencing that one permission set. The
  assignment, not the permission set, is what scopes a group to its account, so
  one permission set is sufficient for "every group gets the same access to its
  own account."
- **(B) One permission set per group.** `for_each` over groups. Only needed if
  different groups require *different* permissions.

**Chosen: (A).** The requirement (R2.1) states exactly one permission set that
"grants a Group access to its Child_Account," and every workshop group needs the
same access profile — the account differs, the permission profile does not.
Account scoping comes from each assignment's `target_id`, so one shared
permission set with per-group assignments is both the minimal and the correct
model. The permission set is bound to the foundation via
`instance_arn = var.idc_instance_arn`.

**Kiro tier stays a console step.** OpenTofu provisions the permission sets and
assignments so that AWS *account* access needs no post-apply manual action
(R2.6). Subscribing the created groups to the Kiro **tier** remains the single
remaining console/manual step — unchanged from today, and called out in the
operator docs.

### Pillar 2 — Explicit nested account > groups > users map

```
terraform.tfvars:
   workshop_accounts = {
     "111111111111" = {
       groups = {
         "team-alpha" = { user_count = 10 }
       }
     }
     "222222222222" = {
       groups = {
         "team-a" = { user_count = 3 }
         "team-b" = { user_count = 3 }
         "team-c" = { user_count = 3 }
       }
     }
   }

locals.tf FLATTEN (nested for-expressions + flatten()):

   account_id ─┐
   group name ─┼─> stable key  "<account_id>:<group>:<NN>"   (per-user)
   user index ─┘            "<account_id>:<group>"       (per-group / membership)

   local.users[k]       = { username, email, display_name, given_name, family_name }
   local.groups[gk]     = { name }
   local.memberships[k] = { user_key, group_key }
   local.group_account  = { <group_key> => <account_id> }      (group -> owning account)
   local.user_account_id= { <user_key> => <account_id> }       (user -> account via its group)

   (SAME value shapes the existing for_each resources already consume — R3.4, R3.5)

manifest / outputs:
   provisioning_manifest.account_id          (document-level; one account => that id)
   provisioning_manifest.users[k].account_id (per-user, resolved through the nesting — R4.3)
   provisioning_manifest.workshop_id          (NEW surfacing, from var.workshop_id)

manifest ──> provision_passwords_and_output.py  (Account ID header + per-user column — UNCHANGED)
manifest ──> seed_claim_pool.py                 (CRED#.account_id via username->account_id — UNCHANGED)
```

**Removed generators.** `user_count`, `group_count`, `user_prefix`,
`group_prefix`, `sequence_start`, `sequence_padding`, `membership_strategy`, and
the `user_emails`/`display_name_template` generator inputs are deleted, so any
reference to them fails to resolve (R3.3). The flattening in `locals.tf` replaces
them entirely.

**Username / display-name derivation.** With prefixes gone, usernames are
derived deterministically from the workshop and the nesting so they are stable
and unique across accounts/groups:

```
username     = "<workshop_id>-<account_id_short>-<group>-<NN>"
display_name = "<group> participant NN"
given_name   = "Kiro"
family_name  = "<group> NN"
email        = null        (anonymous OTP flow, as today)
```

where `<NN>` is the 1-based per-group index zero-padded to the group's width and
`<account_id_short>` is the last 4 digits of the account id (keeps the username
short while staying unique when the same group name recurs under two accounts).
`email` stays `null` — the existing optional `emails` block in
`identity_center.tf` renders nothing for a null email, unchanged.

**Deterministic, stable keys (R3.7).** Keys are built from
`account_id + group name + per-group index`, never from a global running
counter. Adding a group under account B leaves every key under account A
byte-identical, so OpenTofu does not churn unrelated users/groups/memberships on
a change. This is the central reason the flatten is keyed this way rather than by
a flat sequence.

**Per-user account resolution (R4).** A user belongs to exactly one group, and a
group is defined under exactly one account in the map, so
`user → group → account` is a total function. `local.user_account_id[uk]` reads
the owning account directly from the flatten (every user key already embeds its
account id). If a group's account cannot be resolved — which, given the map
shape, means an account key failed validation — the manifest is not emitted and
the error names the participant/group (R4.2).

### Pillar 3 — Workshop-keyed state in the shared S3 backend

```
backend.hcl (subscription AND claim-service) — key REMOVED:
   bucket         = "kiro-tofu-state-<account_id>"
   region         = "<AWS_REGION>"
   dynamodb_table = "kiro-tofu-locks"
   encrypt        = true
   # NO key line (R5.4) — supplied at init

init (per workshop, per stack):
   tofu init -reconfigure \
     -backend-config=backend.hcl \
     -backend-config="key=workshops/${WORKSHOP_ID}/subscription/terraform.tfstate"

   tofu init -reconfigure \
     -backend-config=backend.hcl \
     -backend-config="key=workshops/${WORKSHOP_ID}/claim-service/terraform.tfstate"

state layout in the one shared bucket:
   workshops/kiro-2025-10-10/subscription/terraform.tfstate
   workshops/kiro-2025-10-10/claim-service/terraform.tfstate
   workshops/kiro-2025-10-24/subscription/terraform.tfstate   (another workshop, same bucket)
   ...
   lock table kiro-tofu-locks: one lock PER state key (R5.10)
```

**Why `-reconfigure`.** OpenTofu records the resolved backend (including the
`key`) in `.terraform/` and treats the key as "set once." Switching from one
workshop's key to another's is a backend *change*; without `-reconfigure`,
OpenTofu refuses or prompts to migrate state. `-reconfigure` tells it to adopt
the newly supplied key and discard the cached one, so the local `.terraform`
pointer always matches the `WORKSHOP_ID` the task was invoked with (R5.6, R6.2).

**Rendered backend.hcl change.** `backend/terraform/outputs.tf` renders the two
`backend.hcl` bodies in `_backend_hcl_for`. The `key` line is removed from the
rendered body (and from `backend.hcl.example`), so a freshly bootstrapped
`backend.hcl` already omits `key`. If a residual `key` is left in `backend.hcl`,
supplying a second `key` at init is a conflicting setting — the design treats a
`key` in `backend.hcl` as an error condition (see Error Handling) and the mise
guard greps for it before init (R5.9).

**mise tasks** require `WORKSHOP_ID`, run `tofu init -reconfigure` with the
workshop key *before* every apply/destroy, export `TF_VAR_workshop_id`, and warn
on a collision — see Components §4.

### Pillar 4 — One claim service per workshop

```
claim-service/terraform:
   var.workshop_id                                    (NEW)
   var.workshop_code  (TF_VAR_workshop_code — the handler access-gate secret, DISTINCT)

   local.name = "credential-claim-${var.workshop_id}"

   aws_dynamodb_table.claim.name                 = local.name
   aws_lambda_function.claim_handler.function_name = local.name
   aws_iam_role.claim_handler.name               = "${local.name}-lambda"
   aws_iam_role_policy.claim_table_access.name   = "${local.name}-table-access"
   aws_lambda_function_url.claim_handler          (on that function)

   state key: workshops/${WORKSHOP_ID}/claim-service/terraform.tfstate

two workshops, differing workshop_ids:
   credential-claim-kiro-2025-10-10   (table/lambda/role/policy/url)   state key .../2025-10-10/...
   credential-claim-kiro-2025-10-24   (table/lambda/role/policy/url)   state key .../2025-10-24/...
   => no shared name, no shared state key  (R7.3, R7.5, R9.3)

handler env (unchanged shape):
   TABLE_NAME    = local.name          (the workshop's table)
   WORKSHOP_CODE = var.workshop_code    (access gate — NOT the namespace)

claim_handler._credential_response => {username, otp, sign_in_url, region}  (account_id excluded — R4.7)
```

**`workshop_id` vs `workshop_code` coexist (R9).** They are two independent
values threaded through two independent env vars:

| Value           | Env var          | TF var                | Role                                   |
| --------------- | ---------------- | --------------------- | -------------------------------------- |
| `workshop_id`   | `WORKSHOP_ID`    | `TF_VAR_workshop_id`  | Namespace: state key + resource names  |
| `workshop_code` | `WORKSHOP_CODE`  | `TF_VAR_workshop_code`| Access gate validated in the handler   |

Neither substitutes for the other. `workshop_id` is never used for access-gate
validation; `workshop_code` is never used in a resource name or state key
(R9.3, R9.4).

**seed/audit derive the table name from `workshop_id`.** The pure functions
(`credential_item`, `classify_rows`, `email_item_to_row`,
`_credential_response`) are untouched; only the table-name resolution changes —
`local.name` / `credential-claim-<workshop_id>`. Both scripts error if that
workshop's table does not exist (R7.7).

### Pillar 5 — Teardown + cross-workshop isolation

```
tofu destroy  (subscription state key workshops/<id>/subscription/...):
   removes:  users, groups, memberships, permission set, account assignments  (R10.1)
   leaves:   Foundation IdC (NOT in state — only consumed via vars)          (R10.3)

tofu destroy  (claim-service state key workshops/<id>/claim-service/...):
   removes:  that workshop's table, lambda, function URL, roles/policies      (R10.2)
   leaves:   shared backend bucket + lock table (separate backend/ stack)     (R10.4)
             every OTHER workshop (separate state key)                        (R10.5)

verification check (scripts/verify_isolation.py or a test):
   BEFORE destroy of workshop X:
      snapshot other workshop Y's users/groups/account-assignments + claim resources
   AFTER destroy of workshop X:
      re-read Y's resources, diff against the baseline
      if any of Y's resources were removed/modified -> FAIL, report affected    (R10.6)
```

Because the foundation instance is referenced only through `var.idc_instance_arn`
/ `var.identity_store_id` (not a managed resource and not in state), no destroy
can target it. Because each workshop's state lives under its own key, a destroy
scoped to one key can only enumerate and delete that key's resources.

## Components and Interfaces

### 1. Subscription Terraform (`subscription/terraform`)

**`variables.tf`** — remove the generators, add the foundation + workshop inputs.

Removed: `instance_name`, `user_prefix`, `group_prefix`, `sequence_padding`,
`sequence_start`, `user_count`, `group_count`, `user_emails`,
`display_name_template`, `membership_strategy` (R3.3). Kept: `aws_region`,
`aws_profile`, `default_tags`, `kiro_tier`, `kiro_region`. (The baseline
`idc_account_map` is superseded by per-user resolution through
`workshop_accounts`; it is removed in favor of the nested map.)

Added:

```hcl
variable "idc_instance_arn" {
  description = <<-EOT
    ARN of the long-lived Foundation IdC instance to consume
    (arn:aws:sso:::instance/ssoins-xxxxxxxxxxxx). Supplied via tfvars or
    TF_VAR_idc_instance_arn. This module NEVER creates or destroys the instance.
  EOT
  type = string

  validation {
    condition     = length(trimspace(var.idc_instance_arn)) > 0
    error_message = "idc_instance_arn is required (the Foundation IdC instance ARN). Set it in tfvars or via TF_VAR_idc_instance_arn."
  }
}

variable "identity_store_id" {
  description = <<-EOT
    Identity store ID backing the Foundation IdC instance (d-xxxxxxxxxx).
    Supplied via tfvars or TF_VAR_identity_store_id. Users, groups, and
    memberships are created against this identity store.
  EOT
  type = string

  validation {
    condition     = length(trimspace(var.identity_store_id)) > 0
    error_message = "identity_store_id is required (the Foundation IdC identity store ID). Set it in tfvars or via TF_VAR_identity_store_id."
  }
}

variable "workshop_id" {
  description = <<-EOT
    Slug that namespaces this workshop's state key and resource names, e.g.
    kiro-2025-10-10. Threaded from WORKSHOP_ID via TF_VAR_workshop_id. Distinct
    from workshop_code (the claim access-gate secret).
  EOT
  type = string

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", var.workshop_id)) && !can(regex("--", var.workshop_id))
    error_message = "workshop_id must be a slug: 1-63 lowercase alphanumeric characters and hyphens, starting and ending alphanumeric, with no consecutive hyphens."
  }
}

variable "workshop_accounts" {
  description = <<-EOT
    Explicit nested map describing this workshop's child accounts, the groups in
    each account, and the user count of each group. Keyed by 12-digit account id.
    Replaces the removed count/prefix/strategy generators.
  EOT
  type = map(object({
    groups = map(object({
      user_count = number
    }))
  }))

  validation {
    condition     = alltrue([for acct in keys(var.workshop_accounts) : can(regex("^[0-9]{12}$", acct))])
    error_message = "Every workshop_accounts key must be a 12-digit AWS account id."
  }

  validation {
    condition = alltrue(flatten([
      for acct, cfg in var.workshop_accounts : [
        for gname, g in cfg.groups : length(trimspace(gname)) > 0
      ]
    ]))
    error_message = "Every group name in workshop_accounts must be non-empty."
  }

  validation {
    condition = alltrue(flatten([
      for acct, cfg in var.workshop_accounts : [
        for gname, g in cfg.groups : g.user_count >= 0 && g.user_count <= 500
      ]
    ]))
    error_message = "Every group's user_count must be between 0 and 500 inclusive."
  }
}
```

**`locals.tf`** — flatten `workshop_accounts` into the keyed maps the existing
`for_each` resources consume, keeping their value shapes identical (R3.4, R3.5):

```hcl
locals {
  resolved_region = data.aws_region.current.region

  # Foundation identity now comes from variables (was awscc_sso_instance.this).
  identity_store_id = var.identity_store_id
  instance_arn      = var.idc_instance_arn

  # Group -> owning account. Key a group as "<account_id>:<group_name>" so the
  # same group name under two accounts stays distinct and stable (R3.7).
  group_account = merge([
    for acct, cfg in var.workshop_accounts : {
      for gname, _ in cfg.groups : "${acct}:${gname}" => acct
    }
  ]...)

  # Groups: group_key => { name }. (name is the human group name shown in IdC.)
  groups = {
    for acct, cfg in var.workshop_accounts :
    acct => cfg.groups ...   # placeholder; actual build below via merge
  }

  # Flatten users to a list first (so per-group index is available), then key.
  _user_rows = flatten([
    for acct, cfg in var.workshop_accounts : [
      for gname, g in cfg.groups : [
        for i in range(g.user_count) : {
          account_id = acct
          group      = gname
          group_key  = "${acct}:${gname}"
          index      = i + 1
          width      = max(2, length(tostring(g.user_count)))
        }
      ]
    ]
  ])

  users = {
    for r in local._user_rows :
    "${r.account_id}:${r.group}:${format("%0${r.width}d", r.index)}" => {
      username     = "${var.workshop_id}-${substr(r.account_id, 8, 4)}-${r.group}-${format("%0${r.width}d", r.index)}"
      email        = null
      display_name = "${r.group} participant ${format("%0${r.width}d", r.index)}"
      given_name   = "Kiro"
      family_name  = "${r.group} ${format("%0${r.width}d", r.index)}"
      group_key    = r.group_key
      account_id   = r.account_id
    }
  }

  memberships = {
    for uk, u in local.users :
    uk => { user_key = uk, group_key = u.group_key }
  }

  # Per-user account_id, resolved through user -> group -> owning account (R4.1).
  user_account_id = { for uk, u in local.users : uk => u.account_id }

  # Document-level account_id: the single account when the workshop has exactly
  # one, else "" (the per-user column is authoritative for multi-account).
  account_id = length(keys(var.workshop_accounts)) == 1 ? keys(var.workshop_accounts)[0] : ""
}
```

> The `groups` build above is sketched; the concrete form uses the same `merge([
> for ... ]...)` idiom as `group_account`, producing
> `{ "<account_id>:<group_name>" => { name = <group_name> } }`. Keying groups by
> `<account_id>:<group_name>` (not bare name) is what makes two accounts able to
> reuse a group name without a key collision and keeps keys stable on change
> (R3.7).

The existing `aws_identitystore_user.this`, `aws_identitystore_group.this`, and
`aws_identitystore_group_membership.this` resources are **not reworked** — they
still `for_each = local.users` / `local.groups` / `local.memberships` and read
`local.identity_store_id`. Only the definition of those locals changes (R3.5).
Because `local.users[k]` now also carries `group_key` and `account_id`, the user
resource ignores the extra keys (it reads only `username`, `display_name`,
`given_name`, `family_name`, `email`).

**`identity_center.tf`** — remove the instance, add permission set + assignments:

```hcl
# REMOVED: resource "awscc_sso_instance" "this" { ... }
# REMOVED: locals { identity_store_id = ...; instance_arn = ... }  (now in locals.tf)

# aws_identitystore_user / aws_identitystore_group /
# aws_identitystore_group_membership — UNCHANGED (read local.identity_store_id).

resource "aws_ssoadmin_permission_set" "this" {
  name         = "kiro-${var.workshop_id}"
  instance_arn = var.idc_instance_arn
  description  = "Account access for Kiro workshop ${var.workshop_id} groups."
  tags         = var.default_tags
}

# One assignment per group, binding the group to its owning account (R2.2, R2.3).
resource "aws_ssoadmin_account_assignment" "this" {
  for_each = local.groups   # keyed "<account_id>:<group_name>"

  instance_arn       = var.idc_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.this.arn

  principal_type = "GROUP"
  principal_id   = aws_identitystore_group.this[each.key].group_id

  target_type = "AWS_ACCOUNT"
  target_id   = local.group_account[each.key]
}
```

One `aws_ssoadmin_account_assignment` per group means a two-group account yields
two assignments and a three-group account yields three (R2.3). Every participant
of a group inherits the account access through the group assignment (R2.4).

**`providers.tf`** — the `awscc` provider block is removed (the only awscc
resource is gone). `versions.tf` drops the `awscc` required-provider and keeps
`hashicorp/aws`. The `aws_ssoadmin_*` resources are standard `hashicorp/aws`.

**`outputs.tf`** — thread account resolution and surface `workshop_id`:

```hcl
output "account_id"        { value = local.account_id }         # single-account document-level
output "identity_store_id" { value = local.identity_store_id }  # now from var
output "instance_arn"      { value = local.instance_arn }       # now from var

output "provisioning_manifest" {
  value = {
    region            = local.resolved_region
    kiro_region       = var.kiro_region
    account_id        = local.account_id
    workshop_id       = var.workshop_id          # NEW surfacing
    instance_arn      = local.instance_arn
    identity_store_id = local.identity_store_id
    kiro_tier         = var.kiro_tier
    sign_in_url       = "https://${local.identity_store_id}.awsapps.com/start"
    users = {
      for k, u in aws_identitystore_user.this :
      k => {
        username   = u.user_name
        email      = local.users[k].email
        user_id    = u.user_id
        account_id = local.user_account_id[k]    # per-user, resolved through nesting (R4.3)
      }
    }
    groups      = { for k, g in aws_identitystore_group.this : k => { display_name = g.display_name, group_id = g.group_id } }
    memberships = { for k, m in local.memberships : k => { username = local.users[m.user_key].username, group = local.groups[m.group_key].name } }
  }
}
```

### 2. Credentials renderer & seed script (unchanged logic)

`provision_passwords_and_output.py` already renders a document-level **Account
ID** header and a per-user **Account ID** column from the manifest; because the
manifest keeps the baseline fields (`account_id` document-level,
`users[k].account_id` per-user), **no code change is required** (R4.4). The only
difference is that `users[k].account_id` now varies per user when a workshop
spans multiple accounts — the renderer already reads `u.get("account_id")` per
row, so multi-account rows render their own account.

`seed_claim_pool.py` already builds a `username -> account_id` lookup from
`manifest["users"]` and stamps `CRED#.account_id` (R4.5 upstream). The only
change is **where the table name comes from** (see §5): the `--table` value is
now `credential-claim-<workshop_id>` rather than the fixed
`credential-claim-service`. The pure functions `classify_rows`, `credential_item`
stay as-is.

### 3. Claim service Terraform (`claim-service/terraform`)

**`variables.tf`** — add `workshop_id`, keep `workshop_code` distinct, drop the
`table_name` default in favor of the derived name:

```hcl
variable "workshop_id" {
  description = "Slug that namespaces this workshop's claim resources and state key. From TF_VAR_workshop_id. Distinct from workshop_code."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", var.workshop_id)) && !can(regex("--", var.workshop_id))
    error_message = "workshop_id must be a slug: 1-63 lowercase alphanumeric + hyphens, no leading/trailing/consecutive hyphens."
  }
}

# workshop_code UNCHANGED (sensitive, required; the handler access gate).
```

The `table_name` variable is removed; names derive from a local:

```hcl
# dynamodb.tf / lambda.tf
locals {
  name = "credential-claim-${var.workshop_id}"   # the one namespaced base name
}

resource "aws_dynamodb_table" "claim"        { name          = local.name }
resource "aws_lambda_function" "claim_handler"{ function_name = local.name }
resource "aws_iam_role" "claim_handler"       { name          = "${local.name}-lambda" }
resource "aws_iam_role_policy" "claim_table_access" { name    = "${local.name}-table-access" }
# aws_lambda_function_url.claim_handler.function_name = aws_lambda_function.claim_handler.function_name
# Lambda env: TABLE_NAME = local.claim_table_name (= local.name); WORKSHOP_CODE = var.workshop_code
```

Two differing `workshop_id`s therefore yield fully distinct table, function,
role, and policy names *and* a distinct state key — concurrent applies cannot
collide (R7.3, R7.5, R9.3). The handler and `_credential_response` are untouched;
the response stays `{username, otp, sign_in_url, region}` (R4.7).

**`backend.tf`** stays value-free; **`backend.hcl` / `backend.hcl.example`** drop
the `key` line (see §4).

### 4. mise tasks (`mise.toml`)

A shared guard enforces `WORKSHOP_ID`, validates the slug, exports
`TF_VAR_workshop_id`, and reconfigures the backend before every mutating step.
Representative snippets (whitespace-only `WORKSHOP_ID` treated as unset — R6.1,
R6.7):

```toml
[tasks.provision]
description = "Provision a workshop's IdC users/groups/assignments (requires WORKSHOP_ID)"
dir = "subscription/terraform"
run = """
set -eu
: "${WORKSHOP_ID:?WORKSHOP_ID is required}"      # unset/whitespace -> non-zero exit, no action (R6.7, R8.4)
WID="$(printf '%s' "$WORKSHOP_ID" | tr -d '[:space:]')"
[ -n "$WID" ] || { echo "ERROR: WORKSHOP_ID is only whitespace" >&2; exit 1; }
case "$WID" in
  *--*|-*|*-) echo "ERROR: WORKSHOP_ID '$WID' is not a valid slug" >&2; exit 1 ;;
esac
echo "$WID" | grep -Eq '^[a-z0-9][a-z0-9-]{0,62}$' \
  || { echo "ERROR: WORKSHOP_ID '$WID' must be a 1-63 char lowercase slug" >&2; exit 1; }

# A residual key in backend.hcl conflicts with the init-time key (R5.9).
if grep -Eq '^[[:space:]]*key[[:space:]]*=' backend.hcl; then
  echo "ERROR: remove the 'key' line from backend.hcl; it is supplied at init time." >&2
  exit 1
fi

SUB_KEY="workshops/${WID}/subscription/terraform.tfstate"
BUCKET="$(grep -E '^[[:space:]]*bucket' backend.hcl | sed -E 's/.*= *"(.*)"/\\1/')"
# Collision warning: subscription state key already present for this workshop (R8.5).
if aws s3api head-object --bucket "$BUCKET" --key "$SUB_KEY" >/dev/null 2>&1; then
  echo "WARNING: state key already exists -> $SUB_KEY (workshop '$WID' may already be provisioned)." >&2
fi

export TF_VAR_workshop_id="$WID"                 # thread to OpenTofu (R6.4, R8.2)
# Reconfigure the backend to THIS workshop's key BEFORE apply (R6.2); fail-closed (R6.3).
tofu init -reconfigure -backend-config=backend.hcl -backend-config="key=${SUB_KEY}" \
  || { echo "ERROR: backend reconfiguration failed; not applying." >&2; exit 1; }
tofu apply
"""

[tasks.teardown-tofu]
description = "Destroy a workshop's subscription state (requires WORKSHOP_ID)"
dir = "subscription/terraform"
run = """
set -eu
: "${WORKSHOP_ID:?WORKSHOP_ID is required}"
WID="$(printf '%s' "$WORKSHOP_ID" | tr -d '[:space:]')"
[ -n "$WID" ] || { echo "ERROR: WORKSHOP_ID is only whitespace" >&2; exit 1; }
export TF_VAR_workshop_id="$WID"
tofu init -reconfigure -backend-config=backend.hcl \
  -backend-config="key=workshops/${WID}/subscription/terraform.tfstate" \
  || { echo "ERROR: backend reconfiguration failed; not destroying." >&2; exit 1; }
tofu destroy
"""

[tasks.claim-deploy]
dir = "claim-service/terraform"
run = """
set -eu
: "${WORKSHOP_ID:?WORKSHOP_ID is required}"
: "${WORKSHOP_CODE:?WORKSHOP_CODE is required}"      # access gate, distinct from the namespace (R9.5)
WID="$(printf '%s' "$WORKSHOP_ID" | tr -d '[:space:]')"
[ -n "$WID" ] || { echo "ERROR: WORKSHOP_ID is only whitespace" >&2; exit 1; }
export TF_VAR_workshop_id="$WID"
export TF_VAR_workshop_code="$WORKSHOP_CODE"
tofu init -reconfigure -backend-config=backend.hcl \
  -backend-config="key=workshops/${WID}/claim-service/terraform.tfstate" \
  || { echo "ERROR: backend reconfiguration failed; not applying." >&2; exit 1; }
tofu apply
"""

[tasks.claim-seed]
dir = "claim-service/scripts"
run = """
set -eu
: "${WORKSHOP_ID:?WORKSHOP_ID is required}"
WID="$(printf '%s' "$WORKSHOP_ID" | tr -d '[:space:]')"
[ -n "$WID" ] || { echo "ERROR: WORKSHOP_ID is only whitespace" >&2; exit 1; }
python seed_claim_pool.py \
  --otp-csv ../../subscription/output/otps.csv \
  --manifest ../../subscription/output/manifest.json \
  --table "credential-claim-${WID}" \
  --apply
"""

[tasks.claim-audit]
dir = "claim-service/scripts"
run = """
set -eu
: "${WORKSHOP_ID:?WORKSHOP_ID is required}"
WID="$(printf '%s' "$WORKSHOP_ID" | tr -d '[:space:]')"
[ -n "$WID" ] || { echo "ERROR: WORKSHOP_ID is only whitespace" >&2; exit 1; }
TABLE_NAME="credential-claim-${WID}" python export_audit.py
"""
```

`claim-destroy` mirrors `teardown-tofu` with the claim-service key. `seed`/
`audit` are scoped to the workshop by deriving the table name from `WORKSHOP_ID`
(R6.5, R6.6, R7.6); they never read another workshop's outputs or table.

**Two-layer `workshop_id` validation (recommended: both).** The mise guard
catches a bad/missing slug *before* touching the backend key (so a typo never
creates a stray state path), and the Terraform `variable "workshop_id"`
validation block is the authoritative gate (so a direct `tofu apply` outside
mise is still rejected). The mise guard is defense-in-depth; the TF variable is
the source of truth (R5.8, R8.3, R8.4).

### 5. Backend stack rendered config (`backend/terraform/outputs.tf`)

`_backend_hcl_for` is updated so the rendered `backend.hcl` body omits `key`
(the key is now an init-time argument):

```hcl
locals {
  _backend_hcl_body = <<-EOT
    bucket         = "${local.state_bucket_name}"
    region         = "${data.aws_region.current.region}"
    dynamodb_table = "${aws_dynamodb_table.locks.name}"
    encrypt        = true
  EOT
}

output "backend_hcl"               { value = local._backend_hcl_body }  # subscription
output "backend_hcl_claim_service" { value = local._backend_hcl_body }  # claim-service (identical now)
```

Both stacks render the same keyless body; isolation no longer comes from a
baked-in `key` but from the init-time `key=workshops/<id>/<stack>/...`. The
`.example` files for both stacks drop their `key =` line and document the
init-time key instead.

### 6. Isolation verification check (`scripts/verify_isolation.py`)

A standalone script (invokable as a test) that proves R10.5/R10.6:

```
usage: verify_isolation.py --other-workshop <id> --phase {baseline|verify} --baseline <path>

baseline:  read workshop <other>'s resources, write a JSON snapshot:
             - IdC groups (display_name, group_id) for that workshop
             - IdC users (user_name, user_id) for that workshop
             - account assignments (principal_id, target_id) for its permission set
             - claim resources: table credential-claim-<other> exists? lambda/url present?
verify:    re-read the same resources, diff against the baseline snapshot
             exit 0 + "unchanged" when identical
             exit non-zero + list the removed/modified resources when not (R10.6)
```

The operator runs `--phase baseline` for the live workshop *before* destroying
the finished one, then `--phase verify` after. The diff is pure
(`diff_snapshots(before, after) -> list[str]`) so it is unit/property-testable
without AWS; only the readers touch AWS.

## Data Models

### `workshop_accounts` variable

```hcl
map(object({
  groups = map(object({
    user_count = number   # 0..500 inclusive
  }))
}))
# key: 12-digit account id            e.g. "111111111111"
# groups key: group name (non-empty)  e.g. "team-alpha"
```

### Flattened locals (value shapes consumed by the existing `for_each` resources)

| Local                | Key                               | Value                                                             |
| -------------------- | --------------------------------- | ----------------------------------------------------------------- |
| `local.users`        | `<account_id>:<group>:<NN>`       | `{ username, email(null), display_name, given_name, family_name, group_key, account_id }` |
| `local.groups`       | `<account_id>:<group>`            | `{ name }`                                                        |
| `local.memberships`  | `<account_id>:<group>:<NN>`       | `{ user_key, group_key }`                                         |
| `local.group_account`| `<account_id>:<group>`            | `<account_id>` (owning account)                                   |
| `local.user_account_id`| `<account_id>:<group>:<NN>`     | `<account_id>` (user → group → account)                           |

The user/group/membership resources read only the baseline subset of
`local.users[k]` (`username`, `display_name`, `given_name`, `family_name`,
`email`); the extra `group_key`/`account_id` keys are ignored by those resources
and used only to build assignments and the manifest.

### Manifest (`provisioning_manifest`) — changes vs baseline

| Field                 | Type   | Meaning                                           | Status                       |
| --------------------- | ------ | ------------------------------------------------- | ---------------------------- |
| `account_id`          | string | Document-level account (single-account workshop)  | existing (baseline)          |
| `users[k].account_id` | string | Per-user account resolved through the nesting     | existing field, now per-user |
| `workshop_id`         | string | The workshop namespace slug                       | NEW surfacing                |
| `region`,`kiro_region`,`sign_in_url`,`kiro_tier`,`groups`,`memberships` | — | unchanged | existing |

### Claim-service naming

```
local.name = "credential-claim-${var.workshop_id}"
  table name          = local.name
  lambda name         = local.name
  role name           = "${local.name}-lambda"
  policy name         = "${local.name}-table-access"
```

### State-key scheme

```
workshops/<workshop_id>/subscription/terraform.tfstate
workshops/<workshop_id>/claim-service/terraform.tfstate
bucket:    kiro-tofu-state-<account_id>   (shared)
lock table: kiro-tofu-locks               (shared; one lock per key)
```

### Claim response (unchanged)

`{username, otp, sign_in_url, region}` — `account_id` still excluded (R4.7).

## Error Handling

- **Missing `idc_instance_arn` / `identity_store_id`.** Both variables have no
  default and a `length(trimspace(...)) > 0` validation. An empty or unsupplied
  value fails validation during plan, naming the missing variable, before any
  user/group/membership/assignment is created (R1.7).

- **Invalid account id key.** A `workshop_accounts` key that is not a 12-digit
  numeric string fails the first `workshop_accounts` validation; the apply halts
  with "Every workshop_accounts key must be a 12-digit AWS account id." No
  assignment is created for any group under that account (R2.5, R3.8).

- **Empty group name.** The second `workshop_accounts` validation rejects an
  empty/whitespace group name (R3.9).

- **`user_count` out of range.** The third validation rejects any group whose
  `user_count` is outside `0..500` (R3.2). `user_count = 0` is valid and
  produces a group with no users and no memberships (and still an assignment, so
  the empty group is bound to its account).

- **A group whose account can't be resolved.** Given the map shape, a group is
  always nested under exactly one account key, so `local.group_account[gk]` is
  total — the only way resolution fails is an account key that failed validation,
  which already halts the apply. If an operator somehow references a group under
  a malformed account, the manifest is not emitted and the error identifies the
  participant/group (R4.2).

- **Missing / whitespace / invalid `WORKSHOP_ID`.** The mise guard treats
  unset or whitespace-only as unset, exits non-zero, and does **not** run
  `tofu init -reconfigure`, apply, destroy, seed, or audit (R6.7, R8.4). A
  slug-pattern miss (uppercase, leading/trailing/consecutive hyphen, >63 chars)
  is rejected by both the mise guard and the TF `workshop_id` validation,
  naming the offending value and expected format, leaving all state keys
  untouched (R5.8, R8.3).

- **Residual `key` in `backend.hcl`.** The mise guard greps for a `key =` line
  and errors before init; the rendered `backend.hcl` and both `.example` files
  no longer include one. Supplying `key` both in `backend.hcl` and at init is a
  conflicting backend setting — treated as an init error, leaving state keys
  unchanged (R5.9).

- **State-key collision on provision.** Before init, the provision task
  `head-object`s the subscription state key; if it already exists, it prints a
  warning naming the conflicting `workshop_id` and state key, then proceeds
  (R8.5). (A warning, not a hard stop — re-provisioning an existing workshop is a
  legitimate operation.)

- **seed/audit against a non-existent workshop table.** `seed_claim_pool.py` and
  `export_audit.py` resolve the table name from `WORKSHOP_ID`
  (`credential-claim-<id>`). A `boto3` call against a missing table raises
  `ResourceNotFoundException`; both scripts catch it and exit non-zero with a
  message naming the `workshop_id`, without reading or modifying any other
  workshop's table (R7.7).

- **Concurrent apply/destroy locking.** Each workshop's operation acquires the
  DynamoDB lock in `kiro-tofu-locks` keyed by its own state key. Two workshops
  with different keys never contend; two operations on the *same* key serialize
  on the lock, so one waits rather than corrupting state (R5.10).

- **Backward compatibility note (supersession).** This spec replaces the
  single-run count/prefix/strategy generator model. The removed variables
  (`user_count`, `group_count`, `user_prefix`, `group_prefix`, `sequence_start`,
  `sequence_padding`, `membership_strategy`, `user_emails`,
  `display_name_template`, `instance_name`) no longer resolve; a tfvars file that
  still sets them must migrate to `workshop_accounts`. Likewise the baseline
  `idc_account_map` is superseded by per-user resolution through the nested map.

- **Foundation IdC never destroyed.** The instance is referenced only through
  `var.idc_instance_arn` / `var.identity_store_id`; it is not a managed resource
  and not in state, so no `tofu destroy` can target it (R10.3). The shared
  backend bucket/lock table live in the separate `backend/` stack and are never
  in a workshop's state (R10.4).

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all
valid executions of a system — essentially, a formal statement about what the
system should do. Properties serve as the bridge between human-readable
specifications and machine-verifiable correctness guarantees.*

Each property below is testable with a minimum of **100 randomized iterations**
and references the requirement(s) it validates. The flatten/resolution logic
(`workshop_accounts` → `local.users`/`groups`/`memberships`/`group_account`/
`user_account_id`), the claim-service name derivation
(`credential-claim-<workshop_id>`), the state-key scheme, the slug validator, and
the isolation-diff function are the testable surfaces — modelled as pure
functions (in a small Python/HCL-mirroring harness, or exercised through
`tofu plan` on generated tfvars) so they can be driven with random inputs. Each
property test is tagged `**Feature: multi-workshop-provisioning, Property N:
<text>**`.

Pure configuration facts (variable existence, the removal of a variable, a
`backend.hcl` omitting `key`, env-var threading) and infrastructure wiring (that
an assignment actually grants console access, that the foundation instance is
untouched by AWS) are verified by example/integration/smoke tests, not property
tests, and are not listed here.

### Property 1: Every group maps to exactly one account assignment

*For any* valid `workshop_accounts` map, the flatten SHALL produce exactly one
account assignment per group, binding that group to the account under which it is
nested — so an account holding G groups yields exactly G assignments, each with
`target_id` equal to that account's 12-digit id.

**Validates: Requirements 2.2, 2.3**

### Property 2: User and membership counts equal the declared user_count

*For any* valid `workshop_accounts` map, for every group with user_count N the
flatten SHALL produce exactly N users keyed under that group and exactly N
memberships placing those N users in that group.

**Validates: Requirements 3.6**

### Property 3: Flatten keys are deterministic and locally stable

*For any* valid `workshop_accounts` map, flattening it twice SHALL produce
byte-identical keys for `local.users`, `local.groups`, and `local.memberships`;
and *for any* mutation confined to one account's entry (adding/removing a group
or changing a group's user_count), the keys of every user/group/membership under
every *other* account SHALL be unchanged.

**Validates: Requirements 3.7**

### Property 4: Flattened maps match the shapes the for_each resources consume

*For any* valid `workshop_accounts` map, every `local.users[k]` SHALL carry the
baseline user fields (`username`, `email`, `display_name`, `given_name`,
`family_name`), every `local.groups[gk]` SHALL carry `{ name }`, and every
`local.memberships[k]` SHALL carry `{ user_key, group_key }` whose `user_key` and
`group_key` reference existing entries of `local.users` and `local.groups`.

**Validates: Requirements 3.4, 3.5**

### Property 5: Each participant's account_id is its owning account

*For any* valid `workshop_accounts` map, each user's resolved `account_id`
(`local.user_account_id[uk]`, and the per-user `account_id` in the manifest)
SHALL equal the 12-digit id of the account under which that user's group is
nested.

**Validates: Requirements 4.1, 4.3**

### Property 6: Distinct workshop_ids yield fully distinct claim names and state keys

*For any* two distinct valid `workshop_id` slugs, the derived claim-service
names (table, lambda function, IAM role, IAM policy) and the subscription and
claim-service state keys SHALL share no value between the two workshops.

**Validates: Requirements 7.3, 7.5, 9.3**

### Property 7: workshop_id is the sole namespace substring; workshop_code never namespaces

*For any* valid `workshop_id` and any `workshop_code`, every derived claim
resource name and both state keys SHALL contain the exact `workshop_id` as a
substring and SHALL NOT contain the `workshop_code`.

**Validates: Requirements 7.2, 9.3, 9.4**

### Property 8: The slug validator accepts exactly the specified slug grammar

*For any* candidate string, the `workshop_id` validator SHALL accept it if and
only if it is 1-63 characters of lowercase alphanumerics and hyphens, begins and
ends with an alphanumeric, and contains no consecutive hyphens — rejecting empty,
whitespace, uppercase, over-length, and leading/trailing/double-hyphen inputs.

**Validates: Requirements 5.2, 5.8, 8.3, 8.4**

### Property 9: State keys follow the workshop-scoped scheme

*For any* valid `workshop_id`, the subscription and claim-service state keys SHALL
be exactly `workshops/<workshop_id>/subscription/terraform.tfstate` and
`workshops/<workshop_id>/claim-service/terraform.tfstate`, differing only in the
stack segment and sharing the same `<workshop_id>`.

**Validates: Requirements 5.2, 5.3, 7.4**

### Property 10: Isolation diff flags any removal or modification of another workshop's resources

*For any* pair of resource snapshots (before, after) of another workshop, the
isolation-diff function SHALL report an empty result when the two snapshots are
equal and SHALL report every removed or modified resource when they differ, so a
destroy that touches another workshop is always detected.

**Validates: Requirements 10.5, 10.6**

### Property 11: Claim response excludes account_id

*For any* `CRED#` item — including one carrying an `account_id` attribute — the
credential response returned to a claiming participant SHALL contain exactly the
keys `username`, `otp`, `sign_in_url`, and `region`, and SHALL NOT contain
`account_id`.

**Validates: Requirements 4.7**

## Testing Strategy

The testable surfaces are the pure (and pure-mirrored) logic the design already
calls out; the rest of the module is Terraform configuration and AWS wiring,
verified by plan/smoke/integration tests rather than property tests.

### Property-based tests (pytest + Hypothesis, min 100 iterations each)

Drive the pure surfaces with randomized inputs — a small Python harness mirroring
the HCL flatten/derivation, or `tofu plan` output over generated tfvars. Each
test is tagged `**Feature: multi-workshop-provisioning, Property N: <text>**`
and maps 1:1 to the Correctness Properties above:

- **`workshop_accounts` flatten** → `local.users` / `local.groups` /
  `local.memberships` / `local.group_account` / `local.user_account_id`:
  Properties 1-5 (one assignment per group bound to its owning account;
  user/membership counts equal `user_count`; deterministic and locally stable
  keys; flattened value shapes match what the `for_each` resources consume; each
  participant's `account_id` is its owning account).
- **Claim-service name derivation** (`credential-claim-<workshop_id>`):
  Properties 6, 7 (distinct `workshop_id`s yield fully distinct names; the name
  contains `workshop_id` and never `workshop_code`).
- **State-key scheme** (`workshops/<id>/<stack>/terraform.tfstate`):
  Properties 6, 9 (no shared key between distinct workshops; keys follow the
  workshop-scoped scheme).
- **Slug validator** (`workshop_id`): Property 8 (accepts exactly the specified
  slug grammar, rejecting empty/whitespace/uppercase/over-length/leading/
  trailing/double-hyphen inputs).
- **Isolation-diff function** (`diff_snapshots(before, after)`): Property 10
  (empty result when equal; reports every removed/modified resource when they
  differ).
- **Claim response shaping** (`_credential_response`): Property 11 (response
  carries exactly `username`, `otp`, `sign_in_url`, `region`, never
  `account_id`).

### Example / unit tests

- **Removed-variable supersession.** A tfvars file still setting a removed
  generator (`user_count`, `group_count`, `user_prefix`, `group_prefix`,
  `sequence_start`, `sequence_padding`, `membership_strategy`, `user_emails`,
  `display_name_template`, `instance_name`, `idc_account_map`) no longer resolves
  — assert the reference fails rather than silently taking effect.
- **Table-name-from-`workshop_id` resolution.** `seed_claim_pool.py` and
  `export_audit.py` resolve `credential-claim-<workshop_id>`; assert the resolved
  table name for a sample `workshop_id`, and assert the **not-found error path** —
  a `ResourceNotFoundException` against a missing table exits non-zero with a
  message naming the `workshop_id` and touches no other workshop's table (R7.7).

### Integration / smoke tests (`tofu validate` / `tofu plan` on generated tfvars fixtures)

- **Variable validations.** Confirm the gates reject bad input and accept good:
  12-digit `workshop_accounts` account keys, non-empty group names, `user_count`
  within `0..500`, required (non-empty) `idc_instance_arn` / `identity_store_id`,
  and the `workshop_id` slug grammar.
- **Keyless `backend.hcl`.** Assert the rendered `backend.hcl` (and `.example`)
  omits a `key` line and that `tofu init` succeeds only with an init-time
  `-backend-config="key=..."`.
- **Non-colliding plans.** Two differing `workshop_id`s plan to non-colliding
  claim resource names and distinct state keys (end-to-end confirmation of
  Properties 6/7/9 at the `tofu plan` level).

### Cross-workshop isolation verification (manual / operational, R10)

`scripts/verify_isolation.py --phase baseline` snapshots a live workshop's
resources before another workshop is destroyed, and `--phase verify` re-reads and
diffs them afterward — exiting non-zero and listing any removed/modified resource.
This is the operational check for R10; the pure `diff_snapshots` core it relies on
is covered by Property 10.

### Note on configuration facts

Terraform variable `validation` blocks and the `-reconfigure` backend behavior
are configuration facts, not universal properties — they are verified by the
plan/smoke tests above (and the mise guard), not by property-based tests.
