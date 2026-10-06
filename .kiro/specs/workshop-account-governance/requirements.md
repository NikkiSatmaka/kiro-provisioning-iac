# Requirements Document

## Introduction

This feature adds a new, standalone, **management-account-scoped** OpenTofu/Terraform
stack — the **Governance stack** — at a new top-level `governance/` directory,
mirroring the conventions of the existing `foundation/`, `subscription/`, and
`claim-service/` stacks. Its purpose is to govern workshop AWS accounts that are
billed through the AWS Organizations management account but funded and scoped per
workshop.

Workshop accounts are created and invited into the organization **externally**;
this stack never creates or invites accounts. For a set of accounts already in the
organization, the Governance stack, per workshop:

1. creates one Organizational Unit (OU) for the workshop,
2. places that workshop's pre-existing accounts into the OU,
3. attaches a Kiro-only guardrail Service Control Policy (SCP) to the OU, and
4. attaches a per-account budget whose breach automatically attaches a deny-all
   freeze SCP to the breaching account, so users can no longer operate it.

Account recovery (un-freeze) is a **documented manual** console/CLI detach in the
runbook; the stack provides no recovery automation. The stack runs with
management-account or delegated Organizations-admin credentials, which differ from
the member-account profile the other stacks use. It reuses the shared S3 state
backend under a workshop-namespaced key.

**Scope:** This spec adds ONLY the `governance/` stack (`governance/terraform/`),
its `mise` tasks, its `backend/` bootstrap wiring, and its README/runbook. It makes
no changes to the resources owned by the foundation, subscription, or claim-service
stacks.

**Verification constraint:** This is a planning/IaC-authoring exercise. Verification
is performed with `tofu validate`, `tofu fmt`, and `tofu plan` only. Applying this
stack mutates the live AWS Organizations management account (high blast radius) and
is not performed without the operator's explicit go-ahead.

## Glossary

- **Governance_stack**: The new standalone, management-account-scoped OpenTofu stack
  at `governance/terraform/` that creates OUs, places accounts, and attaches
  guardrail/freeze SCPs and per-account budgets.
- **Management_account**: The AWS Organizations management (payer) account, or a
  delegated Organizations administrator account, under whose credentials the
  Governance_stack runs.
- **Workshop_account**: An AWS account already created and invited into the
  organization externally, identified by a 12-digit account ID.
- **Workshop_ID**: The per-workshop slug that scopes an OU, its accounts, and the
  state key. Matches the slug regex `^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$` with no
  consecutive hyphens.
- **Workshop_OU**: The AWS Organizations Organizational Unit created by the
  Governance_stack for a single Workshop_ID. One OU per Workshop_ID; an OU may hold
  multiple Workshop_accounts.
- **Kiro_guardrail_SCP**: An `aws_organizations_policy` of type `SERVICE_CONTROL_POLICY`
  that permits only a conservative Kiro/IdC allowlist of actions, attached to the
  Workshop_OU.
- **Freeze_SCP**: A separate `aws_organizations_policy` of type
  `SERVICE_CONTROL_POLICY` that denies all actions. Created by the stack but NOT
  attached at apply time; attached to a Workshop_account automatically on budget
  breach.
- **Budget_action**: An `aws_budgets_budget_action` with `action_type = SCP`,
  `approval_model = AUTOMATIC`, that attaches the Freeze_SCP to a breaching
  Workshop_account.
- **Budgets_execution_role**: An IAM role trusted by `budgets.amazonaws.com`, with a
  confused-deputy guard on `aws:SourceAccount`, whose permissions are scoped to the
  Organizations attach/detach of the Freeze_SCP on Workshop_accounts.
- **Notification_emails**: The required list of email addresses subscribed to budget
  notifications. Supplied via `var.notification_emails`.
- **Notify_threshold_percent**: An optional softer notify-only budget threshold,
  supplied via `var.notify_threshold_percent`.
- **Kiro_allowed_actions**: The configurable allowlist of IAM actions permitted by
  the Kiro_guardrail_SCP, supplied via `var.kiro_allowed_actions`, with a
  conservative starter default.
- **Operator**: The person running the stack via `mise run` tasks or raw `tofu`,
  using Management_account credentials.
- **Shared state backend**: The S3 bucket + DynamoDB lock table created by the
  `backend` stack. Each consuming stack uses a value-free, tracked `backend.tf`
  (`backend "s3" {}`) plus a git-ignored, keyless `backend.hcl`, with the state key
  supplied at `tofu init` time.
