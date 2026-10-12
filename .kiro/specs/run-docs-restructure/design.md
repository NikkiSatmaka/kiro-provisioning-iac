# Design Document — Run documentation restructure

## Overview

This design turns the current scattered run/provisioning docs into a single
`Documentation_Set` that a non-expert operator can follow top to bottom. The
work is **documentation only**: every artifact is Markdown, and nothing in the
application code, OpenTofu configuration, Python scripts, or `mise.toml`
changes. `mise.toml` stays the single source of truth for task definitions; the
docs *reference* task names, never restate their bodies.

Two forces shape the structure:

1. **One ordered path for a non-expert.** The root README is the only entry
   point. It carries Phase 0 prep itself, then links out to one document per
   stack in the operator order 0→6, with an early "do I need the governance
   steps?" decision so a child-account operator never runs management-only
   steps.
2. **DRY — each fact documented once.** Each stack collapses its former
   `README.md` + `RUNBOOK.md` + any teardown content into a single
   `Step_Document`. All teardown detail moves into one `Teardown_Document`. The
   root README stops inlining per-stack commands and links out instead.

### Grounding in the actual repo

The design is pinned to what the repo really contains today:

- **Task names** come verbatim from `mise.toml` (`backend-bootstrap-plan`,
  `backend-bootstrap`, `backend-destroy`, `backend-destroy-workshop`,
  `foundation-plan`, `foundation-apply`, `foundation-destroy` (no-op),
  `governance-shared-plan`, `governance-shared-apply`, `governance-plan`,
  `governance-apply`, `governance-place-accounts`, `governance-move-accounts-out`,
  `governance-destroy`, `subscription-plan`, `subscription-apply`,
  `subscription-render`, `subscription-credentials`, `subscription-teardown-plan`,
  `subscription-teardown-run`, `subscription-destroy`, `claim-test`,
  `claim-deploy-plan`, `claim-deploy`, `claim-url`, `claim-seed-plan`,
  `claim-seed`, `claim-audit`, `claim-destroy`, plus the toolchain tasks
  `setup`, `lock`, `aws-login`, `verify`). There is intentionally **no**
  `governance-shared-destroy` task — governance-shared teardown is a manual
  `tofu destroy`, which the Teardown_Document reflects.
- **Dual-mode reality.** `foundation/` and `subscription/` are dual-mode
  (organization or account instance). `governance-shared/` and `governance/`
  are management-account only. This is the basis for the Decision_Checkpoint.
- **Order reconciliation.** The current root README runs subscription before
  governance and frames governance as an optional sidebar. The new set adopts
  the operator order (governance **before** subscription) and explains the
  change.

Because the workspace is a Markdown/IaC repo (no runnable "feature code" to
produce), code examples in this document are the real shell/`mise` invocations
the docs will contain, shown as fenced blocks — not new program code.

## Architecture

### The Documentation_Set file inventory (final state)

Exact paths of every file in the final set, what merges into each, and what is
removed as a result.

| New / kept file (path) | Role | Merged from (existing files) | Existing files deleted as a result |
| --- | --- | --- | --- |
| `README.md` | `Root_README` — overview, org-vs-account, Phase 0 prep, ordered 0→6 flow with links, order-reconciliation note, teardown link | Rewritten in place from today's `README.md` (overview + Phase 0 kept; per-stack command detail removed and replaced by links) | — (same path, rewritten) |
| `backend/README.md` | `Step_Document` for **backend** (step 1) | `backend/README.md` (only doc the stack has) | — (same path, restructured to the template) |
| `foundation/README.md` | `Step_Document` for **foundation** (step 2) | `foundation/README.md` + `foundation/RUNBOOK.md` | `foundation/RUNBOOK.md` |
| `governance-shared/README.md` | `Step_Document` for **governance-shared** (step 3) — opens with Decision_Checkpoint | `governance-shared/README.md` + `governance-shared/RUNBOOK.md` | `governance-shared/RUNBOOK.md` |
| `governance/README.md` | `Step_Document` for **governance** (step 4) — opens with Decision_Checkpoint | `governance/README.md` + `governance/RUNBOOK.md` | `governance/RUNBOOK.md` |
| `subscription/README.md` | `Step_Document` for **subscription** (step 5) | `subscription/README.md` + `subscription/RUNBOOK.md`; teardown content extracted out | `subscription/RUNBOOK.md` |
| `claim-service/README.md` | `Step_Document` for **claim-service** (step 6) | `claim-service/README.md` (only doc the stack has) | — (same path, restructured to the template) |
| `TEARDOWN.md` (repo root) | `Teardown_Document` — the single teardown doc, reverse-order, org-only steps marked | `subscription/TEARDOWN.md` + every stack's prior inline teardown sections (backend "Teardown", foundation "Teardown — nothing to destroy", governance-shared "Teardown — long-lived…", governance "Teardown — two steps…", claim-service destroy) | `subscription/TEARDOWN.md` |

