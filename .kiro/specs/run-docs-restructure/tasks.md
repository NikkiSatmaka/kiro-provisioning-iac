# Implementation Plan: Run documentation restructure

## Overview

This is a **documentation-only** effort. Every task edits, creates, or deletes a
Markdown file; no application code, OpenTofu configuration, Python scripts, or
`mise.toml` change. The plan follows the design's file inventory and DRY
strategy: each stack collapses into a single `Step_Document` (`*/README.md`),
all teardown detail moves into one root `TEARDOWN.md`, and the root `README.md`
becomes an overview that links out instead of inlining command detail.

Tasks are ordered so cross-references resolve as they are introduced. The root
`README.md` is rewritten first to establish the canonical 0→6 order and the link
targets; `TEARDOWN.md` is created next so every Step_Document's teardown pointer
has a live target before the Step_Documents are written. The verification pass
runs last against the completed set.

The design classifies every acceptance criterion as example/structural or
editorial (zero property-based-testing candidates), so there are no property
test tasks. Verification is the VC-1..VC-9 structural checks plus a
plain-language editorial review, captured as the final task.

## Tasks

- [x] 1. Rewrite the root `README.md` as the overview-and-navigation entry point
  - Rewrite `README.md` in place following the Root_README outline (design
    Component 2): remove the per-stack command detail and replace it with links.
  - Lead with the overview of what the repo provisions and the
    organization-versus-account distinction, stated before the ordered step list.
  - Carry the Phase 0 prep directly in this file (it is owned by no stack):
    ordered list of `mise install`, `mise run setup`, `cp .env.example .env`
    (edit `AWS_PROFILE`/`AWS_REGION`, and `WORKSHOP_CODE` for claim-service),
    `mise run aws-login`, `mise run verify`.
  - Present the ordered 0→6 flow as a table whose stack rows link to each
    `Step_Document` (`backend/README.md` … `claim-service/README.md`) and whose
    Phase 0 row points at the in-README Phase 0 section; inline no stack run
    commands.
  - Place the Decision_Checkpoint summary before the step-3/step-4 (governance)
    rows, posed as a plain-language question with perform (management/org) and
    skip (child/account) answers.
  - Place the order-reconciliation note beside the step table, explaining that
    governance (3–4) now runs before subscription (5), unlike the old README.
  - Add the teardown link pointing to `./TEARDOWN.md` (created in task 2; this is
    a deliberate forward reference resolved by the next task).
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 4.1, 5.6, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3_

- [x] 2. Create the single root `TEARDOWN.md` and delete `subscription/TEARDOWN.md`
  - [x] 2.1 Author `TEARDOWN.md` at the repo root following the Teardown_Document outline
    - Create `TEARDOWN.md` presenting every stack's teardown in reverse of the
      provisioning order (6 → 1): claim-service, subscription, governance,
      governance-shared, foundation, backend.
    - Reference the real destroy/teardown tasks: `mise run claim-destroy`;
      `mise run subscription-teardown-plan` → `mise run subscription-destroy`
      (with `subscription-teardown-run` as the state-free fallback) plus the
      manual Kiro-console cleanup; `mise run governance-move-accounts-out` →
      `mise run governance-destroy`; the manual `tofu destroy` for
      governance-shared (note there is intentionally no
      `governance-shared-destroy` task); foundation as a documented no-op
      (`foundation-destroy`); `mise run backend-destroy-workshop` and
      `mise run backend-destroy` for backend.
    - List dry-run tasks before their mutating siblings; add the `WORKSHOP_ID`
      precondition note.
    - Mark the governance and governance-shared sections as **organization mode
      only** with the Decision_Checkpoint skip-in-account-mode guidance.
    - This file is the sole owner of detailed teardown steps.
    - _Requirements: 3.1, 3.2, 3.4, 3.5, 5.3, 6.3, 6.4_
  - [x] 2.2 Delete `subscription/TEARDOWN.md`
    - Remove the file now that its content is absorbed and generalized into the
      root `TEARDOWN.md`.
    - _Requirements: 2.6, 3.1, 3.5_