- **Governance state key**: The S3 object key for this stack's state, namespaced per
  workshop as `workshops/<WORKSHOP_ID>/governance/terraform.tfstate`.
- **All-features precondition**: AWS Organizations configured in "all features" mode
  with the `SERVICE_CONTROL_POLICY` policy type enabled on the organization root. A
  precondition enforced by AWS, not by this stack.

## Requirements

### Requirement 1: Operate only on pre-existing, in-org accounts

**User Story:** As an operator, I want the stack to act only on accounts already in
the organization, so that account creation and invitation stay an external concern.

#### Acceptance Criteria

1. THE Governance_stack SHALL accept Workshop_account identifiers as inputs and
   SHALL NOT create or invite AWS accounts.
2. THE Governance_stack SHALL accept each Workshop_account identifier as a 12-digit
   string.
3. IF a supplied Workshop_account identifier is not a 12-digit string, THEN THE
   Governance_stack SHALL fail validation with a message that names the invalid
   input.
4. THE Governance_stack SHALL operate only on Workshop_accounts that are already
   members of the organization.

### Requirement 2: Create one Organizational Unit per workshop

**User Story:** As an operator, I want one OU created per workshop, so that a
workshop's accounts share a single governance boundary.

#### Acceptance Criteria

1. THE Governance_stack SHALL create exactly one Workshop_OU per Workshop_ID.
2. THE Governance_stack SHALL name the Workshop_OU from the Workshop_ID.
3. WHERE a Workshop_ID has multiple Workshop_accounts, THE Governance_stack SHALL
   create a single Workshop_OU that holds all of those Workshop_accounts.
4. THE Governance_stack SHALL create the Workshop_OU under the organization root.

### Requirement 3: Place the workshop's accounts into its OU

**User Story:** As an operator, I want the workshop's pre-existing accounts placed
into the workshop OU, so that the OU-level guardrail applies to them.

#### Acceptance Criteria

1. THE Governance_stack SHALL place each supplied Workshop_account into the
   Workshop_OU for its Workshop_ID.
2. WHEN multiple Workshop_accounts are supplied for a Workshop_ID, THE
   Governance_stack SHALL place every supplied Workshop_account into the same
   Workshop_OU.
3. THE Governance_stack SHALL NOT move accounts that were not supplied as inputs for
   the Workshop_ID.

### Requirement 4: Attach a Kiro-only guardrail SCP to the OU

**User Story:** As an operator, I want a Kiro-only guardrail SCP attached to the
workshop OU, so that accounts in the OU are limited to the Kiro-relevant actions.

#### Acceptance Criteria

1. THE Governance_stack SHALL create a Kiro_guardrail_SCP as an
   `aws_organizations_policy` of type `SERVICE_CONTROL_POLICY`.
2. THE Governance_stack SHALL attach the Kiro_guardrail_SCP to the Workshop_OU.
3. THE Governance_stack SHALL permit the actions listed in
   `var.kiro_allowed_actions` through the Kiro_guardrail_SCP.
4. WHEN `var.kiro_allowed_actions` is not supplied, THE Governance_stack SHALL use a
   conservative starter allowlist default that permits Kiro and IAM Identity Center
   sign-in plus read-only basics.
5. THE Governance_stack documentation SHALL describe the `var.kiro_allowed_actions`
   default as a tunable starting point.

### Requirement 5: Create the deny-all freeze SCP without attaching it

**User Story:** As an operator, I want a deny-all freeze SCP created but left
unattached, so that it exists ready for a budget breach to attach it to a single
account.

#### Acceptance Criteria

1. THE Governance_stack SHALL create a Freeze_SCP as an `aws_organizations_policy`
   of type `SERVICE_CONTROL_POLICY` that denies all actions.
2. THE Governance_stack SHALL create the Freeze_SCP as a resource separate from the
   Kiro_guardrail_SCP.
3. THE Governance_stack SHALL NOT attach the Freeze_SCP to any account or OU at
   apply time.

### Requirement 6: Budgets execution role with a confused-deputy guard

**User Story:** As an operator, I want a least-privilege execution role for AWS
Budgets, so that budget actions can attach the freeze SCP without over-granting
permissions.

#### Acceptance Criteria

1. THE Governance_stack SHALL create a Budgets_execution_role trusted by the
   `budgets.amazonaws.com` service principal.
2. THE Governance_stack SHALL constrain the Budgets_execution_role trust policy with
   an `aws:SourceAccount` condition equal to the Management_account identifier.
3. THE Governance_stack SHALL scope the Budgets_execution_role permissions to the
   AWS Organizations attach and detach actions on the Freeze_SCP and the
   Workshop_accounts.
