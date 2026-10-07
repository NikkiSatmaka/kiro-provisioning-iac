# Design Document

## Overview

This is a mechanical, deterministic rename. Seven `subscription/`-stack tasks in
the root `mise.toml` are renamed to the `subscription-*` prefix, and every
in-repo reference to an old name is updated to its new name. It is a clean break:
old names are removed with no aliases. No task behavior changes — `dir`, `run`
body logic, and description intent are preserved; only task names and the text
that self-references those names change.

### Rename Mapping (the single source of truth)

| # | Old name            | New name                      |
|---|---------------------|-------------------------------|
| 1 | `provision-plan`    | `subscription-plan`           |
| 2 | `provision`         | `subscription-apply`          |
| 3 | `teardown-tofu`     | `subscription-destroy`        |
| 4 | `provision-render`  | `subscription-render`         |
| 5 | `credentials`       | `subscription-credentials`    |
| 6 | `teardown-plan`     | `subscription-teardown-plan`  |
| 7 | `teardown-run`      | `subscription-teardown-run`   |

Every replacement anywhere in the repo MUST map through this table and nothing
else (Validates R4.7).

### Architecture

There is no runtime architecture to design — the deliverable is a set of text
edits across tracked files. The design's substance is:

1. The exact edits inside `mise.toml` (headers, self-referencing comments, echo
   string, cross-references between subscription tasks).
2. The ordered reference-update strategy for every other affected file, with the
   substring hazards called out per file.
3. A verification approach that proves zero old task references survive and the
   seven new tasks parse.

## Architecture

There is no runtime architecture to design. This change ships text edits only,
so the "architecture" is the ordered set of edits applied across `mise.toml` and
every file that references the renamed tasks. The **Rename Mapping table** above
is the single source of truth: every edit anywhere in the repo maps through that
table and nothing else. Concretely, the architecture is:

1. The exact edits inside `mise.toml` — the seven `[tasks.<name>]` headers, the
   four self-referencing comment lines, and the one echo string — with every
   `dir` and non-echo `run` line held byte-identical.
2. The ordered reference-update strategy for every other affected file (operator
   docs, the `provision.py` help string, the planning doc), with the substring
   hazards called out per file so no non-task token is corrupted.
3. A verification approach that proves zero old task references survive and the
   seven new tasks parse.

The ordering of edits (longest/most specific old names first, then bare names
with word boundaries) is the one load-bearing design decision; see
**Substring Hazards** and **Edit strategy** below.

## Substring Hazards (read first)

A naive find/replace will corrupt this repo. These are the traps, with the rule
for each:

- **`provision` is a substring of many non-task tokens.** It appears in the
  script filename `provision.py`, the task names `provision-plan` /
  `provision-render`, the directory `subscription/scripts`, and the English word
  `provisioning`/`provision` used as prose (e.g. "the main IaC provisioning").
  Only rename the **task reference** `provision` (the `[tasks.provision]` header
  and the `mise run provision` phrase). NEVER touch `provision.py`,
  `provisioning`, the directory path, or prose uses of the verb "provision".
  Rename the *longer* names (`provision-plan`, `provision-render`) BEFORE the
  bare `provision`, and match bare `provision` only with a trailing word
  boundary (`provision` not followed by `-` or `.py`), so `provision-plan` is
  never partially rewritten to `subscription-apply-plan`.
- **`credentials` collides with filenames and a path.** It is the filename stem
  in `output/credentials.md`, `credentials.template.md`, and the renderer path
  `.aws/credentials`, and the English word "credentials" in prose. Only rename
  the **task reference** `credentials` — the `[tasks.credentials]` header and the
  `mise run credentials` phrase. NEVER touch `credentials.md`,
  `credentials.template.md`, `.aws/credentials`, or the prose noun "credentials".
- **The three `teardown-*` names share a prefix.** `teardown-plan`,
  `teardown-run`, and `teardown-tofu` are distinct tasks mapping to three
  distinct new names. Match each as a whole token so `teardown-plan` is not
  rewritten by a `teardown-run` rule (and vice versa), and so `subscription-`
  is prepended to the correct one. `teardown-tofu` maps to `subscription-destroy`
  (a verb change), NOT `subscription-teardown-tofu`.