- [x] 3. Consolidate `backend/README.md` into the Step_Document template (step 1)
  - Restructure `backend/README.md` in place to the standard section order:
    header with phase link and prerequisites/next, "What it is", "Prerequisites",
    "How to run", "Teardown".
  - "How to run" references `mise run backend-bootstrap-plan` (dry run) before
    `mise run backend-bootstrap` (mutating); note the bootstrap writes every
    stack's `backend.hcl`.
  - "Teardown" is a one-line pointer to `../TEARDOWN.md` only — no detailed
    destroy steps.
  - State each fact exactly once; keep plain-language phrasing.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.1, 5.3, 5.4, 6.1, 6.2, 6.4_

- [x] 4. Consolidate `foundation/README.md` and delete `foundation/RUNBOOK.md` (step 2)
  - [x] 4.1 Merge `foundation/README.md` + `foundation/RUNBOOK.md` into the Step_Document template
    - Rewrite `foundation/README.md` in place merging the README and RUNBOOK into
      one concept-first document; state shared facts exactly once.
    - "How to run" references `mise run foundation-plan` (dry run) before
      `mise run foundation-apply` (mutating), then the wire-forward of
      `instance_arn` / `identity_store_id` into the subscription step.
    - Keep the Step 0 "enable IdC" prerequisite and the dual-mode (org/account)
      caution; teardown is a one-line pointer to `../TEARDOWN.md` noting
      `foundation-destroy` is a documented no-op (detail lives in TEARDOWN.md).
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.1, 5.3, 5.5, 6.1, 6.2, 6.4_
  - [x] 4.2 Delete `foundation/RUNBOOK.md`
    - Remove the RUNBOOK now that its run order folds into the Step_Document.
    - _Requirements: 2.2_

- [x] 5. Consolidate `governance-shared/README.md` and delete its `RUNBOOK.md` (step 3)
  - [x] 5.1 Merge `governance-shared/README.md` + `RUNBOOK.md`, opening with the Decision_Checkpoint
    - Rewrite `governance-shared/README.md` in place so the Decision_Checkpoint
      is the first content block (before "What it is"), stating the
      management-account/organization-mode condition in plain language with
      perform (org) and skip (account) branches.
    - Then concept (singletons: budgets role + 2 SCP objects), the
      all-features/SCP-policy-type precondition, `governance-shared-plan` (dry
      run) → `governance-shared-apply` (mutating), and the three `TF_VAR_*`
      wire-forward.
    - Keep the one-time `tofu state mv` migration as a clearly-marked "existing
      deployments only" run-guidance section (not teardown); teardown is a
      one-line pointer to `../TEARDOWN.md`.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 4.2, 4.4, 4.5, 4.6, 5.1, 5.3, 6.1, 6.2, 6.3, 6.4_
  - [x] 5.2 Delete `governance-shared/RUNBOOK.md`
    - Remove the RUNBOOK now that its run order folds into the Step_Document.
    - _Requirements: 2.2_

- [x] 6. Consolidate `governance/README.md` and delete its `RUNBOOK.md` (step 4)
  - [x] 6.1 Merge `governance/README.md` + `RUNBOOK.md`, opening with the Decision_Checkpoint
    - Rewrite `governance/README.md` in place so the Decision_Checkpoint is the
      first content block (before "What it is"), with the same plain-language
      management-vs-child condition and perform/skip branches.
    - Then concept (one OU, guardrail attachment, auto-freeze budgets),
      `governance-plan` (dry run) → `governance-apply` →
      `governance-place-accounts`, and the automatic-freeze / manual-unfreeze
      behavior; teardown is a one-line pointer to `../TEARDOWN.md` (the two-step
      guarded teardown lives in TEARDOWN.md).
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 4.3, 4.4, 4.5, 4.6, 5.1, 5.3, 6.1, 6.2, 6.3, 6.4_
  - [x] 6.2 Delete `governance/RUNBOOK.md`
    - Remove the RUNBOOK now that its run order folds into the Step_Document.
    - _Requirements: 2.2_

- [x] 7. Consolidate `subscription/README.md` and delete `subscription/RUNBOOK.md` (step 5)
  - [x] 7.1 Merge `subscription/README.md` + `RUNBOOK.md` into the Step_Document template
    - Rewrite `subscription/README.md` in place merging README and RUNBOOK into
      one concept-first document; extract all teardown content out to the root
      `TEARDOWN.md` (created in task 2), leaving only a one-line pointer.
    - Concept covers what is provisioned, where identities live, the console-only
      AWS limits, and the dual-mode note; "How to run" references
      `subscription-plan` (dry run) → `subscription-apply`, the console-only
      steps, and `subscription-credentials` / `subscription-render`.
    - State each fact exactly once.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.1, 5.3, 6.1, 6.2, 6.4_
  - [x] 7.2 Delete `subscription/RUNBOOK.md`
    - Remove the RUNBOOK now that its run order folds into the Step_Document.
    - _Requirements: 2.2_

