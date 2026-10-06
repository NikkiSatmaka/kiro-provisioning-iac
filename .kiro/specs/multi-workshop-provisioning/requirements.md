# Requirements Document

> **⚠️ Superseded in part — management-account consolidation.** A later locked
> decision moves all stacks into the **management account**. Where this document
> assumes a member/child account, an `awscc_sso_instance`, or that account
> assignments always exist: foundation now **adopts (reads)** the organization
> IdC instance (no creation); subscription writes into that shared organization
> directory with **workshop-namespaced** group display names; and account access
> is gated behind `enable_account_access` (default **false** → zero permission
> sets, zero assignments, zero console access). The `workshop_accounts` account
> ids are billing/attribution metadata only. See
> `.agents/tasks/management-account-consolidation-plan.md` (authoritative).

## Introduction

This feature turns the Kiro provisioning IaC repository into a per-workshop
provisioning module. One long-lived AWS management account hosts a shared,
org-level IAM Identity Center (IdC) instance and serves many short-lived Kiro
workshops over time. Each workshop must be provisioned and torn down
independently, so that multiple workshops coexist in the same management account
at the same time without interfering with one another. For example, Workshop 1
(one child account, ten participants) and Workshop 2 (three child accounts, nine
participants, three per account) run concurrently in the same management account.

This spec builds on the in-flight `idc-region-account-mapping` spec and treats
that spec's changes as the baseline it extends. The region split
(`KIRO_REGION` for Kiro sign-in, `IDC_REGION` for resource deployment,
`AWS_REGION` tracking `IDC_REGION`), the hard rule that region is derived only
from the environment and never hardcoded, and the `Account_Id` flow
(provisioning manifest → `credentials.md` document header and per-user column →
claim-audit CSV, excluded from `otps.csv` and from the participant claim
response) all remain in force and are carried through the new account > groups >
users structure.

The feature encodes a set of settled decisions:

- The org-level IdC instance is a separate, standalone, long-lived concern that
  this module consumes as an interface rather than creating or destroying. Its
  instance ARN and identity store ID are operator-supplied inputs.
- Account assignments are owned by OpenTofu through permission sets and account
  assignments. The only remaining console/manual step is subscribing the created
  groups to Kiro (the tier).
- Input is an explicit nested map of accounts → groups → users in tfvars,
  replacing today's count/prefix generators. `locals.tf` flattens that map into
  the keyed users/groups/memberships maps the existing `for_each` resources
  already consume, without reworking those resources.
- State is workshop-keyed in the shared S3 backend. The `key` is removed from
  `backend.hcl` and supplied at init time from `WORKSHOP_ID`.
- Each workshop deploys its own claim service, with `workshop_id` threaded into
  resource names and the state key so concurrent workshops never collide.

### Dependency / assumption (out of scope)

Creating the org-level IdC foundation instance is explicitly out of scope for
this spec and will be addressed by its own future spec. This module assumes the
foundation IdC instance already exists, is managed separately (possibly not even
by OpenTofu), and is long-lived. This module consumes the foundation's identity
through operator-supplied inputs and never creates or destroys that instance.

## Glossary

- **System**: The kiro-provisioning-iac repository as a whole, including its
  OpenTofu/Terraform configurations, Python scripts, the claim-service Lambda,
  the mise task definitions, and the environment configuration that drives them.
- **Environment_Config**: The environment-variable layer that supplies
  configuration values, comprising `.env`, `.env.example`, and the mise
  configuration that sources them.
- **Foundation_Idc**: The long-lived, org-level IAM Identity Center instance
  hosted in the management account, managed outside this module and consumed by
  it as an interface. This module neither creates nor destroys the Foundation_Idc.
- **Idc_Instance_Arn**: The operator-supplied ARN of the Foundation_Idc instance.
- **Identity_Store_Id**: The operator-supplied identity store ID backing the
  Foundation_Idc instance.
- **Subscription_Terraform**: The OpenTofu/Terraform configuration under
  `subscription/terraform/` that provisions a workshop's users, groups,
  memberships, permission sets, and account assignments, and emits the
  Provisioning_Manifest.
