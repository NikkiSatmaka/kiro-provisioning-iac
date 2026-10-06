# Requirements Document

> **⚠️ Superseded in part — management-account consolidation.** Requirements
> here that mandate *creating/owning* an account-level IdC instance (the
> `awscc_sso_instance` resource, the `instance_name` variable, the AWSCC tag
> shape, the member-account enablement toggle, importing/destroying the
> instance) no longer hold. A later locked decision makes `foundation/` run in
> the **management account** and **adopt (read)** the existing **organization**
> instance via `data "aws_ssoadmin_instances"`: it creates and owns nothing, so
> there is nothing to import or destroy and no `awscc`/`instance_name`. The
> enablement precondition is now simply "IAM Identity Center is enabled in the
> management account." The consumed outputs and the decoupling-via-variables
> boundary are unchanged. The authoritative current design is
> `.agents/tasks/management-account-consolidation-plan.md`.

## Introduction

This feature adds a dedicated, standalone OpenTofu/Terraform stack — the
**Foundation IdC service** — whose sole responsibility is to CREATE and OWN the
account-level IAM Identity Center (IdC) instance for this AWS account. It lives
at a new `foundation/terraform/` stack directory, mirroring the conventions of
the existing `backend/terraform`, `subscription/terraform`, and
`claim-service/terraform` stacks.

The Foundation IdC instance is a long-lived, shared resource reused across every
workshop. The recently-completed `multi-workshop-provisioning` work changed the
`subscription` stack to CONSUME this instance via two operator-supplied inputs
(`idc_instance_arn`, `identity_store_id`) rather than create it; the
`awscc_sso_instance` resource and the `awscc` provider were removed from the
subscription stack. This stack re-homes that creation responsibility into one
place.

The decoupling boundary established by the subscription stack is preserved: the
Foundation IdC service EMITS outputs (instance ARN, identity store id, region,
sign-in URL), and the operator copies/exports those values into the subscription
stack's inputs (e.g. via `TF_VAR_*` or tfvars). The Foundation IdC service does
NOT create users, groups, memberships, permission sets, or account assignments —
those remain in the subscription stack. The two stacks are wired together by the
operator through explicit variables, NOT by a remote-state reference.

**Scope:** This spec adds ONLY the foundation stack (`foundation/terraform/`),
its `mise` tasks, and its runbook/documentation. It makes NO changes to the
subscription stack, which keeps consuming the IdC instance through its existing
`var.idc_instance_arn` and `var.identity_store_id` inputs.

## Glossary

- **Foundation IdC service**: The new standalone OpenTofu stack at
  `foundation/terraform/` that creates and owns the account-level IdC instance.
- **IdC instance / IdC account instance**: An account-level instance of AWS IAM
  Identity Center, created in the account/region the provider targets. Created
  by the `awscc_sso_instance` resource (AWS Cloud Control, maps to the
  `AWS::SSO::Instance` type). Distinct from the AWS Organizations management
  account's organization instance. AWS permits one account instance per account
  across all regions.
- **Identity_Store_ID**: The identity store ID backing the IdC instance,
  formatted `d-xxxxxxxxxx`. Surfaced from `awscc_sso_instance.this.identity_store_id`.
- **Instance_ARN**: The ARN of the IdC instance, formatted
  `arn:aws:sso:::instance/ssoins-xxxxxxxxxxxx`. Surfaced from
  `awscc_sso_instance.this.instance_arn`.
- **Sign_In_URL**: The default AWS access portal URL derived from the identity
  store id, formatted `https://<identity-store-id>.awsapps.com/start`.
- **Subscription stack**: The existing `subscription/terraform` stack that
  consumes the Foundation IdC instance via `var.idc_instance_arn` and
  `var.identity_store_id`.
- **Operator**: The person running the stacks via `mise run` tasks or raw
  `tofu`.
- **Shared state backend**: The S3 bucket + DynamoDB lock table created by the
  `backend` stack. Each consuming stack uses a value-free, tracked
  `backend.tf` (`backend "s3" {}`) plus a git-ignored, keyless `backend.hcl`,
  with the state key supplied at `tofu init` time.
- **Foundation state key**: The S3 object key for this stack's state. Because
  the IdC instance is a single shared foundation resource (NOT workshop-scoped),
  the key is `foundation/terraform.tfstate` — it carries no `workshops/<id>/`
  prefix.
- **AWS_REGION / IDC_REGION**: The resource-provisioning region. `mise` sources
  `IDC_REGION` from the git-ignored `.env`; `AWS_REGION` tracks it and drives
  the AWS provider.
- **Management account enablement**: A one-time, irreversible toggle in the AWS
  Organizations management account that permits member accounts to create IdC
  account instances. A precondition for this stack, enforced by AWS, not by
  this stack.

## Requirements

### Requirement 1: Create and own the Foundation IdC instance

**User Story:** As an operator, I want a dedicated stack that creates the
account-level IdC instance, so that one place owns that long-lived resource and
the subscription stack is free to consume it.