4. THE Governance_stack SHALL NOT grant the Budgets_execution_role permissions
   beyond those required to attach and detach the Freeze_SCP on Workshop_accounts.

### Requirement 7: Per-account budget with an automatic SCP freeze action

**User Story:** As an operator, I want each workshop account to carry a budget whose
breach automatically freezes that account, so that cost overruns stop usage without
manual intervention.

#### Acceptance Criteria

1. THE Governance_stack SHALL create one budget per Workshop_account.
2. THE Governance_stack SHALL attach a Budget_action to each per-account budget with
   `action_type = SCP` and `approval_model = AUTOMATIC`.
3. WHEN a Workshop_account breaches its budget threshold, THE Budget_action SHALL
   attach the Freeze_SCP to that Workshop_account.
4. THE Governance_stack SHALL target the Budget_action at the breaching
   Workshop_account identifier rather than at the Workshop_OU.
5. WHEN a Workshop_account breaches its budget threshold, THE Budget_action SHALL
   use the Budgets_execution_role to attach the Freeze_SCP.

### Requirement 8: Required notification emails and optional notify threshold

**User Story:** As an operator, I want budget notifications sent to required
recipients, so that a breach is never silent.

#### Acceptance Criteria

1. THE Governance_stack SHALL require `var.notification_emails` with no default
   value.
2. IF `var.notification_emails` is an empty list, THEN THE Governance_stack SHALL
   fail validation and apply nothing.
3. THE Governance_stack SHALL subscribe every address in `var.notification_emails`
   as a notify-only recipient on each per-account budget.
4. WHERE `var.notify_threshold_percent` is supplied, THE Governance_stack SHALL add
   a notify-only budget threshold at that percentage.
5. WHEN `var.notify_threshold_percent` is not supplied, THE Governance_stack SHALL
   create no additional notify-only threshold.

### Requirement 9: Workshop-namespaced shared state backend

**User Story:** As an operator, I want this stack to store its state in the shared S3
backend under a workshop-namespaced key, so that each workshop's governance state
stays isolated.

#### Acceptance Criteria

1. THE Governance_stack SHALL use the shared S3 state backend created by the
   backend_stack.
2. THE Governance_stack SHALL declare a tracked, value-free `backend "s3" {}` block
   and supply account-specific values through a git-ignored, keyless `backend.hcl`
   at `tofu init` time.
3. THE Governance_stack SHALL use the Governance state key
   `workshops/<WORKSHOP_ID>/governance/terraform.tfstate`.
4. THE Governance_stack SHALL reuse the DynamoDB lock table created by the
   backend_stack.

### Requirement 10: Backend bootstrap extension

**User Story:** As an operator, I want the backend bootstrap to write this stack's
`backend.hcl`, so that it is wired the same way as the other stacks.

#### Acceptance Criteria

1. THE backend_stack SHALL emit a `backend_hcl_governance` output.
2. WHEN the backend bootstrap runs, THE backend_stack SHALL write the Governance_stack
   `backend.hcl` at `governance/terraform/backend.hcl`, consistent with how it writes
   the foundation, subscription, and claim-service `backend.hcl` files.
3. THE repository `.gitignore` SHALL ignore the Governance_stack `backend.hcl`.
4. THE repository `.gitignore` SHALL ignore the Governance_stack `*.tfvars` files.

### Requirement 11: Stack layout and Terraform file conventions

**User Story:** As a maintainer, I want the governance stack to mirror the existing
stacks' file layout and provider conventions, so that it is consistent and
predictable.

#### Acceptance Criteria

1. THE Governance_stack SHALL be an independent top-level `governance/` directory
   containing `README.md`, `RUNBOOK.md`, and a `terraform/` subdirectory.
2. THE Governance_stack `versions.tf` SHALL set `required_version >= 1.6` and require
   `hashicorp/aws >= 5.56.0`.
3. THE Governance_stack SHALL NOT declare the `hashicorp/awscc` provider.
4. THE Governance_stack `providers.tf` SHALL resolve the region from `var.aws_region`
   using a `!= "" ? var.aws_region : null` fallback to the environment.
5. THE Governance_stack `providers.tf` SHALL resolve the profile from
   `var.aws_profile` using a `!= "" ? var.aws_profile : null` fallback to the
   environment.
6. THE Governance_stack `providers.tf` SHALL set `default_tags` on the AWS provider
   and declare a `data "aws_region" "current"` source.
