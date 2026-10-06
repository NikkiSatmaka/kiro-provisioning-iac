# Teardown — remove this workshop's Kiro IdC users, groups, and subscription

Goal: wipe **this workshop's** provisioning from the management account
completely, and have that stay possible **a month later, from a different
computer** — without ever touching the shared organization IdC instance or any
other workshop's identities.

There are two paths. **Option B (remote state + `tofu destroy`) is the primary
one.** **Option A (a state-free discovery script) is the fallback** for when
`tofu destroy` has no usable state. Both finish with the same short list of
**manual Kiro-console steps** that AWS does not expose through any API.

---

## What teardown must remove

| Thing | Created by | Removed by |
| ----- | ---------- | ---------- |
| IdC users (`<workshop_id>-…`) | OpenTofu | Option B or A |
| IdC groups (`<workshop_id>-<group>`) | OpenTofu | Option B or A |
| Group memberships | OpenTofu | Option B or A |
| Permission set / account assignments (only if `enable_account_access` was true) | OpenTofu | Option B |
| IdC **organization instance** | NOT this stack (adopted read-only) | **NEVER deleted** — shared by every workshop |
| **Kiro subscriptions / tier assignments** | Kiro console | **Manual** (console) |
| **Kiro IdC application assignment** | Kiro (service) | **Manual** (console) — not auto-removed |
| Local `output/credentials.md`, `output/otps.csv` | scripts | `rm` by hand |

> The IdC user/group/membership rows (plus the flag-gated permission set and
> assignments) are the fully-automatable part. The Kiro subscription and
> application-assignment rows are console-only on AWS's side — no stable API
> exists — so every path below ends by pointing you at them. The shared
> organization instance is never in scope for a per-workshop teardown.

---

## The "different computer, a month later" problem

`tofu destroy` only deletes what is in its **state**. Local state is git-ignored
and does **not** travel with the repo. On a fresh clone, local state is empty,
so `tofu destroy` would delete **nothing** and silently leave this workshop's
users and groups orphaned. That is why remote S3 state is **required** and set
up at provision time (RUNBOOK step 1b) — `backend.tf` is tracked and active, so
state always lives in S3.

- **Option B solves this** by putting state in S3, so any machine with
  credentials can `tofu init` + `tofu destroy`.
- **Option A sidesteps it** by needing no state at all — it rediscovers the
  resources live from the account.

If you want the "a month later" guarantee, set up Option B's remote state
**now, at provision time** (before you walk away). Option A is always available
as a safety net even if you forget.

---

## Option B (primary) — remote S3 state, then `tofu destroy`

### One-time setup at provision time

Create the state bucket + lock table and write `backend.hcl` in one step
(the bootstrap keeps its **own local state** — chicken-and-egg):

```bash
mise run backend-bootstrap      # creates bucket + lock table AND writes
                                # subscription/terraform/backend.hcl (bucket name
                                # derived from your account id — nothing to fill in)
```

`backend.tf` is tracked and value-free, so the S3 backend is already active;
the bootstrap only has to supply `backend.hcl`. From here, state lives in S3.
`backend.hcl` is git-ignored (account-specific); `backend.tf` and
`backend.hcl.example` stay tracked.

### Teardown later, from any machine

`backend.tf` is already in the clone (tracked). You only need `backend.hcl` to
exist, then init + destroy. Any of these gets you `backend.hcl`:

```bash
git clone <repo> && cd <repo>/subscription

# (a) regenerate it — backend-bootstrap is idempotent (bucket already exists):
mise run backend-bootstrap

# (b) OR copy the template and fill in region (bucket is the derived default):
cp terraform/backend.hcl.example terraform/backend.hcl   # edit region

cd terraform
tofu init -backend-config=backend.hcl   # one-time on a fresh clone (no task)
cd ../..
mise run teardown-tofu                  # tofu destroy: this workshop's users, groups, memberships
```