Notes on the inventory:

- **Six Step_Documents, one per stack**, each named `README.md` and living
  **inside its own stack folder** (R2.1, R2.5). Keeping the name `README.md`
  means it is still the file a reader lands on when they open the folder on the
  code host.
- The single `Teardown_Document` lives at the **repo root** as `TEARDOWN.md`
  (R3.1). Root placement makes it a peer of the Root_README and avoids implying
  it belongs to any one stack. `subscription/TEARDOWN.md` is deleted; its
  content is absorbed and generalized to all stacks.
- **RUNBOOK.md files are deleted** for foundation, governance-shared,
  governance, and subscription — their run order folds into the stack's single
  Step_Document (R2.2). backend and claim-service have no RUNBOOK today.
- No new directories. All files are Markdown (R8.1, R8.2).

### Document relationship map

```
README.md (Root_README, entry point)
├── Phase 0 prep (lives ONLY here)
├── Decision_Checkpoint (org vs account — summary; precedes governance steps)
├── ordered flow 0 → 6, each step links to:
│     1 backend/README.md
│     2 foundation/README.md
│     3 governance-shared/README.md   ─ opens with Decision_Checkpoint
│     4 governance/README.md          ─ opens with Decision_Checkpoint
│     5 subscription/README.md
│     6 claim-service/README.md
├── order-reconciliation note (beside the step list)
└── teardown link ──────────────▶ TEARDOWN.md (Teardown_Document)
                                     reverse order 6 → 1
                                     org-only steps (3,4) marked skip-in-account-mode

Each Step_Document's "Teardown" subsection = a one-line pointer to TEARDOWN.md
(no detailed destroy steps anywhere but TEARDOWN.md).
```

## Components and Interfaces

### Component 1 — Step_Document section template

Every `Step_Document` follows one standard section order so an operator reads
each stack the same way, concept first and run last (R2.3, R6.2, R6.4):

```markdown
# <Stack> (step N of the flow) — <one-line what-it-is>

> Phase link: this is **Step N** of the root README flow.
> Prerequisites: <prior step(s)> · Next: <next step>

## What it is            ← concept: plain-language "what this stack does and why"
   - one paragraph a non-expert understands
   - the org/account note only where it matters (foundation/subscription dual-mode)

## Prerequisites         ← what must be true/done before running
   - prior steps, required env (.env keys), any one-time console action (e.g. enable IdC)

## How to run            ← ordered list; dry-run task BEFORE the mutating task (R5.1, R5.3)
   1. <mise run ...-plan>   (dry run — reports, changes nothing)
   2. <mise run ...-apply>  (mutates — prompts to approve)
   3. <wire-forward / follow-up, where applicable>

## Teardown              ← SHORT pointer only (R2.6)
   See the root [`TEARDOWN.md`](../TEARDOWN.md) for how to remove this stack.
```

**Governance-shared and governance Step_Documents** additionally **open with the
Decision_Checkpoint** — it is the first content block, before "What it is"
(R4.2, R4.3):