- [x] 8. Consolidate `claim-service/README.md` into the Step_Document template (step 6)
  - Restructure `claim-service/README.md` in place to the standard template.
  - Concept covers the self-serve claim via one Lambda Function URL;
    prerequisites cover Phase 3 outputs and `WORKSHOP_CODE`; "How to run" lists
    the lifecycle `claim-test` → `claim-deploy-plan` → `claim-deploy` →
    `claim-url` → `claim-seed-plan` → `claim-seed` → `claim-audit` (dry-run
    tasks before mutating siblings).
  - "Teardown" is a one-line pointer to `../TEARDOWN.md` only.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.1, 5.3, 6.1, 6.2, 6.4_

- [x] 9. Verification pass — structural checks and editorial review
  - [x] 9.1 Run the VC-1..VC-8 structural checks across the completed Documentation_Set
    - VC-1 (ordering): README shows Phase 0 then steps 1→6 in canonical order,
      governance before subscription. _Requirements: 1.1, 7.1, 7.3_
    - VC-2 (link-out, no inlining): each stack step links to its Step_Document,
      no stack run commands inlined in README, README links to `TEARDOWN.md`.
      _Requirements: 1.2, 1.4, 3.3_
    - VC-3 (inventory): exactly one Step_Document per stack in its folder, exactly
      one `Teardown_Document`, and the deleted files (foundation /
      governance-shared / governance / subscription `RUNBOOK.md`,
      `subscription/TEARDOWN.md`) are gone. _Requirements: 2.1, 2.5, 3.1_
    - VC-4 (consolidation + concept→run order): each Step_Document contains the
      merged concept and run content, concept first. _Requirements: 2.2, 2.3_
    - VC-5 (teardown centralization): detailed destroy steps only in
      `TEARDOWN.md`; each Step_Document teardown is a pointer; reverse order with
      governance/governance-shared marked org-only. _Requirements: 2.6, 3.2, 3.4, 3.5_
    - VC-6 (decision checkpoint): checkpoint precedes the governance links in
      README and opens both governance Step_Documents, perform/skip branches in
      plain language. _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_
    - VC-7 (task references valid, dry-run first): every `mise run <name>` in the
      set matches a `[tasks.<name>]` in `mise.toml`; backend and foundation
      reference their named plan+apply tasks; Phase 0 references the four
      toolchain tasks; each dry-run task precedes its mutating sibling.
      _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 8.3_
    - VC-8 (scope): the change set modifies only Markdown files — no `.tf`,
      `.py`, `.toml`, `.hcl`, or `.sh` touched. _Requirements: 8.1, 8.2_
  - [x] 9.2 Run the VC-9 plain-language editorial review
    - Confirm glossary terms are explained at or before first use in each
      document, each step states the action and expected result, decisions are
      posed as questions with per-answer actions, and procedures are ordered
      lists. _Requirements: 6.1, 6.2, 6.3, 6.4_

## Notes

- This workflow produces documentation artifacts only; no feature code or
  `mise.toml` is implemented or modified (R8).
- Every task is Markdown-only. Deletions (RUNBOOK.md files, subscription/TEARDOWN.md)
  are part of the DRY consolidation, not code changes.
- Each task references the specific requirement clauses it satisfies for
  traceability.
- Ordering is deliberate: the root `README.md` (task 1) establishes the canonical
  0→6 order and link targets, `TEARDOWN.md` (task 2) is created before any
  Step_Document points to it, and the Step_Documents (tasks 3–8) follow in
  provisioning order. The README's teardown link in task 1 is a forward reference
  resolved by task 2.
- The design defines zero property-based-testing candidates for this docs-only
  change, so verification (task 9) uses the VC-1..VC-9 structural checks and
  editorial review in place of property tests.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "3", "4.1", "5.1", "6.1", "7.1", "8"] },
    { "id": 3, "tasks": ["4.2", "5.2", "6.2", "7.2"] },
    { "id": 4, "tasks": ["9.1", "9.2"] }
  ]
}
```