- **Claim_Service_Terraform**: The OpenTofu/Terraform configuration under
  `claim-service/terraform/` that provisions a workshop's claim-service DynamoDB
  table, Lambda, Function URL, and IAM roles.
- **Workshop**: A single short-lived Kiro event, provisioned and torn down as an
  independent unit, comprising one or more child AWS accounts, the groups and
  users within them, and its own claim service.
- **Workshop_Id**: An operator-chosen slug that namespaces a single Workshop
  across its state keys and resource names (e.g. `kiro-2025-10-10`). Supplied via
  the `WORKSHOP_ID` environment variable and threaded to OpenTofu as
  `TF_VAR_workshop_id`. Distinct from Workshop_Code.
- **Workshop_Code**: The shared gate secret a participant submits with a claim,
  which gates the public claim Function URL in the Claim_Handler. Distinct from
  Workshop_Id. Supplied via the `WORKSHOP_CODE` environment variable and threaded
  to OpenTofu as `TF_VAR_workshop_code`.
- **Workshop_Accounts**: The operator-supplied nested-map Terraform variable in
  Subscription_Terraform describing a Workshop's child accounts, the groups in
  each account, and the user count of each group.
- **Child_Account**: A child AWS account within a Workshop, identified by a
  12-digit Account_Id, that holds one or more Groups.
- **Group**: A named IdC group within a Child_Account whose member Participants
  share that Child_Account's access.
- **Participant**: An IdC user who belongs to a Group, receives Kiro access, and
  may share a Child_Account with other Participants.
- **Account_Id**: A 12-digit child AWS account ID associated with a Child_Account.
- **Permission_Set**: An IdC permission set that, through an account assignment,
  grants a Group access to its Child_Account.
- **Account_Assignment**: An `aws_ssoadmin_account_assignment` resource that
  binds a Group to a Permission_Set within a Child_Account.
- **Shared_State_Backend**: The shared S3 state bucket (`kiro-tofu-state-<account_id>`)
  and DynamoDB lock table (`kiro-tofu-locks`) created by the `backend/` stack and
  reused by every Workshop.
- **State_Key**: The S3 object key that isolates one Workshop's state within the
  Shared_State_Backend, of the form `workshops/<workshop_id>/subscription/terraform.tfstate`
  or `workshops/<workshop_id>/claim-service/terraform.tfstate`.
- **Backend_Config**: The `backend.hcl` file for a stack, holding only shared,
  non-secret backend values (bucket, region, lock table) after the `key` is
  removed.
- **Mise_Tasks**: The mise task definitions in `mise.toml` for provision,
  teardown, claim deploy/destroy, seed, and audit operations.
- **Provisioning_Manifest**: The `provisioning_manifest` OpenTofu output,
  exported to `manifest.json`, that carries everything the scripts consume
  (region, identity store id, sign-in URL, users with Account_Id, groups,
  memberships).
- **Credentials_Document**: The operator-facing Markdown file rendered by
  `subscription/scripts/provision_passwords_and_output.py` to `credentials.md`.
- **Otps_Csv**: The `otps.csv` file (header `username,otp`) that maps a username
  to a one-time password.
- **Audit_Export**: The claim-audit CSV written by
  `claim-service/scripts/export_audit.py` to `claim-service/output/`.
- **Claim_Handler**: The claim-service Lambda handler
  (`claim-service/lambda/claim_handler.py`).
- **Claim_Response**: The JSON success body the Claim_Handler returns to a
  claiming Participant.
- **Seed_Script**: `claim-service/scripts/seed_claim_pool.py`, which seeds a
  Workshop's claim-service DynamoDB table from that Workshop's outputs.

## Requirements

### Requirement 1: Consume the Foundation IdC instead of creating it

**User Story:** As an operator, I want the per-workshop module to consume the long-lived org-level IdC instead of creating it, so that provisioning and tearing down a workshop never creates or destroys the shared Foundation_Idc.

#### Acceptance Criteria

