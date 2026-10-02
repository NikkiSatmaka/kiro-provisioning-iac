# Credential Claim Service

Self-serve, race-proof distribution of pre-provisioned Kiro IAM Identity Center
credentials to workshop participants. See [`DESIGN.md`](./DESIGN.md) for the full
requirements and design.

This is an opt-in, self-contained subtree with its own OpenTofu state. It does
not alter or depend on the `../subscription/` provisioning flow and can be torn down
independently without touching provisioned identities.

## Run order

The operator steps, in order (wrapped as `mise run <task>` tasks — to be filled
in by task 12.1):

1. **deploy-plan** — dry-run the infrastructure; reports changes, applies none.
2. **deploy** — apply the infrastructure (prompts for approval).
3. **seed** — populate the claim pool from `otps.csv` + `manifest.json`.
4. _(workshop runs — participants claim credentials)_
5. **audit** — export who claimed what to a git-ignored CSV, before teardown.
6. **destroy** — tear down the claim infrastructure (prompts for approval).

<!-- Details for each step are filled in by task 12.1. -->
