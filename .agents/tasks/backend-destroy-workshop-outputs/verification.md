# Verification — backend-destroy-workshop (Option A)

## Change summary

The `backend-destroy-workshop` purge no longer depends on a phantom
`backend/terraform/backend.hcl`. The `backend/` stack is the bootstrap stack
(LOCAL backend, no backend.hcl of its own). The purge now resolves the shared
state bucket + lock table from the backend stack's OWN Terraform outputs and
passes them to the script via the `STATE_BUCKET` / `LOCK_TABLE` env contract.

Files changed:

- `mise.toml` (`[tasks.backend-destroy-workshop]`): removed the
  `require_backend_hcl` guard and `reject_residual_key` call. Added
  `tofu init -input=false` + `tofu output -raw state_bucket_name` /
  `lock_table_name`, fail-closed if either is empty, then
  `export STATE_BUCKET LOCK_TABLE`. Kept `require_workshop_id`, the dry-run/APPLY
  branch structure, and the typed-phrase gate
  (`require_typed_phrase "destroy-workshop-state" "deleting nothing."`) in the
  APPLY branch only. No `tofu apply`/`destroy` added — still a non-mutating task.
- `backend/scripts/destroy_workshop_state.sh`: replaced the backend.hcl parse
  block with reading `STATE_BUCKET` / `LOCK_TABLE` from the environment
  (fail-closed if either empty). Updated the header comment block to describe the
  env contract instead of "Reads backend.hcl from the CURRENT directory". All
  other behavior (prefix scoping, dry-run vs --apply, S3 batch-delete pagination,
  DynamoDB lock-row scoping, summary lines, isolation contract, `set -eu` /
  POSIX-sh) left identical.
- `tests/test_destroy_workshop_state_lint.py`: replaced the guard assertions
  (`require_backend_hcl` / `reject_residual_key`) with assertions that the task
  resolves bucket+table from `tofu output -raw` and exports `STATE_BUCKET` /
  `LOCK_TABLE`, and that it no longer references the backend.hcl guards. Replaced
  the "fails closed without backend.hcl" harness test with a script-level
  "fails closed without STATE_BUCKET/LOCK_TABLE" test (no tofu/AWS needed).
  MUTATING_TASKS regression guard left untouched and passing.
- `tests/test_destroy_workshop_state_purge.py`: `_run_script` now pins
  `STATE_BUCKET` / `LOCK_TABLE` to the moto fixtures instead of writing a
  backend.hcl. Replaced the missing/unparseable-backend.hcl fail-closed tests
  with a single missing-env-contract fail-closed test. Isolation assertions
  unchanged.
- `subscription/TEARDOWN.md`: no change. Its "Per-workshop state cleanup"
  section documents `backend-destroy-workshop` via WORKSHOP_ID + dry-run only and
  never claimed a backend.hcl requirement for this task; the backend.hcl mentions
  there all concern the consumer `subscription/` stack (Option B), not this task.

## Commands run and results

### POSIX sh parse check
```
$ sh -n backend/scripts/destroy_workshop_state.sh
sh -n OK   (exit 0)
```

### shellcheck
Not installed on this machine (`which shellcheck` -> not found). The
`test_script_shellcheck_clean` lint case SKIPS cleanly in this condition (one of
the 3 skips below).

### Affected + regression tests
Run with `AWS_REGION=us-east-1` because the ambient dev-shell region
(`ap-southeast-1`, from mise/.env) leaks into the moto subprocess and makes
moto's `create_bucket` (no LocationConstraint) fail with
`IllegalLocationConstraintException`. The purge test file pins the region via
`os.environ.setdefault`, so an ambient value wins; us-east-1 is the region moto
expects for the default-constraint create. This is an environment nuance, not a
code issue.

```
$ AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 uv run pytest \
    tests/test_destroy_workshop_state_lint.py \
    tests/test_destroy_workshop_state_purge.py \
    tests/test_keyless_backend.py -q
31 passed, 3 skipped in 21.70s   (exit 0)
```
The 3 skips are the shellcheck-not-installed lint case plus 2 other
conditionally-skipped keyless-backend cases. The MUTATING_TASKS regression test
(`test_mutating_tasks_tuple_excludes_this_task`) PASSES: the tuple stays the four
tofu-mutating tasks and `backend-destroy-workshop` is not in it.

### Full root suite
```
$ AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 uv run pytest -q
6 failed, 212 passed, 3 skipped in 271.77s
```
The 6 failures are PRE-EXISTING and unrelated to this task — they are
foundation docs-content assertions and governance tofu-plan property tests that
invoke real `tofu plan` needing vars. Confirmed by stashing all 4 of this task's
changed files and re-running `tests/test_foundation_scope_boundary.py` on the
clean base: the same 3 foundation failures reproduce with zero of my changes
applied. The failing files
(`test_foundation_scope_boundary.py`,
`test_governance_budget_action_targets_property.py`,
`test_governance_guardrail_allowlist_property.py`,
`test_governance_notification_subscribers_property.py`) are untouched by this
task (git status shows only the 4 files above modified).

### No live tofu/AWS
No real `tofu apply`/`destroy` or live AWS calls were made. Behavioral
verification is the moto-backed purge suite.
```