1. THE Subscription_Terraform SHALL NOT create the Foundation_Idc instance.
2. THE Subscription_Terraform SHALL NOT destroy the Foundation_Idc instance.
3. THE Subscription_Terraform SHALL define an Idc_Instance_Arn variable, suppliable only through a tfvars file or the TF_VAR environment variable, that accepts the ARN of the Foundation_Idc instance.
4. THE Subscription_Terraform SHALL define an Identity_Store_Id variable, suppliable only through a tfvars file or the TF_VAR environment variable, that accepts the identity store ID of the Foundation_Idc instance.
5. THE Subscription_Terraform SHALL create its users, groups, memberships, and Account_Assignments against the Identity_Store_Id and Idc_Instance_Arn supplied through those variables.
6. THE Subscription_Terraform SHALL resolve the Idc_Instance_Arn and Identity_Store_Id values only from the Idc_Instance_Arn and Identity_Store_Id variables, without any data-source discovery and without any remote-state lookup.
7. IF the Idc_Instance_Arn or Identity_Store_Id variable is empty or not supplied, THEN THE Subscription_Terraform SHALL halt before creating any users, groups, memberships, or Account_Assignments and SHALL return an error indicating which required variable is missing.

### Requirement 2: OpenTofu-owned permission sets and account assignments

**User Story:** As an operator, I want each group assigned to its child account declaratively through OpenTofu, so that the only remaining manual step is subscribing the created groups to Kiro.

#### Acceptance Criteria

1. THE Subscription_Terraform SHALL create one Permission_Set that grants a Group access to its Child_Account.
2. WHEN a Group is defined under a Child_Account in the Workshop_Accounts input, THE Subscription_Terraform SHALL create exactly one Account_Assignment that binds that Group to that Child_Account's Account_Id through a Permission_Set.
3. WHERE one Child_Account holds more than one Group, THE Subscription_Terraform SHALL create one Account_Assignment per Group, each binding its Group to that Child_Account's Account_Id, so that the number of Account_Assignments for that Child_Account equals its Group count.
4. WHILE an Account_Assignment binding a Group to its Child_Account exists, THE Subscription_Terraform SHALL grant every Participant of that Group the same Child_Account access defined by the bound Permission_Set.
5. IF a Group in the Workshop_Accounts input references a Child_Account whose Account_Id is absent, empty, or not a 12-digit AWS account identifier, THEN THE Subscription_Terraform SHALL halt the apply without creating any Account_Assignment for that Group and return an error indicating the Child_Account identifier is missing or invalid.
6. THE Subscription_Terraform SHALL provision the Permission_Sets and Account_Assignments for all Groups such that subscribing the created Groups to Kiro is the only remaining console/manual step, with no other post-apply manual action required to grant Child_Account access.

### Requirement 3: Explicit nested account > groups > users map input

**User Story:** As an operator, I want to declare a workshop's accounts, groups, and user counts as one explicit nested map, so that the structure is explicit in tfvars instead of produced by count and prefix generators.

#### Acceptance Criteria

1. THE Subscription_Terraform SHALL define the Workshop_Accounts variable as a map keyed by Account_Id, where each value holds a map of Groups keyed by group name, and each Group holds a user count.
2. IF a Group's user count in the Workshop_Accounts input is outside the inclusive range 0 to 500, THEN THE Subscription_Terraform SHALL reject the input with a validation error.
3. THE Subscription_Terraform SHALL remove the `user_count`, `group_count`, `user_prefix`, `group_prefix`, `sequence_start`, `sequence_padding`, and `membership_strategy` variables, such that any reference to them fails to resolve.
4. THE Subscription_Terraform SHALL flatten the Workshop_Accounts input into the keyed users, groups, and memberships maps consumed by the existing `aws_identitystore_user`, `aws_identitystore_group`, and `aws_identitystore_group_membership` `for_each` resources, producing the same value shapes those resources require today.
5. THE Subscription_Terraform SHALL preserve the existing `aws_identitystore_user`, `aws_identitystore_group`, and `aws_identitystore_group_membership` resources without reworking them.
6. WHEN the Workshop_Accounts input defines a Group with a user count of N, THE Subscription_Terraform SHALL create exactly N Participants and exactly N memberships placing those Participants in that Group.
7. THE Subscription_Terraform SHALL derive the flattened users, groups, and memberships map keys deterministically from the Account_Id, group name, and per-group user index, so that the keys are byte-identical on re-run and a change to one Workshop_Accounts entry leaves the keys of unrelated entries unchanged.
8. IF an Account_Id key in the Workshop_Accounts input is not a 12-digit numeric string, THEN THE Subscription_Terraform SHALL reject the input with a validation error.
9. IF a group name in the Workshop_Accounts input is empty, THEN THE Subscription_Terraform SHALL reject the input with a validation error.