```markdown
# Governance-shared (step 3 of the flow) — ...

## Do I need this step?   ← Decision_Checkpoint (opens the doc)
   **Are you running against the AWS Organizations _management account_?**
   - **Yes — organization mode:** perform this step (and step 4, governance).
   - **No — a child/member account:** **skip** this step and step 4; go to step 5.
   Why: this stack creates AWS Organizations resources that only exist in the
   management account.

## What it is
...
```

The Decision_Checkpoint text states the condition in plain language — tying
**organization mode → management account** and **account mode → child/member
account** (R4.6) — and gives the explicit perform/skip action for each answer
(R4.4, R4.5, R6.3).

Per-stack specifics the template accommodates (grounded in the real docs):

- **backend** — `How to run` references `mise run backend-bootstrap-plan` then
  `mise run backend-bootstrap` (R5.4); notes the bootstrap writes every stack's
  `backend.hcl`. Teardown pointer only.
- **foundation** — `How to run` references `mise run foundation-plan` then
  `mise run foundation-apply` (R5.5), then the wire-forward of `instance_arn` /
  `identity_store_id` into the subscription step. Keeps the Step 0 "enable IdC"
  prerequisite and the dual-mode caution. Teardown pointer notes
  `foundation-destroy` is a documented no-op (detail lives in TEARDOWN.md).
- **governance-shared** — Decision_Checkpoint first; then concept (singletons:
  budgets role + 2 SCP objects), the all-features/SCP-policy-type precondition,
  `governance-shared-plan` → `governance-shared-apply`, and the three
  `TF_VAR_*` wire-forward. The one-time `tofu state mv` migration from
  foundation stays here as a clearly-marked "existing deployments only" section
  (it is run guidance, not teardown).
- **governance** — Decision_Checkpoint first; then concept (one OU, guardrail
  attachment, auto-freeze budgets), `governance-plan` → `governance-apply` →
  `governance-place-accounts`, the automatic-freeze and manual-unfreeze
  behavior. Teardown pointer only (the two-step guarded teardown lives in
  TEARDOWN.md).
- **subscription** — concept (what is provisioned, where identities live, the
  console-only AWS limits, dual-mode), then `subscription-plan` →
  `subscription-apply`, the console-only steps, and
  `subscription-credentials` / `subscription-render`. Teardown pointer only.
- **claim-service** — concept (self-serve claim via one Lambda Function URL),
  prerequisites (Phase 3 outputs, `WORKSHOP_CODE`), then the lifecycle
  `claim-test` → `claim-deploy-plan` → `claim-deploy` → `claim-url` →
  `claim-seed-plan` → `claim-seed` → `claim-audit`. Teardown pointer only.

### Component 2 — Root_README outline

```markdown
# kiro-provisioning-iac

## Overview                         (R1.5)
   - what the repo provisions (Kiro subscriptions via IAM Identity Center),
     "nothing runs automatically" note
## Organization vs account          (R1.5, R6.1)
   - plain-language distinction: management account (organization mode) vs
     child/member account (account mode); which steps each mode runs
## Phase 0 — Set up                 (R1.3, R5.6)  ← lives ONLY here
   1. mise install
   2. mise run setup
   3. cp .env.example .env  (edit AWS_PROFILE / AWS_REGION; WORKSHOP_CODE if using claim-service)
   4. mise run aws-login
   5. mise run verify
## The ordered flow (0 → 6)         (R1.1, R1.2, R7.1, R7.3)
   | Step | What you do | Mode | Doc |
   | 0 Setup        | toolchain + AWS auth              | both | ↑ Phase 0 above |
   | 1 Backend      | shared S3 remote state            | both | backend/README.md |
   | 2 Foundation   | adopt the IdC instance            | both | foundation/README.md |
   | — Decision_Checkpoint: do the governance steps apply to me?  (R4.1) |
   | 3 Governance-shared | mgmt-account singletons      | org only | governance-shared/README.md |
   | 4 Governance   | per-workshop OU + guardrail + budgets | org only | governance/README.md |
   | 5 Subscription | IdC users/groups + console Kiro steps | both | subscription/README.md |
   | 6 Claim-service| optional self-serve distribution  | both | claim-service/README.md |

   > Order-reconciliation note (R7.2, R7.3), right beside the table:
   > "This flow runs the governance steps (3–4) BEFORE subscription (5). Earlier
   >  documentation ran subscription first and treated governance as an optional
   >  sidebar. The order changed so the account guardrails exist before the
   >  identities that will use those accounts. If you followed the old README,
   >  note the reversal."
## Teardown                         (R1.4, R3.3)
   > To remove everything, see [`TEARDOWN.md`](./TEARDOWN.md).
## Reference (repo layout, config knobs, security notes)  — trimmed, links out
```

