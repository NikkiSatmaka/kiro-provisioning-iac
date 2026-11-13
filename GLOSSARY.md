# Kiro Workshop Provisioning

Tooling that provisions Kiro enterprise subscriptions for workshop participants through AWS IAM Identity Center, one workshop at a time, across many AWS accounts.

## Language

**Workshop**:
A time-boxed event with its own participants, identities, and credentials, provisioned and torn down independently of every other workshop.
_Avoid_: Engagement, event, run

**Workshop admin**:
The person who provisions and tears down workshops using this repo.
_Avoid_: Operator, user

**Workshop folder**:
The git-ignored directory `workshops/<id>/` that holds everything specific to one workshop: its configuration, its AWS sign-in, its generated outputs, and its credentials. The admin is responsible for backing it up.
_Avoid_: Workshop directory, workshop checkout, per-workshop clone

**Provisioning account**:
The AWS account a workshop folder signs in to, which holds its IAM Identity Center instance, its state backend, and its claim service. It is a setting of that workshop, not a repo-level concept, and several workshops may point at the same one.
_Avoid_: Home account, target account, main account

**Management-account workshop**:
A workshop whose provisioning account is an AWS Organizations management account, using the organization instance of IAM Identity Center and spanning multiple member accounts. The management account may be new or already used by other workshops.
_Avoid_: Organization-mode workshop

**Member-account workshop**:
A workshop whose provisioning account is a single member account under a management account the admin does not touch, using that account's own account instance of IAM Identity Center.
_Avoid_: Account-mode workshop, child-account workshop

**Workshop account**:
A member account that belongs to a workshop's participants for attribution and governance, as opposed to the provisioning account the workshop signs in to.
_Avoid_: Child account, participant account