### Requirement 4: Per-user account_id resolved through the nesting

**User Story:** As an operator, I want each participant's account ID resolved from the account that owns the participant's group, so that the Account_Id flow from the baseline spec continues to work under the nested structure.

#### Acceptance Criteria

1. WHEN a Participant belongs to exactly one Group that is owned by exactly one Child_Account, THE Subscription_Terraform SHALL resolve that Participant's Account_Id to the Account_Id of that owning Child_Account.
2. IF a Participant belongs to a Group whose owning Child_Account cannot be resolved to exactly one Account_Id, THEN THE Subscription_Terraform SHALL halt provisioning without emitting the Provisioning_Manifest and SHALL produce an error indicating the Participant and Group whose Account_Id could not be resolved.
3. THE Subscription_Terraform SHALL include each Participant's resolved Account_Id in that Participant's entry within the Provisioning_Manifest.
4. THE Credentials_Document SHALL present each Participant's resolved Account_Id in that Participant's row exactly once.
5. WHEN a credential is claimed, THE Audit_Export SHALL populate the `account_id` column of that credential's row with the resolved Account_Id of the Participant associated with that credential.
6. THE Otps_Csv SHALL exclude every Participant's Account_Id from all columns and rows.
7. THE Claim_Response SHALL exclude the Account_Id from its payload.

### Requirement 5: Workshop-keyed state in the shared S3 backend

**User Story:** As an operator, I want each workshop's state stored under its own key in the shared S3 backend, so that concurrent workshops share one bucket and lock table without sharing state.

#### Acceptance Criteria

1. THE Subscription_Terraform and Claim_Service_Terraform SHALL store state in the Shared_State_Backend bucket `kiro-tofu-state-<account_id>` and lock table `kiro-tofu-locks`.
2. THE System SHALL store each Workshop's subscription state under the State_Key `workshops/<workshop_id>/subscription/terraform.tfstate`, where `<workshop_id>` is a non-empty identifier of 1 to 64 characters matching the pattern `[a-z0-9][a-z0-9-]*`.
3. THE System SHALL store each Workshop's claim-service state under the State_Key `workshops/<workshop_id>/claim-service/terraform.tfstate`, using the same `<workshop_id>` identifier as the Workshop's subscription State_Key.
4. THE Backend_Config SHALL omit the `key` setting.
5. THE Backend_Config SHALL retain only the shared, non-secret backend values: bucket, region, and lock table.
6. WHEN a mutating OpenTofu operation runs for a Workshop, THE System SHALL supply the State_Key at init time via `tofu init -reconfigure -backend-config=backend.hcl -backend-config="key=workshops/<workshop_id>/..."` before executing the operation.
7. THE System SHALL store the authoritative Workshop state in the Shared_State_Backend rather than on the operator's device.
8. IF the supplied `<workshop_id>` is absent or does not match the pattern `[a-z0-9][a-z0-9-]*` within 1 to 64 characters, THEN THE System SHALL halt before any mutating OpenTofu operation, leave all existing State_Keys unchanged, and return an error indicating the workshop identifier is missing or invalid.
9. IF the Backend_Config contains a `key` setting at init time, THEN THE System SHALL halt the OpenTofu init operation, leave all existing State_Keys unchanged, and return an error indicating that the `key` setting must be supplied only at init time and not in the Backend_Config.
10. WHILE two or more Workshops run mutating OpenTofu operations concurrently against the Shared_State_Backend, THE System SHALL isolate each Workshop's state at its own State_Key and acquire the lock in table `kiro-tofu-locks` per State_Key so that no Workshop reads or overwrites another Workshop's state.