#### Acceptance Criteria

1. THE Foundation_IdC_service SHALL create exactly one account-level IAM
   Identity Center instance using the `awscc_sso_instance` resource.
2. THE Foundation_IdC_service SHALL create no IAM Identity Center users.
3. THE Foundation_IdC_service SHALL create no IAM Identity Center groups.
4. THE Foundation_IdC_service SHALL create no IAM Identity Center group
   memberships.
5. THE Foundation_IdC_service SHALL create no IAM Identity Center permission
   sets.
6. THE Foundation_IdC_service SHALL create no IAM Identity Center account
   assignments.
7. WHERE the operator supplies an instance name input, THE Foundation_IdC_service
   SHALL apply that name to the IdC instance.
8. WHEN the operator supplies no instance name input, THE Foundation_IdC_service
   SHALL apply the default instance name `kiro-login` to the IdC instance.
9. THE Foundation_IdC_service SHALL apply the stack's default tags to the IdC
   instance using the AWS Cloud Control list-of-objects tag shape.

### Requirement 2: Emit outputs for operator wiring

**User Story:** As an operator, I want the stack to output the instance ARN,
identity store id, region, and sign-in URL, so that I can feed them into the
subscription stack's inputs.

#### Acceptance Criteria

1. THE Foundation_IdC_service SHALL output the Instance_ARN of the created IdC
   instance.
2. THE Foundation_IdC_service SHALL output the Identity_Store_ID backing the
   created IdC instance.
3. THE Foundation_IdC_service SHALL output the region in which the IdC instance
   was created.
4. THE Foundation_IdC_service SHALL output the Sign_In_URL derived from the
   Identity_Store_ID in the format `https://<identity-store-id>.awsapps.com/start`.
5. WHEN the operator requests a single output value in raw form, THE
   Foundation_IdC_service SHALL emit that value without surrounding quotes so it
   can be assigned to a `TF_VAR_*` variable or tfvars entry.

### Requirement 3: Preserve the decoupling boundary with the subscription stack

**User Story:** As a maintainer, I want the subscription stack to keep consuming
the IdC instance through explicit operator-supplied variables, so that the two
stacks stay decoupled and independently applyable.

#### Acceptance Criteria

1. THE Foundation_IdC_service SHALL expose the Instance_ARN and
   Identity_Store_ID only as stack outputs.
2. THE subscription_stack SHALL continue to read the Instance_ARN from
   `var.idc_instance_arn` and the Identity_Store_ID from `var.identity_store_id`.
3. THE subscription_stack SHALL NOT reference the Foundation_IdC_service remote
   state.
4. THE Foundation_IdC_service SHALL NOT reference the subscription_stack remote
   state.

### Requirement 4: Use the shared remote-state backend with a foundation-scoped key

**User Story:** As an operator, I want this stack to store its state in the same
shared S3 backend as the other stacks, so that teardown works from any machine
later.

#### Acceptance Criteria

1. THE Foundation_IdC_service SHALL use the shared S3 state backend created by
   the backend_stack.
2. THE Foundation_IdC_service SHALL declare a tracked, value-free `backend "s3" {}`
   block and supply account-specific values through a git-ignored, keyless
   `backend.hcl` at `tofu init` time.
3. THE Foundation_IdC_service SHALL use the Foundation state key
   `foundation/terraform.tfstate`.
4. THE Foundation state key SHALL NOT include a `workshops/<id>/` prefix.
5. WHEN the backend_stack bootstrap runs, THE backend_stack SHALL write the
   Foundation_IdC_service `backend.hcl` from a bootstrap output, consistent with
   how it writes the subscription and claim-service `backend.hcl` files.
6. IF `backend.hcl` is missing when a plan, apply, or destroy task runs, THEN
   THE Foundation_IdC_service task SHALL stop with a non-zero exit and a message
   that names the missing file.
7. IF `backend.hcl` contains a `key` entry when a plan, apply, or destroy task
   runs, THEN THE Foundation_IdC_service task SHALL stop with a non-zero exit and
   a message that the `key` is supplied at init time.

### Requirement 5: Provider and region configuration

**User Story:** As an operator, I want the stack to target the same region as
the rest of the repo through the environment, so that the IdC instance lands in
the configured provisioning region without editing committed files.

#### Acceptance Criteria

1. THE Foundation_IdC_service SHALL declare the `hashicorp/awscc` provider as a
   required provider for creating the IdC instance.
2. WHERE outputs require region or account resolution, THE Foundation_IdC_service
   SHALL declare the `hashicorp/aws` provider as a required provider.
3. WHEN `var.aws_region` is empty, THE Foundation_IdC_service SHALL create the
   IdC instance in the region resolved from the `AWS_REGION` environment
   variable.
4. WHEN `var.aws_region` is a non-empty value, THE Foundation_IdC_service SHALL
   create the IdC instance in that region.
5. WHERE `var.aws_profile` is a non-empty value, THE Foundation_IdC_service SHALL
   use that AWS profile for provider credentials.