- **Ordering rule that defuses all of the above:** apply the longest / most
  specific old names first (`provision-plan`, `provision-render`,
  `teardown-tofu`, `teardown-plan`, `teardown-run`), then the bare `provision`
  with a trailing word boundary, then the bare `credentials` with a word
  boundary. Within each file, operate on `mise run <name>` phrases, `[tasks.<name>]`
  headers, and backtick-quoted `` `<name>` `` self-references — not on free text
  that merely contains the substring.

## Components and Interfaces

There are no runtime components. The "components" of this change are the
surfaces that reference task names — each is a file (or region of a file) whose
contract is the task-name vocabulary it exposes or consumes:

- **Task_Registry (`mise.toml`).** The authoritative component. Its interface is
  the set of invokable task names: callers run `mise run <name>` and the registry
  declares each task under a `[tasks.<name>]` header. This change rewrites seven
  of those names (and the self-referencing comments/echo that name them), which
  is the interface change every other component must track.
- **Operator docs (`README.md`, `subscription/RUNBOOK.md`,
  `subscription/TEARDOWN.md`, `subscription/output/credentials.template.md`).**
  Consumers of the task-name interface. They instruct operators with
  `mise run <name>` phrases and backtick-quoted task names that must match the
  registry exactly.
- **`provision.py` help string.** A consumer of the interface at runtime: the
  `BACKEND_SETUP_HELP` string prints two `mise run <task>` tokens that must point
  at the renamed tasks. (The filename and `python provision.py` invocations are
  not part of this interface — see the hazard guard list.)
- **Planning doc (`.agents/tasks/remote-state-plan.md`).** A consumer that
  documents the tasks under their names in prose and must track the rename.

The exact per-file, per-line reference points for each component are enumerated
in the **In-repo occurrence catalogue** below.

## Data Models

There are no runtime data structures. The only "data model" in this change is
the **Rename Mapping** — the fixed set of old→new task-name pairs defined in the
*Rename Mapping (the single source of truth)* table in the Overview. Every edit
is a lookup against those seven pairs; no other mapping, alias, or derived
structure exists. Refer to that table as the authoritative model for all
replacements (Validates R4.7).

## In-repo occurrence catalogue (authoritative sweep)

Every surviving occurrence of each old task name, by file and kind. Each row is
a required edit unless marked **(do not change)** or **(history — leave as-is)**.

### mise.toml (Task_Registry)

| Line (approx) | Old name       | Kind                              | Action |
|---------------|----------------|-----------------------------------|--------|
| 149           | `provision-plan` | comment self-reference          | → `subscription-plan` |
| 151           | `provision`      | comment self-reference (bare)   | → `subscription-apply` |
| 153           | `provision-plan` | task declaration header         | → `[tasks.subscription-plan]` |
| 165           | `provision`      | task declaration header (bare)  | → `[tasks.subscription-apply]` |
| 209           | `provision-render` | task declaration header       | → `[tasks.subscription-render]` |
| 218           | `credentials`    | task declaration header (bare)  | → `[tasks.subscription-credentials]` |
| 231           | `credentials`    | echo string `mise run credentials` (R5.2) | → `mise run subscription-credentials` |
| 239           | `teardown-plan`  | comment self-reference          | → `subscription-teardown-plan` |
| 240           | `teardown-tofu`  | comment self-reference          | → `subscription-destroy` |
| 243           | `teardown-plan`  | task declaration header         | → `[tasks.subscription-teardown-plan]` |
| 248           | `teardown-run`   | task declaration header         | → `[tasks.subscription-teardown-run]` |
| 253           | `teardown-tofu`  | task declaration header         | → `[tasks.subscription-destroy]` |

Notes on `mise.toml`:
- There are **no `run`-body cross-references between the subscription tasks**.
  Each subscription task's `run` body invokes `python provision.py` /
  `python teardown.py` or shell helpers, not `mise run <sibling>`. The only
  self-reference inside a run body is the echo at line 231 (R5.2). So R3.2's
  "preserve run logic except self-reference lines" reduces to: change only that
  one echo line; every other run line stays byte-for-byte.
