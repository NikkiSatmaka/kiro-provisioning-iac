# Implementation Plan: mise-task-naming

## Overview

This is a mechanical, deterministic rename executed as an ordered sequence of
text edits. The seven subscription tasks in the root `mise.toml` are renamed to
the `subscription-*` prefix per the Rename Mapping (the single source of truth),
and every in-repo reference is updated through that same table. Tasks are ordered
so `mise.toml` changes land first (the interface), then its consumers (docs,
help string, planning doc), then the one in-code test that references the task
names, and finally a repo-wide verification that proves zero old references
survive and the seven new names parse.

No property-based tests are defined: the design's Correctness Properties section
establishes that this one-shot, deterministic rename has no input space to
quantify over, so correctness is proven by targeted grep, a `mise tasks` parse
check, and the existing example-based test suite. All tasks below are required.

## Tasks

- [x] 1. Rename the seven subscription tasks and self-references in `mise.toml`
  - Rename the seven `[tasks.X]` headers per the Rename Mapping: `provision-plan`→`subscription-plan`, `provision`→`subscription-apply`, `teardown-tofu`→`subscription-destroy`, `provision-render`→`subscription-render`, `credentials`→`subscription-credentials`, `teardown-plan`→`subscription-teardown-plan`, `teardown-run`→`subscription-teardown-run` (lines ~153, 165, 253, 209, 218, 243, 248)
  - Update the four self-referencing comment lines that name `provision-plan`, `provision`, `teardown-plan`, `teardown-tofu` (lines ~149, 151, 239, 240) to their new names
  - Update the one `echo` string in the `subscription-credentials` task so it instructs the user to re-run `mise run subscription-credentials` (line ~231)
  - Apply longest/most-specific old names before bare `provision` (trailing word boundary) and bare `credentials`, matching only `[tasks.<name>]` headers, `mise run <name>` phrases, and backtick self-references — never prose, filenames, or directory paths
  - Hold every `dir` value and every non-echo `run` line byte-for-byte identical; preserve each description's functional intent (only task-name self-references change)
  - Leave the shared toolchain tasks (`setup`, `lock`, `aws-configure`, `verify`) and all `backend-*`/`claim-*`/`foundation-*`/`governance-*` headers untouched
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 5.1, 5.2, 5.3_

- [x] 2. Update operator documentation references
  - Update `README.md` per the occurrence catalogue (lines ~153, 164, 165, 222, 233, 234, 235), mapping each `mise run <old>` / prose task name to its new name
  - Update `subscription/RUNBOOK.md` per the catalogue (lines ~84, 97, 100, 130, 178, 227, 283, 290, 292)
  - Update `subscription/TEARDOWN.md` per the catalogue (lines ~96, 99, 127, 128, 136, 139, 185, 188, 189, 190, 193), matching each `teardown-*` name as a whole token
  - Update `subscription/output/credentials.template.md` (line ~5), changing only the `mise run credentials` task phrase
  - Honor the substring hazards: do not touch `provision.py`, `teardown.py`, `python provision.py`/`python teardown.py` invocations, the `subscription/scripts` and `subscription/terraform` directory paths, `credentials.md`/`credentials.template.md`/`.aws/credentials`, or the English words "provisioning"/"provision"/"credentials" used as prose
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.7_

- [x] 3. Update the `BACKEND_SETUP_HELP` tokens in `subscription/scripts/provision.py`
  - Change the two `mise run <task>` tokens inside the `BACKEND_SETUP_HELP` string (line ~119) from `mise run provision-plan   # or: mise run provision` to `mise run subscription-plan   # or: mise run subscription-apply`
  - Leave the filename `provision.py`, all `python provision.py` references, and the prose word "provisioning" (line ~117) unchanged
  - _Requirements: 4.6, 4.7_

- [x] 4. Update the planning doc `.agents/tasks/remote-state-plan.md`
  - Update the backtick-quoted task names and `mise run <task>` phrases per the catalogue (lines ~30, 121, 125, 153, 156), mapping `provision`→`subscription-apply`, `teardown-tofu`→`subscription-destroy`, `provision-plan`→`subscription-plan`
  - Leave the prose verb "provisioning", `provision.py` references, and historical commit-message scopes like `feat(provision)` unchanged
  - _Requirements: 4.5, 4.7_

- [x] 5. Update the `MUTATING_TASKS` tuple in `tests/test_keyless_backend.py`
  - Change the `MUTATING_TASKS` tuple from `("provision", "teardown-tofu", "claim-deploy", "claim-destroy")` to `("subscription-apply", "subscription-destroy", "claim-deploy", "claim-destroy")` so the keyless-backend contract keeps validating the two renamed subscription tasks under their new names
  - This is the one in-code test touched beyond R4's doc list, called out in the design's Testing Strategy; it doubles as a regression guard that the renamed tasks still parse out of `mise.toml`
  - _Requirements: 1.2, 1.3, 2.1_

- [x] 6. Verify zero surviving references, parse the registry, and run the suite
  - Run the whole-repo targeted grep with task-reference-shaped patterns (`mise run provision-plan|provision-render|teardown-tofu|teardown-plan|teardown-run`, bare `mise run provision\b`, `mise run credentials\b`, and `\[tasks\.(provision|provision-plan|provision-render|teardown-tofu|teardown-plan|teardown-run|credentials)\]`), excluding `.kiro/specs/` and `.env.example`; assert zero matches
  - Run `mise tasks` and confirm the seven new `subscription-*` names list with no TOML parse error, none of the seven old names appear, and the shared tasks plus other stacks' tasks still list
  - Run the pytest + Hypothesis + moto suite: `uv run --group dev pytest -q` at the repo root and the same command from `claim-service/`
  - Diff `mise.toml` to confirm only the seven headers, four comment self-references, and one echo string changed
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3_

## Notes

- All tasks are required; none are optional. This is a clean-break rename, so a
  partial application leaves the repo pointing at removed task names.
- Tasks are ordered so each later task can verify earlier ones: `mise.toml`
  (the interface) changes first, then every consumer, then the regression test,
  then the whole-repo verification sweep.
- No property-based tests are included. The design's Correctness Properties
  section establishes that this deterministic text rename has no input space to
  quantify over; the single repo-wide invariant (Property 1 — no old task name
  survives as a task reference) is proven by the exhaustive targeted grep in
  task 6, not by randomized generation.
- Every replacement maps through the Rename Mapping table and nothing else; the
  substring hazards (`provision`, `credentials`, the shared `teardown-*` prefix)
  are defused by applying longest names first and matching only task-shaped
  occurrences.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2", "3", "4", "5"] },
    { "id": 2, "tasks": ["6"] }
  ]
}
```