`mise run teardown-tofu` runs `tofu destroy`, which reads the real state from S3
and deletes this workshop's IdC users, groups, and memberships (plus the
permission set / assignments if `enable_account_access` was true). It never
touches the shared organization instance, which is not in this stack's state.
The `tofu init` above is only needed once per clone to wire up the S3 backend.

### After `tofu destroy`

Do the [manual Kiro-console cleanup](#manual-cleanup-both-options) below, then
tear the backend down last (optional):

```bash
# force_destroy defaults to false. To delete a bucket that still holds state
# versions, create the tfvars (the one case the bootstrap needs it) and set it:
cp backend/terraform/terraform.tfvars.example \
   backend/terraform/terraform.tfvars   # then set force_destroy = true
mise run backend-bootstrap   # apply the force_destroy flag first
mise run backend-destroy     # deletes the state bucket + lock table
```

---

## Option A (fallback) — state-free discovery script

Use this when `tofu destroy` can't help: no remote backend was set up, and the
local state is gone (fresh clone). It needs **no state** — it finds everything
live from the account by naming convention.

The common cases have mise tasks — `mise run teardown-plan` (dry run) and
`mise run teardown-run` (delete this workshop's users/groups/memberships). Drop
to the raw script only for the variants no task covers (custom prefixes):

```bash
cd subscription/scripts
# (project venv has boto3; from repo root `mise run setup` if needed)

# 1. DRY RUN (default, safe) — see exactly what it would delete:
python teardown.py                           # or: mise run teardown-plan

# 2. Delete users, groups, memberships (the shared org instance is always kept):
python teardown.py --delete                  # or: mise run teardown-run
```

Behavior:

- **Dry run by default.** Mutating needs `--delete` **and** typing the
  confirmation phrase `delete kiro provisioning` (or `--yes` for CI).
- Discovers the organization IdC instance automatically (only to scope the
  lookup); matches users by `--user-prefix` (default `kiro-user-`) and groups by
  `--group-prefix` (default `kiro-team-`). Override if you changed the prefixes.
- Deletes in the correct order: memberships → users → groups. **It never deletes
  the IdC instance** — there is no `--delete-instance` flag.
- If you still have `output/manifest.json`, pass `--manifest ../output/manifest.json`
  to use exact ids instead of prefix matching.

```bash
# Example: custom prefixes / explicit region, non-interactive
python teardown.py --user-prefix acme-dev- --group-prefix acme-team- \
    --region us-east-1 --delete --yes
```

The script prints the same manual cleanup steps when it finishes.

---

## Manual cleanup (both options)

AWS exposes no stable API for these, so do them in the console after either
path:

1. **Deactivate Kiro subscriptions.** Kiro console → deactivate every plan /
   tier assigned to the groups. Per Kiro's docs, removing access "at end of
   month" does **not** auto-remove the IdC application assignment.
2. **Remove the Kiro IdC application assignment.** IAM Identity Center →
   Applications → remove the Kiro application / its assignments. This is the
   piece that lingers if you skip it.
3. **Delete local secrets.** `rm -f subscription/output/credentials.md subscription/output/otps.csv`.
4. **Do NOT disable IAM Identity Center** to clean up one workshop. The
   organization instance is shared by every workshop; disabling it is a
   deliberate, standalone console action, never part of a per-workshop teardown.

---

## Runner entrypoints (mise)

Convenience tasks wrap the commands above. None mutate the account without a
prompt; `teardown-plan` is a safe dry run.

```bash
mise run teardown-plan    # Option A DRY RUN — report only, no changes
mise run teardown-run     # Option A — delete this workshop's users/groups/memberships (confirms)
mise run teardown-tofu    # Option B — tofu destroy (confirms)
```

Start with `mise run teardown-plan` to see exactly what would be removed.

---

## Which path should I use?

- **Set up Option B at provision time** and use `tofu destroy` for teardown.
  It's the clean, auditable path and the one the repo is designed around.
- **Keep Option A as the safety net.** If you're reading this a month later on a
  new laptop and don't have the state or the bucket name, `python teardown.py`
  will still find and remove this workshop's identities. Then do the manual
  console steps.