- The description text that mentions the verb "provision" / "credentials" as
  English prose (e.g. the `subscription-apply` description "…then render
  credentials") is **functional intent, not a task self-reference** — leave it
  (R3.3). Only backtick/`mise run`-shaped task names change.
- The comment block header `# === subscription/ stack ===` and the directory
  values (`subscription/scripts`, `subscription/terraform`) are **not** task
  names — leave them (they also preserve R3.1, identical `dir`).

### README.md

| Line (approx) | Old name       | Kind                    | Action |
|---------------|----------------|-------------------------|--------|
| 153           | `provision`    | prose `mise run provision` fails-closed note | → `subscription-apply` |
| 164           | `provision-plan` | `mise run provision-plan` | → `subscription-plan` |
| 165           | `provision`    | `mise run provision`    | → `subscription-apply` |
| 222           | `teardown-tofu`| prose `(…, teardown-tofu)` | → `subscription-destroy` |
| 233           | `teardown-plan`| `mise run teardown-plan`| → `subscription-teardown-plan` |
| 234           | `teardown-tofu`| `mise run teardown-tofu`| → `subscription-destroy` |
| 235           | `teardown-run` | `mise run teardown-run` | → `subscription-teardown-run` |

(The requirements cite "near lines 153, 164, 165, 232, 233, 234"; the live file
places them at 153, 164, 165, 222, 233, 234, 235. The content, not the line
number, is authoritative — R4.1.)

### subscription/RUNBOOK.md

| Line (approx) | Old name       | Kind | Action |
|---------------|----------------|------|--------|
| 84            | `provision-plan` | prose `mise run provision-plan` | → `subscription-plan` |
| 97            | `provision-plan` | `mise run provision-plan` | → `subscription-plan` |
| 100           | `provision`    | `mise run provision` | → `subscription-apply` |
| 130           | `provision`    | prose `mise run provision` | → `subscription-apply` |
| 178           | `credentials`  | prose `mise run credentials` | → `subscription-credentials` |
| 227           | `credentials`  | `mise run credentials` | → `subscription-credentials` |
| 283           | `teardown-tofu`| `mise run teardown-tofu` | → `subscription-destroy` |
| 290           | `teardown-plan`| `mise run teardown-plan` | → `subscription-teardown-plan` |
| 292           | `teardown-run` | `mise run teardown-run` | → `subscription-teardown-run` |

### subscription/TEARDOWN.md

| Line (approx) | Old name       | Kind | Action |
|---------------|----------------|------|--------|
| 96            | `teardown-tofu`| `mise run teardown-tofu` | → `subscription-destroy` |
| 99            | `teardown-tofu`| prose `` `mise run teardown-tofu` `` | → `subscription-destroy` |
| 127           | `teardown-plan`| prose `mise run teardown-plan` | → `subscription-teardown-plan` |
| 128           | `teardown-run` | prose `mise run teardown-run` | → `subscription-teardown-run` |
| 139           | `teardown-run` | comment `# or: mise run teardown-run` | → `subscription-teardown-run` |
| 136           | `teardown-plan`| comment `# or: mise run teardown-plan` | → `subscription-teardown-plan` |
| 185           | `teardown-plan`| prose `teardown-plan is a safe dry run` | → `subscription-teardown-plan` |
| 188           | `teardown-plan`| `mise run teardown-plan` | → `subscription-teardown-plan` |
| 189           | `teardown-run` | `mise run teardown-run` | → `subscription-teardown-run` |
| 190           | `teardown-tofu`| `mise run teardown-tofu` | → `subscription-destroy` |
| 193           | `teardown-plan`| prose `mise run teardown-plan` | → `subscription-teardown-plan` |

### subscription/output/credentials.template.md

| Line (approx) | Old name      | Kind | Action |
|---------------|---------------|------|--------|
| 5             | `credentials` | prose `(run it via `mise run credentials`)` | → `subscription-credentials` |

Hazard: the surrounding filenames `credentials.md` / the template's own name and
the renderer `provision_passwords_and_output.py` are **(do not change)** — only
the `mise run credentials` task phrase changes (R4.4).

### subscription/scripts/provision.py

| Line (approx) | Old name       | Kind | Action |
|---------------|----------------|------|--------|
| 117           | `provision-plan` / `provision` | comment `# Then re-run provisioning` (prose "provisioning" is **do not change**) | leave the word "provisioning" |
| 119           | `provision-plan`, `provision` | run-time help string (`BACKEND_SETUP_HELP`) `mise run provision-plan   # or: mise run provision` | → `mise run subscription-plan   # or: mise run subscription-apply` |

Hazards in this file, explicit: the **filename `provision.py` is never renamed**;
the module/script references `python provision.py`, `python teardown.py`, and the
word `provisioning` in the comment are **(do not change)**. Only the two
`mise run <task>` tokens inside the `BACKEND_SETUP_HELP` string change. The user
brief flags this as a "run-body reference in addition to comments" — the string
is printed at runtime, so it is a live reference, not a comment (R4.6 covers the
file; the mapping still applies to the printed string).

### .agents/tasks/remote-state-plan.md

This file documents the subscription tasks under their old names in planning
prose. Required edits (R4.5):

| Line (approx) | Old name       | Kind | Action |
|---------------|----------------|------|--------|
| 30            | `provision`, `teardown-tofu` | prose `` `provision`/`teardown-tofu` behave `` | → `subscription-apply`/`subscription-destroy` |
| 121           | `provision-plan` | prose `` `mise run provision-plan` `` | → `subscription-plan` |
| 125           | `provision-plan`, `provision` | prose `` `mise run provision-plan`/`provision` `` | → `subscription-plan`/`subscription-apply` |
| 153           | `provision-plan`, `provision` | prose `` `provision-plan`/`provision` lines `` | → `subscription-plan`/`subscription-apply` |
| 156           | `teardown-tofu`| prose `` `teardown-tofu ... needs remote state` `` | → `subscription-destroy` |

Hazards: this file uses the verb "provisioning" and references `provision.py`
heavily in prose and commit-message examples (e.g. `feat(provision): …`). Those
are **(do not change)** — they are not task references. Only backtick-quoted task
names and `mise run <task>` phrases change. Commit-message scopes like
`feat(provision)` are historical plan text; leave them.

### .kiro/specs/multi-workshop-provisioning/design.md and tasks.md

These are historical spec artifacts for a *different, already-completed* feature.
They contain `[tasks.provision]`, `[tasks.teardown-tofu]`, and prose
`` `teardown-tofu` `` (design.md lines 688, 722, 778) and a task-list line naming
`provision`, `teardown-tofu` (tasks.md line 136).

Decision: **leave these as-is (history — do not change).** They are not
operator-facing instructions that "point at a removed task"; they are a frozen
record of how that feature was built, and editing them would rewrite history
without benefit. Requirement 4 enumerates the files that MUST change (R4.1–R4.6)
and does **not** list these two. The user brief named them as files that *contain*
old references so the sweep would surface them — this design surfaces them here
and consciously scopes them OUT, so the verification grep must exclude the
`.kiro/specs/` tree (and this feature's own `requirements.md`/`design.md`) when
asserting "zero surviving references." If the repo owner wants the historical
specs updated too, that is a separate, explicit decision.

### Files that must NOT change (hazard guard list)

- `subscription/scripts/provision.py` as a **filename** and all `python provision.py`
  invocations repo-wide.
- `subscription/scripts/teardown.py` and `python teardown.py` invocations.
- The directories `subscription/scripts`, `subscription/terraform`.
- The words `provisioning` / `provision` used as English verbs/nouns in prose.
- `output/credentials.md`, `credentials.template.md`, `.aws/credentials`, and the
  noun "credentials" in prose.
- `.env.example` line 23 names `provision`, `teardown-tofu` — **this file is NOT
  in Requirement 4's list.** Flag it for the operator but treat it as out of
  scope for this spec (same rule as the historical specs). (Noted so the sweep
  result is explainable, not silently ignored.)
- `.kiro/specs/multi-workshop-provisioning/*` and this feature's own spec files.

## Edit strategy (ordered)

1. **`mise.toml` first.** Apply the twelve edits in the mise.toml table. Rename
   the seven `[tasks.X]` headers, the four self-referencing comment lines, and
   the one echo string. Confirm the four shared tasks (`setup`, `lock`,
   `aws-configure`, `verify`) and all `backend-*`/`claim-*`/`foundation-*`/
   `governance-*` headers are untouched (R2.3, R3.4). Confirm each renamed task's
   `dir` and (non-echo) `run` lines are byte-identical (R3.1, R3.2).
2. **Operator docs:** `README.md`, `subscription/RUNBOOK.md`,
   `subscription/TEARDOWN.md`, `subscription/output/credentials.template.md`
   (R4.1–R4.4).
3. **Source help string:** `subscription/scripts/provision.py` — the two
   `mise run` tokens in `BACKEND_SETUP_HELP` only (R4.6).
4. **Planning doc:** `.agents/tasks/remote-state-plan.md` (R4.5).

Within every file, apply the longest old names before the bare ones, and match
only task-shaped occurrences (`[tasks.<name>]`, `mise run <name>`, backtick
`` `<name>` ``), per the Substring Hazards section.

## Error Handling

Not applicable at runtime — this change ships text edits only. The failure mode
is a *missed or wrong edit*, handled by the verification approach below (grep +
`mise tasks` parse + test suite), not by code.

## Verification Approach

Run from the repo root after all edits.

1. **Zero surviving old task references (the master check, R5.3 / R4.x).** Grep
   the whole repo with task-reference-shaped patterns, excluding the historical
   spec tree and `.env.example` (scoped out above). Patterns (use whole-token /
   word-boundary forms to dodge the substring hazards):
   - `mise run provision-plan`, `mise run provision-render`,
     `mise run teardown-tofu`, `mise run teardown-plan`, `mise run teardown-run`
   - `mise run provision\b` (bare, not `-plan`/`-render`)
   - `mise run credentials\b`
   - `\[tasks\.(provision|provision-plan|provision-render|teardown-tofu|teardown-plan|teardown-run|credentials)\]`
   Exclude: `.kiro/specs/`, `.env.example`. Expect **no matches**. A match
   outside the excluded set is a defect to fix before proceeding.
2. **The seven new names parse (R1.1–R1.7, R2.1).** Run `mise tasks` (or
   `mise tasks ls`). Assert the output lists exactly `subscription-plan`,
   `subscription-apply`, `subscription-destroy`, `subscription-render`,
   `subscription-credentials`, `subscription-teardown-plan`,
   `subscription-teardown-run`, and none of the seven old names, with no TOML
   parse error. Also confirm `setup`, `lock`, `aws-configure`, `verify` and the
   other stacks' tasks still list (R2.3, R3.4).
3. **Test suite.** The repo uses pytest + Hypothesis + moto. Run the root suite
   (`uv run --group dev pytest -q` from the repo root; claim-service tests run
   the same way from `claim-service/`). Pay special attention to
   `tests/test_keyless_backend.py`: its `MUTATING_TASKS` tuple hard-codes
   `("provision", "teardown-tofu", "claim-deploy", "claim-destroy")` and its
   `_task_block()` helper looks up `[tasks.<name>]` headers in `mise.toml`. After
   the rename, `provision` and `teardown-tofu` no longer exist as headers, so
   those parametrized cases will raise `ValueError` from `toml.index(...)`.
   **This test is NOT in Requirement 4's edit list and asserts a different
   feature's contract**, but it will break mechanically. The design's position:
   update `MUTATING_TASKS` to `("subscription-apply", "subscription-destroy",
   "claim-deploy", "claim-destroy")` so the keyless-backend contract keeps
   validating the same two subscription tasks under their new names. This is a
   consequential reference update (the test references the task *names*), so it
   belongs in this change even though R4 did not enumerate it — flag it to the
   repo owner as the one in-code test touched beyond the doc list.
4. **Behavior-preservation spot check (R3.1–R3.3).** Diff `mise.toml` and confirm
   the only changed lines are the seven headers, four comment self-references,
   and one echo string — every `dir`, every non-echo `run` line, and every
   description's functional words are unchanged.

## Testing Strategy

Testing mirrors the Verification Approach above; it is example-based and static,
not property-based (see Correctness Properties for why). Three checks together
establish correctness:

1. **Targeted whole-repo grep (master check).** Run the task-reference-shaped
   patterns from the Verification Approach against the whole repo, excluding the
   historical spec tree (`.kiro/specs/`) and `.env.example`, and assert **zero**
   surviving old task references. The word-boundary / whole-token forms dodge the
   substring hazards (R4.1–R4.7, R5.1, R5.3).
2. **`mise tasks` parse check.** Run `mise tasks` and assert the seven new
   `subscription-*` names list with no TOML parse error, none of the seven old
   names appear, and the shared tasks and other stacks' tasks are untouched
   (R1.1–R1.7, R2.1–R2.3, R3.4).
3. **pytest + Hypothesis + moto suite.** Run the root suite
   (`uv run --group dev pytest -q`; claim-service tests run the same way from
   `claim-service/`). This includes updating `tests/test_keyless_backend.py`:
   its `MUTATING_TASKS` tuple must change from
   `("provision", "teardown-tofu", …)` to
   `("subscription-apply", "subscription-destroy", …)` so the keyless-backend
   contract keeps validating the two renamed subscription tasks under their new
   names and doubles as a regression guard that they still parse from `mise.toml`.

A behavior-preservation diff of `mise.toml` (only the seven headers, four comment
self-references, and one echo string changed) closes out R3.1–R3.3.

## Non-Goals

- **No behavior changes.** `dir`, `run` logic, and description intent are
  preserved verbatim; only names and name self-references change (R3.1–R3.3).
- **Other stacks untouched.** `backend-*`, `claim-*`, `foundation-*`,
  `governance-*` task names are left exactly as they are (R3.4).
- **Shared toolchain tasks stay unprefixed.** `setup`, `lock`, `aws-configure`,
  `verify` keep their bare names (R2.3).
- **No aliases or compatibility shims.** Old names are removed outright; there is
  exactly one way to invoke each task (R2.1, R2.2).
- **Historical spec artifacts and `.env.example` are out of scope.** The
  `.kiro/specs/multi-workshop-provisioning/*` files and `.env.example` contain old
  names but are surfaced-and-scoped-out above, not edited by this change.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid
executions of a system — a formal statement about what the system should do.*

This feature is a one-shot, deterministic rename of a fixed set of names in a
fixed set of files. Every acceptance criterion is a **static text fact** about
the content of specific files after the edit; none describe behavior that varies
with generated input. There is no pure function and no input space over which to
quantify, so there is no meaningful "for all inputs X, P(X) holds" statement to
write. Per the property-based-testing guidance, PBT is **not appropriate** here
(this falls under the "configuration / not-a-function" and "deterministic,
one-shot operation" exclusions).

Accordingly, this design defines **no property-based tests**. For completeness,
the one invariant that holds across the entire repo is stated below as an
explicit, numbered property; it is verified by the targeted grep (an exhaustive
static check over all tracked files), not by randomized input generation.

### Property 1: No old task name survives as a task reference

*For any* tracked file in the repo outside the explicitly scoped-out set
(`.kiro/specs/` and `.env.example`), after the rename there is **no** occurrence
of any old task name in task-reference shape — i.e. no `mise run <old>`, no
`[tasks.<old>]` header, and no backtick-quoted `` `<old>` `` self-reference —
for any `<old>` in `{provision, provision-plan, provision-render, teardown-tofu,
teardown-plan, teardown-run, credentials}`.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.3**

Verified by the whole-repo targeted grep (patterns and exclusions in the
Verification Approach / Testing Strategy), not by a property-based test — the
grep is an exhaustive static check, so randomized generation adds nothing.

Correctness is otherwise established by the example-based and static assertions
in the Verification Approach:

- Parse `mise.toml` and assert the seven `subscription-*` headers exist, the
  seven old headers are absent, the task-header set totals exactly seven
  subscription tasks, and the four shared tasks plus the other stacks' tasks are
  unchanged (Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2,
  2.3, 3.4).
- Assert each renamed task's `dir` equals its pre-rename value and the
  re-run echo string names `subscription-credentials` (Validates: Requirements
  3.1, 5.2).
- Whole-repo targeted grep (patterns and exclusions above) returns zero surviving
  old task references (Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7,
  5.1, 5.3).

The existing `tests/test_keyless_backend.py` is the one automated test that
exercises these names; after updating its `MUTATING_TASKS` tuple to the new
names it continues to assert the keyless-backend contract and doubles as a
regression guard that the two renamed subscription tasks still parse out of
`mise.toml`.