### Requirement 6: WORKSHOP_ID-parameterized mise tasks

**User Story:** As an operator, I want the mise tasks to take a workshop ID and reconfigure the backend before every mutating operation, so that the local `.terraform` pointer always matches the intended workshop.

#### Acceptance Criteria

1. THE Mise_Tasks for provision, teardown, claim-deploy, claim-destroy, seed, and audit SHALL read the Workshop_Id from the `WORKSHOP_ID` environment variable, treating a value consisting only of whitespace as unset.
2. WHEN a provision, teardown, claim-deploy, or claim-destroy task runs with the `WORKSHOP_ID` environment variable set to a non-empty value, THE Mise_Tasks SHALL run `tofu init -reconfigure` using that Workshop's State_Key to completion before invoking the corresponding apply or destroy step.
3. IF the `tofu init -reconfigure` step for a provision, teardown, claim-deploy, or claim-destroy task exits with a non-zero status, THEN THE Mise_Tasks SHALL report an error indicating backend reconfiguration failed and SHALL NOT invoke the apply or destroy step.
4. WHEN a provision, teardown, claim-deploy, or claim-destroy task invokes OpenTofu, THE Mise_Tasks SHALL thread the Workshop_Id to OpenTofu via the `TF_VAR_workshop_id` environment variable, set to the value of `WORKSHOP_ID`.
5. WHEN the seed task runs, THE Seed_Script SHALL operate against only the Workshop identified by the Workshop_Id, reading that Workshop's outputs and its own claim table, and SHALL NOT read or modify any other Workshop's outputs or claim table.
6. WHEN the audit task runs, THE Audit_Export SHALL operate against only the Workshop identified by the Workshop_Id, reading that Workshop's outputs or its own claim table, and SHALL NOT read any other Workshop's outputs or claim table.
7. IF the `WORKSHOP_ID` environment variable is unset or consists only of whitespace when a provision, teardown, claim-deploy, claim-destroy, seed, or audit task runs, THEN THE Mise_Tasks SHALL report an error indicating that `WORKSHOP_ID` is required, SHALL exit with a non-zero status, and SHALL NOT run `tofu init -reconfigure`, apply, destroy, seed, or audit operations.

### Requirement 7: One claim service per workshop with namespaced resources

**User Story:** As an operator, I want each workshop to deploy its own claim service with workshop-namespaced resource names, so that concurrent workshops never collide on claim resources.

#### Acceptance Criteria

1. THE Claim_Service_Terraform SHALL deploy a DynamoDB table, a Lambda, a Function URL, and IAM roles for each Workshop.
2. THE Claim_Service_Terraform SHALL include the exact Workshop_Id as a substring of the DynamoDB table name, the Lambda function name, the Function URL's function name, and the IAM role and policy names.
3. WHEN two Workshops have differing Workshop_Ids, THE Claim_Service_Terraform SHALL produce distinct DynamoDB table names, Lambda function names, Function URLs, and IAM role and policy names for the two Workshops, sharing none of those names.
4. THE Claim_Service_Terraform SHALL isolate each Workshop's claim-service state under the claim-service State_Key for that Workshop_Id, so that neither Workshop's apply reads or overwrites the other's state.
5. WHEN two Workshops with differing Workshop_Ids are applied without either being destroyed first, THE Claim_Service_Terraform SHALL create both Workshops' claim resources with no shared resource name and no shared State_Key.
6. WHEN the seed or audit operation runs for a Workshop, THE Seed_Script and the Audit_Export SHALL derive the DynamoDB table name from that Workshop's Workshop_Id so that they target the same table the Claim_Service_Terraform created for that Workshop.
7. IF the seed or audit operation runs with a Workshop_Id for which no corresponding claim table exists, THEN the Seed_Script or Audit_Export SHALL report an error identifying the Workshop_Id and SHALL NOT read or modify any other Workshop's table.

### Requirement 8: Workshop_Id as a validated, operator-supplied slug

**User Story:** As an operator, I want to supply the workshop ID as a validated slug in `.env`, so that a malformed or colliding workshop ID is caught before it namespaces state and resources.