The Decision_Checkpoint in the Root_README sits **before** the step-3/step-4
links (R4.1); the full checkpoint also opens each governance Step_Document
(R4.2, R4.3). Phase 0 and the ordered flow are the only places those live
(DRY).

### Component 3 — Teardown_Document outline

```markdown
# Teardown — remove everything in reverse order

> Linked from the root README. Set WORKSHOP_ID in .env for the workshop you are
> tearing down; the namespaced tasks fail closed without it.
> Reverse of the provisioning order (6 → 1).

## 6. Claim-service (if you deployed it)
   1. mise run claim-destroy
## 5. Subscription
   1. mise run subscription-teardown-plan   (dry run)
   2. mise run subscription-destroy          (Option B — remote-state tofu destroy, primary)
      - fallback: mise run subscription-teardown-run (Option A — state-free script)
   3. manual Kiro-console cleanup (deactivate subscription, remove IdC app assignment, rm local secrets)
## 4. Governance        🏢 ORGANIZATION MODE ONLY — account-mode operators skip (R3.4)
   1. mise run governance-move-accounts-out  (typed phrase: move-accounts-out)
   2. mise run governance-destroy             (typed phrase: destroy-governance)
## 3. Governance-shared 🏢 ORGANIZATION MODE ONLY — account-mode operators skip (R3.4)
   - long-lived singletons; destroy ONLY at full decommission when no workshop remains
   - manual `tofu destroy` (there is intentionally no governance-shared-destroy task)
## 2. Foundation
   - nothing to destroy: foundation-destroy is a documented no-op (read-only adoption)
   - disabling IdC is a deliberate management-account console action, never a repo task
## 1. Backend  (last)
   - per-workshop state cleanup: mise run backend-destroy-workshop (dry run; APPLY=1 to purge)
   - whole-backend teardown (all workshops done): mise run backend-destroy
```

Each stack's teardown references the **real** destroy/teardown tasks and marks
the org-only steps (governance, governance-shared) with the skip-in-account-mode
guidance (R3.2, R3.4). This is the **only** document that states detailed
teardown steps (R3.5); every Step_Document's teardown subsection is a pointer
here (R2.6).

## Data Models

The "data" of this feature is the fixed set of Markdown documents and the cross
-reference graph among them. The DRY rule assigns each class of content exactly
one owning location:

| Content (stated exactly once) | Owning document | Everyone else |
| --- | --- | --- |
| Phase 0 prep (mise install / setup / aws-login / verify / `.env`) | `Root_README` | link to README |
| Overview + organization-vs-account distinction | `Root_README` | link to README |
| Ordered flow 0→6 + order-reconciliation note | `Root_README` | — |
| Decision_Checkpoint (full) | `governance-shared/README.md` and `governance/README.md` open with it; README carries the summary before the governance links | link / restate the one-line question |
| Per-stack concept + how-to-run | that stack's `Step_Document` | README links to it; no run commands inlined in README (R1.2) |
| Detailed teardown steps | `Teardown_Document` (`TEARDOWN.md`) | Step_Documents carry a one-line pointer only (R2.6, R3.5) |
| Mise task **definitions** (bodies) | `mise.toml` | docs reference `mise run <task>`, never restate the body (R5.1, R5.2, R8.3) |
| Backend/state mechanics (bucket naming, shared-key scheme) | `backend/README.md` | other stacks link to it |

