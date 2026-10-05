# Requirements Document

## Introduction

This feature makes two related changes to the Kiro provisioning IaC repository.

First, it splits the single `AWS_REGION` setting into two distinct region
concepts. Today one region value serves every purpose: where AWS resources are
created, and the region a participant enters when signing in to Kiro. Because
Kiro is only supported in `us-east-1` while the operator wants IAM Identity
Center (IdC), S3, and Lambda resources to be deployed in `ap-southeast-1`, these
two concerns must be separated. A new `KIRO_REGION` (default `us-east-1`) drives
only Kiro sign-in instructions and the Kiro console application region, while a
new `IDC_REGION` (default `ap-southeast-1`) drives where all AWS resources are
provisioned. `AWS_REGION` tracks `IDC_REGION`. The repository's existing hard
rule stands: a region value is derived only from the environment, never
hardcoded in code, IaC, or scripts.

Second, it adds an explicit mapping from each provisioned IdC to its child AWS
account ID. This supports management-account-style IdC creation where a child
account is associated. The account ID flows from a new Terraform variable into
the provisioning manifest and downstream outputs. It is surfaced in the
operator-facing credentials document (`credentials.md`) and the claim-audit CSV,
but is deliberately kept out of the one-time-password CSV (`otps.csv`) and out of
the response the Lambda claim handler returns to a claiming participant.

## Glossary

- **System**: The kiro-provisioning-iac repository as a whole, including its
  OpenTofu/Terraform configurations, Python scripts, and the claim-service
  Lambda, together with the environment configuration that drives them.
- **Environment_Config**: The environment-variable layer that supplies
  configuration values, comprising `.env`, `.env.example`, and the mise
  configuration that sources them.
- **Kiro_Region**: The region value, provided by the `KIRO_REGION` environment
  variable, that identifies where Kiro is used — specifically the region a user
  enters during Kiro sign-in and the Kiro console application region. Default
  value `us-east-1`.
- **Idc_Region**: The region value, provided by the `IDC_REGION` environment
  variable, in which all AWS resources (IdC account instance, S3, Lambda) are
  provisioned. Default value `ap-southeast-1`.
- **Aws_Region**: The `AWS_REGION` environment variable consumed by the AWS CLI,
  the AWS SDKs, and OpenTofu to resolve the region in which AWS API calls and
  resource creation occur.
- **Subscription_Terraform**: The OpenTofu/Terraform configuration under
  `subscription/terraform/` that provisions the IdC account instance, users,
  groups, and memberships, and emits the Provisioning_Manifest.
- **Claim_Service_Terraform**: The OpenTofu/Terraform configuration under
  `claim-service/terraform/` that provisions the claim-service Lambda and its
  supporting resources.
- **Provisioning_Manifest**: The `provisioning_manifest` OpenTofu output,
  exported to `manifest.json`, that carries everything the scripts consume
  (region, identity store id, sign-in URL, users, groups, memberships).
- **Idc_Account_Map**: A new Terraform variable in Subscription_Terraform that
  maps each IdC to its child AWS account ID, supplied as explicit per-IdC input.
- **Account_Id**: A child AWS account ID associated with an IdC, as supplied
  through the Idc_Account_Map.
- **Credentials_Document**: The operator-facing Markdown file rendered by
  `subscription/scripts/provision_passwords_and_output.py` to
  `credentials.md`, listing the sign-in URL, region, and a row per user.
- **Otps_Csv**: The `otps.csv` file (header `username,otp`) that maps a username
  to a one-time password.
- **Audit_Export**: The timestamped claim-audit CSV written by
  `claim-service/scripts/export_audit.py` to `claim-service/output/`.
- **Claim_Handler**: The claim-service Lambda handler
  (`claim-service/lambda/claim_handler.py`) that returns a credential to a
  claiming participant.
- **Claim_Response**: The JSON success body the Claim_Handler returns to a
  claiming participant.
- **Seed_Script**: `claim-service/scripts/seed_claim_pool.py`, which seeds the
  claim-service DynamoDB table from the Otps_Csv and the Provisioning_Manifest.

## Requirements

### Requirement 1

**User Story:** As an operator, I want separate region settings for Kiro sign-in
and for AWS resource provisioning, so that resources can be deployed in
`ap-southeast-1` while Kiro sign-in continues to use the only region Kiro
supports, `us-east-1`.

#### Acceptance Criteria