#### Acceptance Criteria

1. THE Environment_Config SHALL define a `WORKSHOP_ID` variable supplied by the operator in `.env`.
2. WHEN a provision task runs, THE System SHALL thread the Workshop_Id to OpenTofu via `TF_VAR_workshop_id`, mirroring the existing `TF_VAR_workshop_code` and `TF_VAR_kiro_region` pattern.
3. IF the Workshop_Id does not match the slug format of 1 to 63 lowercase alphanumeric characters and hyphens, beginning and ending with an alphanumeric character, with no consecutive hyphens, THEN THE System SHALL reject it with a validation error identifying the offending value and the expected slug format, and SHALL NOT create or modify any state or resources.
4. IF the Workshop_Id is empty or unset when a provision task runs, THEN THE System SHALL reject the task with a validation error indicating that a Workshop_Id is required, and SHALL NOT create or modify any state or resources.
5. WHEN a provision task runs with a Workshop_Id whose subscription State_Key already exists in the Shared_State_Backend, THE System SHALL report the collision to the operator with a warning identifying the conflicting Workshop_Id and State_Key before proceeding.
6. THE Subscription_Terraform and Claim_Service_Terraform SHALL accept the Workshop_Id, the Workshop_Accounts map, the Idc_Instance_Arn, and the Identity_Store_Id as variables, each of which SHALL be suppliable via tfvars.

### Requirement 9: Workshop_Code distinct from Workshop_Id

**User Story:** As an operator, I want the claim access-gate secret kept separate from the workshop namespace, so that the secret that gates the public claim URL is never conflated with the identifier that namespaces resources.

#### Acceptance Criteria

1. WHEN a claim request is submitted to the public claim Function URL in the Claim_Handler, THE Claim_Service_Terraform SHALL validate the submitted value against the Workshop_Code and SHALL grant access only when the submitted value exactly matches the Workshop_Code.
2. IF a claim request is submitted without a value matching the Workshop_Code, THEN THE Claim_Handler SHALL reject the request, return a response indicating access is denied, and make no change to claim state.
3. THE Claim_Service_Terraform SHALL use the Workshop_Id, and never the Workshop_Code, as the namespace prefix for resource names and as the State_Key.
4. THE System SHALL store the Workshop_Code and the Workshop_Id as two distinct values that coexist within one Workshop, such that the Workshop_Code is used only for access-gate validation and the Workshop_Id is used only for namespacing, and neither value substitutes for the other.
5. THE Environment_Config SHALL supply the Workshop_Code via the `WORKSHOP_CODE` variable (passed as `TF_VAR_workshop_code`) and the Workshop_Id via the `WORKSHOP_ID` variable (passed as `TF_VAR_workshop_id`) as two separate variables, each sourced independently.

### Requirement 10: Cross-workshop teardown isolation

**User Story:** As an operator, I want tearing down one workshop to leave every other workshop and the shared foundation untouched, so that destroying a finished workshop never disrupts a live one.

#### Acceptance Criteria

1. WHEN `tofu destroy` runs against a Workshop's subscription State_Key, THE System SHALL remove that Workshop's users, groups, memberships, Permission_Sets, and Account_Assignments.
2. WHEN `tofu destroy` runs against a Workshop's claim-service State_Key, THE System SHALL remove that Workshop's DynamoDB table, Lambda, Function URL, and IAM roles.
3. WHEN `tofu destroy` runs against a Workshop, THE System SHALL NOT remove the Foundation_Idc instance.
4. WHEN `tofu destroy` runs against a Workshop, THE System SHALL NOT remove the Shared_State_Backend bucket or lock table.
5. WHEN `tofu destroy` runs against one Workshop, THE System SHALL NOT remove any other Workshop's users, groups, memberships, Account_Assignments, or claim-service DynamoDB table, Lambda, Function URL, or IAM roles.
6. THE System SHALL provide a verification check that compares another Workshop's users, groups, Account_Assignments, and claim-service resources against a pre-destroy baseline, and IF the check detects any removal or modification of that other Workshop's resources, THEN THE System SHALL report a failure identifying the affected resources.