### DRY cross-reference strategy

- **Reference, don't repeat.** When document A needs a fact owned by document B,
  A links to B rather than copying it. Example: a Step_Document that needs the
  toolchain setup links to the Root_README Phase 0 section instead of restating
  the four commands.
- **Task names are references, not copies.** Docs write `mise run foundation-apply`
  and describe the *effect*; they never paste the task's shell body. `mise.toml`
  remains authoritative (R8.2, R8.3). Every `mise run <name>` token in the set
  resolves to a real `[tasks.<name>]` in `mise.toml` (R5.2).
- **Teardown is centralized.** No Step_Document restates destroy sequences; they
  point to `TEARDOWN.md` (R2.6), which is the sole owner (R3.5).
- **Dry-run-before-mutating is a presentation rule everywhere.** Wherever a stack
  has a `*-plan`/`*-apply` (or `*-teardown-plan`/`*-destroy`) pair, the dry-run
  task is listed first (R5.3).

## Error Handling

Documentation "errors" are inaccuracies and DRY violations. The design guards
against them with these rules, checked during authoring and review:

- **Stale task name** → every `mise run <name>` is cross-checked against
  `mise.toml`; a name with no matching task is a defect (R5.2, R8.3).
- **Duplicated detail** → if a fact appears in two documents, one becomes a link
  to the owner (DRY table above). Teardown detail outside `TEARDOWN.md` is a
  defect (R3.5).
- **Wrong order** → the Root_README step list and the `TEARDOWN.md` reverse list
  are checked against the canonical 0→6 order; a mutating task shown before its
  dry-run sibling is a defect (R5.3).
- **Missing mode guidance** → governance and governance-shared content without
  the Decision_Checkpoint (Step_Document open; teardown org-only marker) is a
  defect (R4.2, R4.3, R3.4).
- **Scope creep** → the change set must contain only `*.md` files; any touched
  `.tf` / `.py` / `.toml` / `.hcl` / `.sh` is out of scope (R8.1, R8.2).

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all
valid executions of a system — a formal statement about what the system should
do.*

This feature is **documentation only**: it produces a single, fixed, hand
-authored set of Markdown files. There is no pure function, parser, serializer,
or data transformation with a varying input space to exercise. Per the
property-based-testing guidance, documentation/UI/configuration content is
validated with example-based structural checks, snapshot/grep checks, and
editorial review — **not** property-based tests. Accordingly, the prework
analysis classified every acceptance criterion as **EXAMPLE** or **SMOKE**, and
**no criterion is a property-based-testing candidate**. There are therefore no
universally-quantified `For all generated inputs …` properties to assert here;
asserting one would be meaningless because the "input" is one known document
set.

### Property reflection