1. THE Environment_Config SHALL define a `KIRO_REGION` variable with a default
   value of `us-east-1`.
2. THE Environment_Config SHALL define an `IDC_REGION` variable with a default
   value of `ap-southeast-1`.
3. THE Environment_Config SHALL set `AWS_REGION` to the value of `IDC_REGION`.
4. THE System SHALL provision the IdC account instance, S3 resources, and Lambda
   resources in the region identified by `IDC_REGION`.
5. THE System SHALL use `KIRO_REGION` only for Kiro sign-in instructions and the
   Kiro console application region.
6. WHERE a document or instruction states the region a user enters when signing
   in to Kiro, THE System SHALL present the value of `KIRO_REGION`.

### Requirement 2

**User Story:** As an operator, I want the credentials document to clearly
distinguish the Kiro sign-in region from the resource-deployment region, so that
participants enter the correct region when signing in to Kiro.

#### Acceptance Criteria

1. THE Credentials_Document SHALL present the Kiro sign-in region as the value of
   `KIRO_REGION`.
2. WHERE the Credentials_Document instructs a user to enter a region during Kiro
   sign-in, THE Credentials_Document SHALL present the value of `KIRO_REGION`.
3. THE Credentials_Document SHALL present the region in which AWS resources are
   provisioned as the value of `IDC_REGION`.

### Requirement 3

**User Story:** As a maintainer, I want every region value to come from the
environment, so that no region is hardcoded anywhere in the repository.

#### Acceptance Criteria

1. THE System SHALL derive every region value from an environment variable in
   application code, infrastructure-as-code, and scripts.
2. IF a region value would otherwise be written as a literal constant in
   application code, infrastructure-as-code, or scripts, THEN THE System SHALL
   instead read that region value from an environment variable.
3. WHERE a script accepts a region argument, THE System SHALL default that
   argument to a region value read from the environment.

### Requirement 4

**User Story:** As an operator, I want to declare which child AWS account each
IdC belongs to, so that management-account-style IdC creation with child-account
association is supported.

#### Acceptance Criteria

1. THE Subscription_Terraform SHALL define the Idc_Account_Map variable mapping
   each IdC to its child Account_Id.
2. THE Idc_Account_Map SHALL accept the Account_Id for each IdC as explicit
   per-IdC input.
3. WHERE an IdC is created in management-account style with a child-account
   association, THE Subscription_Terraform SHALL accept the associated child
   Account_Id through the Idc_Account_Map.

### Requirement 5

**User Story:** As an operator, I want the account ID to flow from the Terraform
input into the manifest and downstream outputs, so that scripts and reports can
read it from a single provisioning source.

#### Acceptance Criteria

1. THE Subscription_Terraform SHALL include the Account_Id in the
   Provisioning_Manifest.
2. THE Subscription_Terraform SHALL expose the Account_Id in its outputs.
3. WHEN a user maps to a specific IdC, THE Provisioning_Manifest SHALL associate
   that user with the Account_Id of that IdC.

### Requirement 6

**User Story:** As an operator, I want the account ID shown in the credentials
document, so that I know which AWS account each user maps to.

#### Acceptance Criteria

1. THE Credentials_Document SHALL present the Account_Id as a document-level
   header field.
2. THE Credentials_Document SHALL present a per-user Account_Id column, so that
   users mapping to different accounts show their respective Account_Id values.
3. WHEN a user maps to an Account_Id, THE Credentials_Document SHALL display that
   user's Account_Id in the user's row.

### Requirement 7

**User Story:** As an operator, I want the account ID recorded in the claim-audit
export, so that the post-workshop audit records which account each claimed
credential belongs to.

#### Acceptance Criteria

1. THE Audit_Export SHALL include an `account_id` column.
2. WHEN the Audit_Export writes a row for a claimed credential, THE Audit_Export
   SHALL populate the `account_id` column with the Account_Id associated with
   that credential.

### Requirement 8

**User Story:** As a security-conscious operator, I want the account ID withheld
from the OTP CSV and from the participant-facing claim response, so that account
information is confined to operator-facing outputs.

#### Acceptance Criteria

1. THE Otps_Csv SHALL exclude the Account_Id.
2. THE Claim_Response SHALL exclude the Account_Id.
3. WHEN the Claim_Handler returns a credential to a claiming participant, THE
   Claim_Handler SHALL return only the username, one-time password, sign-in URL,
   and region.