6. THE Foundation_IdC_service SHALL report in its region output the concrete
   region the provider resolved to.

### Requirement 6: mise tasks for the foundation lifecycle

**User Story:** As an operator, I want `mise run` tasks for planning, applying,
and destroying the foundation stack, so that the workflow mirrors the other
stacks' plan/apply/destroy conventions.

#### Acceptance Criteria

1. THE repository SHALL provide a `foundation-plan` task that runs
   `tofu init -backend-config=backend.hcl` and `tofu plan` and changes no AWS
   resources.
2. THE repository SHALL provide a `foundation-apply` task that runs
   `tofu init -backend-config=backend.hcl` and `tofu apply` and prompts for
   approval before mutating AWS resources.
3. THE repository SHALL provide a `foundation-destroy` task that runs
   `tofu destroy` and prompts for confirmation before mutating AWS resources.
4. WHEN a foundation task runs `tofu init`, THE task SHALL supply the Foundation
   state key through `-backend-config="key=foundation/terraform.tfstate"`.
5. IF `tofu init` exits non-zero in a foundation task, THEN THE task SHALL stop
   with a non-zero exit and apply or destroy nothing.

### Requirement 7: Guarded, deliberate teardown

**User Story:** As an operator, I want destroying the IdC instance to be a
deliberate, guarded action, so that a routine per-workshop teardown never
removes the shared foundation resource by accident.

#### Acceptance Criteria

1. THE Foundation_IdC_service SHALL be excluded from every per-workshop
   provisioning and teardown task.
2. WHEN the operator runs the `foundation-destroy` task, THE task SHALL prompt
   the operator to type the fixed confirmation phrase `destroy-foundation`
   before any deletion proceeds.
3. WHEN the operator types a confirmation phrase that matches
   `destroy-foundation`, THE `foundation-destroy` task SHALL proceed to the
   `tofu` apply/destroy approval prompt before deleting the IdC instance.
4. IF the typed confirmation phrase does not match `destroy-foundation`, THEN
   THE `foundation-destroy` task SHALL stop with a non-zero exit and delete
   nothing.
5. WHEN the typed confirmation phrase matches `destroy-foundation`, THE
   `foundation-destroy` task SHALL still require the operator to approve `tofu`'s
   own apply/destroy prompt before deleting the IdC instance.
6. THE Foundation_IdC_service documentation SHALL state that deleting the IdC
   instance is destructive and that the management-account enablement of account
   instances cannot be reversed.
7. THE subscription teardown tasks SHALL NOT delete the Foundation IdC instance.

### Requirement 8: Single-instance idempotency and re-apply behavior

**User Story:** As an operator, I want re-applying the stack to be safe when the
instance already exists, so that I do not create a duplicate or fail an account
that already has an instance.

#### Acceptance Criteria

1. WHEN the operator re-applies the stack after a successful apply, THE
   Foundation_IdC_service SHALL make no changes to the existing IdC instance
   absent a configuration change.
2. IF an IdC account instance already exists in the account and is not yet in
   this stack's state, THEN THE Foundation_IdC_service documentation SHALL
   direct the operator to import it with
   `tofu import awscc_sso_instance.this <instance_arn>`.
3. THE Foundation_IdC_service documentation SHALL state that AWS permits one IdC
   account instance per account across all regions.

### Requirement 9: Management-account enablement precondition

**User Story:** As an operator, I want the stack to document the one-time
management-account prerequisite, so that an apply failure caused by a missing
enablement is understandable.

#### Acceptance Criteria

1. THE Foundation_IdC_service documentation SHALL state that creating an account
   instance requires the AWS Organizations management account to have enabled
   member-account IdC instances.
2. IF the management account has not enabled member-account IdC instances, THEN
   the apply SHALL fail with an authorization error on the `awscc_sso_instance`
   resource, and THE Foundation_IdC_service documentation SHALL identify that
   error as the missing enablement.
3. THE Foundation_IdC_service documentation SHALL state that the management
   account enablement is a one-time, irreversible toggle.

### Requirement 10: Operator runbook for the create-then-wire workflow

**User Story:** As an operator, I want a runbook that walks through creating the
foundation instance first and wiring its outputs into the subscription stack, so
that the end-to-end order of operations is clear.

#### Acceptance Criteria

1. THE Foundation_IdC_service documentation SHALL describe running the backend
   bootstrap, then the Foundation_IdC_service, before the subscription stack.
2. THE Foundation_IdC_service documentation SHALL describe capturing the
   Instance_ARN and Identity_Store_ID outputs.
3. THE Foundation_IdC_service documentation SHALL describe supplying the captured
   Instance_ARN and Identity_Store_ID to the subscription stack through
   `TF_VAR_idc_instance_arn` and `TF_VAR_identity_store_id` or tfvars.
4. THE Foundation_IdC_service documentation SHALL state that the foundation stack
   is applied once and reused across every workshop rather than per workshop.