Reviewing the testable criteria, they reduce to a few structural checks that
subsume the rest (e.g. the ordering checks 1.1/7.1 share one check; the two
sides of the README↔Teardown link, 1.4 and 3.3, are one check; the task-name
cross-reference 5.2 subsumes 8.3's task half). After consolidation the
verification surface is the example/snapshot checks below plus editorial review
for the plain-language criteria (6.1–6.4). None converts into a universal
property, so the reflection confirms: zero PBT properties for this feature.

### Verification checks (example/structural, in place of properties)

These are the concrete, repeatable checks that stand in for correctness
properties for a docs-only change:

- **VC-1 (ordering).** The Root_README presents Phase 0 then steps 1→6 in the
  canonical order, with governance-shared/governance before subscription.
  **Covers: Requirements 1.1, 7.1, 7.3.**
- **VC-2 (link-out, no inlining).** Each stack step in the Root_README links to
  its Step_Document and inlines no stack run commands; the README links to
  `TEARDOWN.md`. **Covers: Requirements 1.2, 1.4, 3.3.**
- **VC-3 (inventory).** Exactly one Step_Document per stack inside its folder,
  exactly one `Teardown_Document`, and the deleted files
  (foundation/governance-shared/governance/subscription `RUNBOOK.md`,
  `subscription/TEARDOWN.md`) are gone. **Covers: Requirements 2.1, 2.5, 3.1.**
- **VC-4 (consolidation + concept→run order).** Each Step_Document contains the
  merged concept and run content from its prior docs, concept section first.
  **Covers: Requirements 2.2, 2.3.**
- **VC-5 (teardown centralization).** Detailed destroy sequences appear only in
  `TEARDOWN.md`; each Step_Document's teardown subsection is a pointer; the
  teardown sections run in reverse order with governance/governance-shared
  marked org-only. **Covers: Requirements 2.6, 3.2, 3.4, 3.5.**
- **VC-6 (decision checkpoint).** The Decision_Checkpoint precedes the
  governance links in the README and opens both governance Step_Documents, with
  perform (org/management) and skip (account/child) branches stated in plain
  language. **Covers: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6.**
- **VC-7 (task references valid, dry-run first).** Every `mise run <name>` in
  the set matches a `[tasks.<name>]` in `mise.toml`; backend and foundation
  reference their named plan+apply tasks; Phase 0 references the four toolchain
  tasks; each dry-run task precedes its mutating sibling. **Covers:
  Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 8.3.**
- **VC-8 (scope).** The change set modifies only Markdown files. **Covers:
  Requirements 8.1, 8.2.**
- **VC-9 (plain language — editorial).** Human review that glossary terms are
  explained at first use, each step states action + expected result, decisions
  are posed as questions with per-answer actions, and procedures are ordered
  lists. **Covers: Requirements 6.1, 6.2, 6.3, 6.4.**

## Requirement-to-design mapping

| Requirement | Design element that satisfies it |
| --- | --- |
| **R1 — single ordered path from the root** | Root_README outline (Component 2): overview + org/account before the list (1.5), ordered 0→6 table linking each stack's Step_Document (1.1, 1.2), Phase 0 carried in-README (1.3), teardown link (1.4) |
| **R2 — one consolidated Step_Document per stack** | File inventory (six `*/README.md`, one per stack, in-folder — 2.1, 2.5) merging prior README+RUNBOOK+teardown (2.2); Step_Document template concept→run (2.3) stated once (2.4) with teardown as a pointer only (2.6) |
| **R3 — single dedicated Teardown_Document** | `TEARDOWN.md` at repo root (3.1), linked from README (3.3), reverse-order sections (3.2), governance/governance-shared marked org-only (3.4), sole owner of detailed steps (3.5) |
| **R4 — org-vs-account Decision_Checkpoint** | Decision_Checkpoint summary before governance links in README (4.1); full checkpoint opens governance-shared and governance Step_Documents (4.2, 4.3) with perform (4.4) / skip (4.5) branches and the plain-language management-vs-child condition (4.6) |
| **R5 — commands reference real mise task names** | Template "How to run" uses `mise run <task>` (5.1) with dry-run first (5.3); task names verified against `mise.toml` (5.2); backend plan+bootstrap (5.4), foundation plan+apply (5.5), Phase 0 install/setup/aws-login/verify (5.6) |
| **R6 — plain language for a non-expert** | Step_Document + Root_README templates: "What it is" plain-language concept and glossary terms at first use (6.1), action+expected-result phrasing (6.2), Decision_Checkpoint as question-with-answers (6.3), ordered "How to run" lists (6.4) |
| **R7 — explicit order reconciliation** | Ordered flow places governance before subscription (7.1); order-reconciliation note placed beside the step table (7.2, 7.3) |
| **R8 — documentation-only scope** | Inventory is all Markdown, no code/config touched (8.1, 8.2); task bodies stay in `mise.toml`, docs reference them so described behavior matches the repo (8.3); VC-8 enforces the scope |