7. THE Governance_stack SHALL provide `versions.tf`, `providers.tf`, `backend.tf`,
   `backend.hcl.example`, `variables.tf`, `outputs.tf`, and resource files under
   `terraform/`.
8. THE Governance_stack `backend.tf` SHALL be tracked and declare a value-free
   `backend "s3" {}` block.

### Requirement 12: mise tasks for the governance lifecycle

**User Story:** As an operator, I want `mise run` tasks for planning, applying, and
destroying the governance stack, so that the workflow mirrors the other stacks'
conventions.

#### Acceptance Criteria

1. THE repository SHALL provide a `governance-plan` task that runs
   `tofu init -reconfigure` with the Governance state key and `tofu plan`, and
   changes no AWS resources.
2. THE repository SHALL provide a `governance-apply` task that runs `tofu apply`
   behind a guard and prompts for approval before mutating AWS resources.
3. THE repository SHALL provide a `governance-destroy` task that requires the
   operator to type a fixed confirmation phrase, mirroring `foundation-destroy`.
4. IF the typed confirmation phrase for `governance-destroy` does not match the
   fixed phrase, THEN THE task SHALL stop with a non-zero exit and delete nothing.
5. WHEN the typed confirmation phrase for `governance-destroy` matches the fixed
   phrase, THE task SHALL still require the operator to approve `tofu`'s own
   apply/destroy prompt before deleting anything.

### Requirement 13: WORKSHOP_ID guard and init-time key

**User Story:** As an operator, I want the WORKSHOP_ID validated and the state key
supplied at init time, so that each run targets exactly one well-formed workshop.

#### Acceptance Criteria

1. WHEN a governance task reads WORKSHOP_ID, THE task SHALL strip surrounding
   whitespace from the value.
2. IF the stripped WORKSHOP_ID does not match the slug regex
   `^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`, THEN THE governance task SHALL stop with a
   non-zero exit and change nothing.
3. IF the stripped WORKSHOP_ID contains consecutive hyphens, THEN THE governance task
   SHALL stop with a non-zero exit and change nothing.
4. IF `backend.hcl` is missing when a governance task runs, THEN THE task SHALL stop
   with a non-zero exit and a message that names the missing file.
5. IF `backend.hcl` contains a `key` entry when a governance task runs, THEN THE task
   SHALL stop with a non-zero exit and a message that the `key` is supplied at init
   time.
6. WHEN a governance task runs `tofu init`, THE task SHALL supply the Governance state
   key through `tofu init -reconfigure -backend-config="key=workshops/<WORKSHOP_ID>/governance/terraform.tfstate"`.

### Requirement 14: Documented platform preconditions

**User Story:** As an operator, I want the organization-level and credential
preconditions documented, so that an apply failure caused by a missing precondition
is understandable.

#### Acceptance Criteria

1. THE Governance_stack documentation SHALL state that AWS Organizations must be in
   "all features" mode with the `SERVICE_CONTROL_POLICY` policy type enabled on the
   organization root as a Step 0 the stack cannot perform.
2. THE Governance_stack documentation SHALL state that the stack must run with
   Management_account or delegated Organizations-admin credentials, which differ from
   the member-account profile used by the other stacks.
3. THE Governance_stack SHALL parameterize the credential profile through
   `var.aws_profile`.
4. IF the all-features or SCP-type precondition is not met, THEN the apply SHALL fail
   with an Organizations authorization or policy-type error, and THE Governance_stack
   documentation SHALL identify that error as the missing precondition.

### Requirement 15: Documented manual un-freeze recovery

**User Story:** As an operator, I want recovery from a freeze documented as a manual
step, so that I know the stack does not and will not auto-recover a frozen account.

#### Acceptance Criteria

1. THE Governance_stack documentation SHALL describe un-freezing a Workshop_account as
   a manual console or CLI detach of the Freeze_SCP in the RUNBOOK.
2. THE Governance_stack SHALL NOT provide a `governance-unfreeze` task.
3. THE Governance_stack SHALL NOT automate detachment of the Freeze_SCP for account
   recovery.

### Requirement 16: Verification without applying to the live organization

**User Story:** As a maintainer, I want verification limited to non-mutating tofu
commands, so that authoring this stack never touches the live management account
without explicit approval.

#### Acceptance Criteria

1. THE Governance_stack SHALL be verifiable with `tofu validate`, `tofu fmt`, and
   `tofu plan` only.
2. THE Governance_stack documentation SHALL state that applying mutates the live AWS
   Organizations management account and carries a high blast radius.
3. THE Governance_stack SHALL NOT be applied without the operator's explicit
   go-ahead.
