# Requirements Document

## Introduction

This feature restructures the run/provisioning documentation for the
`kiro-provisioning-iac` repository so that a non-expert operator — the weakest
member of a team who still has to provision this — can follow it top to bottom
without getting lost. The work is **documentation only**: every change is to
Markdown files, and no application, OpenTofu, or Python code changes.

Two principles drive the restructure:

1. **Maximum readability for a non-expert.** Plain language, one clear ordered
   path, and an early "do I even need this?" decision point so an operator never
   runs management-account-only steps by mistake.
2. **DRY — each thing documented exactly once.** Today the same run and teardown
   detail is spread across a root `README.md`, per-stack `README.md` /
   `RUNBOOK.md`, and `TEARDOWN.md` files. The restructure consolidates each
   stack into a single step document, collects all teardown into one dedicated
   document, and reduces the root README to an overview that links out instead
   of inlining command detail.

The restructured documentation set targets this operator-facing run order
(Phase 0 through Step 6):

- **0. Setup** — repo toolchain, AWS sign-in, environment config.
- **1. Backend** — prepare the shared S3 remote-state backend for the AWS
  account in use (the control plane; management or member).
- **2. Foundation** — adopt the IAM Identity Center instance.
- **3. Governance-shared** — management-account singleton primitives (only in
  organization mode).
- **4. Governance** — per-workshop OU, guardrail, and budgets (only in
  organization mode).
- **5. Subscription** — create the Identity Center users, groups, memberships,
  and the console-only Kiro steps.
- **6. Claim-service** — optional self-serve credential distribution.

### Order reconciliation (must be called out in the docs)

The operator-specified order above places the **governance** track (steps 3–4)
**before subscription** (step 5). The current `README.md` runs **subscription
before** the governance track and presents governance as an optional sidebar
that is "not part of the linear Phase 0→4 flow." The restructured documentation
MUST adopt the operator-specified order (0→6, governance before subscription)
and MUST explicitly explain this change so a reader coming from the old README
understands why the order differs. This reconciliation is a first-class
documentation requirement, captured in Requirement 7.

## Glossary

- **Operator**: The person running the provisioning steps, assumed to be a
  non-expert who follows the documentation literally.
- **Documentation_Set**: The complete collection of restructured Markdown
  files produced by this feature — the root README, the per-stack consolidated
  step documents, and the single teardown document. The Root_README is a member
  of the Documentation_Set.
- **Root_README**: The repository root `README.md`. After the restructure it is
  an overview-and-navigation document that links to the step documents rather
  than inlining per-step command detail.
- **Step_Document**: A single consolidated Markdown document living inside a
  stack folder (`backend/`, `foundation/`, `governance-shared/`, `governance/`,
  `subscription/`, `claim-service/`) that merges that stack's prior
  `README.md`, `RUNBOOK.md`, and any teardown content into one document that
  reads top to bottom: what the stack is, then how to run it.
- **Teardown_Document**: The single dedicated Markdown document, linked from the
  Root_README, that collects every stack's teardown steps in reverse
  provisioning order.
- **Decision_Checkpoint**: A plain-language "Do I need this?" check that
  distinguishes organization/management mode from account/child mode and tells
  the operator whether to perform or skip the governance steps.
- **Organization_Mode**: Running against the AWS Organizations management
  account using its IAM Identity Center organization instance. The governance
  and governance-shared steps apply.
- **Account_Mode**: Running against a child/member account using that account's
  own IAM Identity Center account instance. The governance and
  governance-shared steps are skipped.
- **Mise_Task**: A named task defined in `mise.toml` and invoked as
  `mise run <task-name>` (for example `mise run backend-bootstrap`).
- **Phase_0_Prep**: The setup steps that precede any stack: installing the
  toolchain with mise, signing in to AWS, and preparing the `.env` environment
  file.

## Requirements

### Requirement 1: Single ordered path from the root

**User Story:** As an operator, I want one clearly ordered path starting at the
repository root, so that I can provision from start to finish without deciding
which document to read next.

#### Acceptance Criteria

1. THE Root_README SHALL present the provisioning flow as a single ordered
   sequence covering Phase_0_Prep followed by steps 1 through 6 in this order:
   backend, foundation, governance-shared, governance, subscription,
   claim-service.
2. WHERE a step corresponds to a stack, THE Root_README SHALL link to that
   stack's Step_Document rather than inlining that stack's run commands.
3. THE Root_README SHALL contain the Phase_0_Prep instructions (installing the
   toolchain with mise, signing in to AWS, and preparing the `.env` file)
   directly, because Phase_0_Prep is not owned by any single stack.
4. THE Root_README SHALL link to the Teardown_Document for all teardown
   instructions.
5. THE Root_README SHALL state the overview of what the repository provisions
   and the organization-versus-account distinction before the ordered step
   list.

### Requirement 2: One consolidated step document per stack

**User Story:** As an operator, I want each stack to have exactly one document
that tells me what it is and how to run it, so that I never have to cross-read a
separate README, RUNBOOK, and teardown file for the same stack.

#### Acceptance Criteria

1. THE Documentation_Set SHALL provide exactly one Step_Document for each of the
   six stacks: backend, foundation, governance-shared, governance, subscription,
   and claim-service.
2. Each Step_Document SHALL merge the content of that stack's prior `README.md`,
   `RUNBOOK.md`, and any teardown content into a single document.
