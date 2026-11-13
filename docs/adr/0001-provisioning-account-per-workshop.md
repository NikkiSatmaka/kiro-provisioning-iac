# Each workshop names its own provisioning account

Status: accepted. Supersedes the "all stacks live in one management account" decision recorded in the `multi-workshop-provisioning` spec.

Workshops are run in three shapes: a new management account with member accounts, an existing management account already used by other workshops, or a single member account under a management account the admin never touches. A single repo-wide account therefore cannot work. Each workshop folder instead records its own provisioning account (profile, account id, mode, region), and the admin signs in to it separately for every workshop. Several workshops may point at the same provisioning account, so state backend creation and the management-account singletons are discovered in AWS and created only if missing, with no local registry of accounts.

## Consequences

- The mode (`organization` or `account`) is explicit and required per workshop. The tooling asserts the live account id and mode before any mutation.
- AWS region is a per-workshop setting, never a repo-wide default. Only the test suite pins `us-east-1`.
- Authentication is `aws login` only, once per workshop; long-lived access keys are not supported.
- Tearing down a workshop never deletes the shared state bucket or singletons. A separate, explicit account-level destroy refuses to run while any workshop still has state.