3. Each Step_Document SHALL be ordered to read top to bottom from a concept
   section ("what it is") to a run section ("how to run it").
4. WHERE the same fact, command, or explanation appears in more than one of a
   stack's prior documents, THE Step_Document SHALL state that fact, command, or
   explanation exactly once.
5. Each Step_Document SHALL reside inside its own stack folder.
6. WHERE a Step_Document covers teardown, THE Step_Document SHALL limit that
   coverage to a short pointer to the Teardown_Document, SHALL NOT restate any
   detailed teardown step, and SHALL have every detailed teardown step relocated
   to the Teardown_Document, so that teardown detail lives in exactly one place.

### Requirement 3: Single dedicated teardown document

**User Story:** As an operator, I want one teardown document that lists every
removal step in reverse order, so that I can tear everything down correctly
without hunting through each stack's folder.

#### Acceptance Criteria

1. THE Documentation_Set SHALL provide exactly one Teardown_Document.
2. THE Teardown_Document SHALL present the teardown steps for every stack in the
   reverse of the provisioning order defined in Requirement 1.
3. THE Teardown_Document SHALL be linked from the Root_README.
4. WHERE a teardown step applies only in Organization_Mode, THE
   Teardown_Document SHALL mark that step with the Decision_Checkpoint guidance
   so an Account_Mode operator skips it.
5. THE Teardown_Document SHALL be the only document in the Documentation_Set
   that states the detailed teardown steps.

### Requirement 4: Organization-versus-account decision checkpoint

**User Story:** As an operator, I want an early plain-language check that tells
me whether the governance steps apply to me, so that I do not attempt
management-account-only steps from a child account or skip required steps by
mistake.

#### Acceptance Criteria

1. THE Root_README SHALL present the Decision_Checkpoint before the governance
   steps in the ordered flow.
2. THE Step_Document for governance-shared SHALL open with the
   Decision_Checkpoint.
3. THE Step_Document for governance SHALL open with the Decision_Checkpoint.
4. WHEN an operator is in Organization_Mode, THE Decision_Checkpoint SHALL
   instruct the operator to perform the governance-shared and governance steps.
5. WHEN an operator is in Account_Mode, THE Decision_Checkpoint SHALL instruct
   the operator to skip the governance-shared and governance steps.
6. THE Decision_Checkpoint SHALL state the condition in plain language that ties
   Organization_Mode to the AWS Organizations management account and
   Account_Mode to a child/member account.

### Requirement 5: Commands reference the real mise task names

**User Story:** As an operator, I want the documentation to point me at the
exact `mise run` task to invoke, so that I run the maintained task instead of
copying a command that may drift from the task runner.

#### Acceptance Criteria

1. WHERE a Step_Document instructs the operator to perform an action that a
   Mise_Task performs, THE Step_Document SHALL reference that action by its
   `mise run <task-name>` invocation.
2. Each Mise_Task name referenced in the Documentation_Set SHALL match a task
   name defined in `mise.toml`.
3. WHERE a stack provides a dry-run task and a mutating task for the same action,
   THE Step_Document SHALL present the dry-run task before the mutating task.
4. THE backend Step_Document SHALL reference `mise run backend-bootstrap-plan`
   and `mise run backend-bootstrap` for backend preparation.
5. THE foundation Step_Document SHALL reference `mise run foundation-plan` and
   `mise run foundation-apply`.
6. THE Phase_0_Prep section SHALL reference `mise install`, `mise run setup`,
   `mise run aws-login`, and `mise run verify`.

### Requirement 6: Plain language for a non-expert operator

**User Story:** As a non-expert operator, I want the documentation written in
plain language without unexplained jargon, so that I can understand and complete
each step without specialist knowledge.

#### Acceptance Criteria

1. THE Documentation_Set SHALL define each technical term from the Glossary in
   plain language at or before its first use in a given document.
2. THE Documentation_Set SHALL describe each step in terms of what the operator
   does and what result to expect.
3. WHERE a step requires a decision, THE Documentation_Set SHALL state the
   decision as a plain-language question with the available answers and the
   action for each answer.
4. THE Documentation_Set SHALL present the steps of each procedure as an ordered
   list that the operator follows from first to last.

### Requirement 7: Explicit order reconciliation

**User Story:** As an operator familiar with the previous README, I want the
documentation to explain that the governance steps now come before subscription,
so that I understand the order change and do not follow the old sequence.

#### Acceptance Criteria

1. THE Root_README SHALL order the governance-shared and governance steps before
   the subscription step.
2. THE Root_README SHALL contain a plain-language note explaining that this
   order places the governance steps before subscription, which differs from the
   previous documentation that ran subscription before governance.
3. THE order-reconciliation note SHALL appear where the ordered step list is
   presented so that a reader encounters the explanation alongside the order it
   describes.

### Requirement 8: Documentation-only scope

**User Story:** As a maintainer, I want this effort limited to documentation, so
that no runtime behavior changes while the docs are reorganized.

#### Acceptance Criteria

1. THE feature SHALL change only Markdown documentation files.
2. THE feature SHALL NOT change application code, OpenTofu configuration, Python
   scripts, or `mise.toml`.
3. WHERE the Documentation_Set describes a command or behavior, THE
   Documentation_Set SHALL verify that command or behavior against the
   repository's actual current tasks and code and SHALL correct the description
   when it does not match the repository's actual current tasks and code.
