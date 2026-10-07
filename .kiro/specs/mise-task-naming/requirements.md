# Requirements Document

## Introduction

The `mise.toml` task registry at the repository root follows a `<stack>-<verb>`
naming convention for every stack except `subscription/`. The `backend/`,
`claim-service/`, `foundation/`, and `governance/` stacks already prefix their
tasks (e.g. `backend-bootstrap`, `claim-deploy`, `foundation-apply`,
`governance-plan`). The seven subscription tasks remain unprefixed
(`provision-plan`, `provision`, `teardown-tofu`, `provision-render`,
`credentials`, `teardown-plan`, `teardown-run`), which breaks the convention and
makes stack ownership of a task ambiguous.

This feature renames all seven subscription tasks to the `subscription-*` prefix
and standardizes their verbs on plan/apply/destroy where they map cleanly. The
rename is a clean break: old task names are removed entirely with no
backward-compatibility aliases. Every documentation file and in-repo reference to
the old names is updated to the new names. Task behavior (working directory, run
body logic, and description intent) is preserved unchanged; only task names and
the text that self-references those names change.

## Glossary

- **Task_Registry**: The `mise.toml` file at the repository root that declares
  all `[tasks.*]` entries runnable via `mise run <task>`.
- **Subscription_Task**: One of the seven tasks that drive the `subscription/`
  stack, declared under `[tasks.*]` in the Task_Registry.
- **Rename_Mapping**: The fixed set of old-name → new-name pairs defined in
  Requirement 1.
- **Self_Reference**: Any comment, description, or `echo` string inside the
  Task_Registry that names a Subscription_Task by its old name.
- **Documentation_Reference**: Any occurrence of an old Subscription_Task name in
  one of the documentation or source files enumerated in Requirement 4.
- **Task_Behavior**: The `dir` value, the `run` body shell logic, and the
  functional intent of a task's `description`, excluding any text that is a
  Self_Reference to a task name.

## Requirements

### Requirement 1: Rename subscription tasks under the subscription- prefix

**User Story:** As an operator, I want every subscription task renamed under the
`subscription-*` prefix with standardized verbs, so that task names consistently
identify their owning stack.

#### Acceptance Criteria

1. THE Task_Registry SHALL declare a task named `subscription-plan` and SHALL NOT declare a task named `provision-plan`.
2. THE Task_Registry SHALL declare a task named `subscription-apply` and SHALL NOT declare a task named `provision`.
3. THE Task_Registry SHALL declare a task named `subscription-destroy` and SHALL NOT declare a task named `teardown-tofu`.
4. THE Task_Registry SHALL declare a task named `subscription-render` and SHALL NOT declare a task named `provision-render`.
5. THE Task_Registry SHALL declare a task named `subscription-credentials` and SHALL NOT declare a task named `credentials`.
6. THE Task_Registry SHALL declare a task named `subscription-teardown-plan` and SHALL NOT declare a task named `teardown-plan`.
7. THE Task_Registry SHALL declare a task named `subscription-teardown-run` and SHALL NOT declare a task named `teardown-run`.

### Requirement 2: Clean break with no legacy aliases

**User Story:** As a maintainer, I want the rename to be a clean break with no
legacy aliases, so that only the new names exist and there is one way to invoke
each task.

#### Acceptance Criteria

1. THE Task_Registry SHALL contain exactly seven Subscription_Task declarations after the rename.
2. THE Task_Registry SHALL NOT declare any alias, duplicate, or compatibility-shim task that maps an old Subscription_Task name to a new one.
3. THE Task_Registry SHALL retain the four shared toolchain tasks `setup`, `lock`, `aws-configure`, and `verify` without a stack prefix.

### Requirement 3: Preserve subscription task behavior

**User Story:** As an operator, I want the subscription tasks to behave exactly
as before, so that only their names change and no execution logic is altered.

#### Acceptance Criteria

1. THE Task_Registry SHALL preserve the `dir` value of each renamed Subscription_Task identical to the value it had under the old name.
2. THE Task_Registry SHALL preserve the `run` body shell logic of each renamed Subscription_Task identical to the logic it had under the old name, except where a line is a Self_Reference to a renamed task name.
3. THE Task_Registry SHALL preserve the functional intent of each renamed Subscription_Task `description`, changing description text only where it is a Self_Reference to a renamed task name.
4. WHERE the `backend/`, `claim-service/`, `foundation/`, or `governance/` stacks declare tasks, THE Task_Registry SHALL leave those task names unchanged.

### Requirement 4: Update documentation and in-code references

**User Story:** As a reader of the project docs, I want every documented and
in-code reference to the old task names updated to the new names, so that no
instruction points at a removed task.

#### Acceptance Criteria

1. THE File `README.md` SHALL reference the renamed Subscription_Task names in place of every old Subscription_Task name, including the occurrences near lines 153, 164, 165, 232, 233, and 234.
2. THE File `subscription/RUNBOOK.md` SHALL reference the renamed Subscription_Task names in place of every old Subscription_Task name.
3. THE File `subscription/TEARDOWN.md` SHALL reference the renamed Subscription_Task names in place of every old Subscription_Task name.
4. THE File `subscription/output/credentials.template.md` SHALL reference the renamed Subscription_Task name in place of every old Subscription_Task name.
5. THE File `.agents/tasks/remote-state-plan.md` SHALL reference the renamed Subscription_Task names in place of every old Subscription_Task name.
6. THE File `subscription/scripts/provision.py` SHALL reference the renamed Subscription_Task names in place of every old Subscription_Task name in its comments.
7. WHEN each Documentation_Reference is updated, THE updated reference SHALL use the new name assigned to that old name by the Rename_Mapping in Requirement 1.

### Requirement 5: Update mise.toml internal self-references

**User Story:** As a maintainer, I want the Task_Registry's own internal
references to the subscription tasks updated, so that comments and echo output
name the tasks that actually exist.

#### Acceptance Criteria

1. THE Task_Registry SHALL update every Self_Reference in its subscription-section comments to the new Subscription_Task name assigned by the Rename_Mapping, including the comment lines that currently name `provision-plan`, `provision`, `teardown-plan`, and `teardown-tofu`.
2. THE Task_Registry SHALL update the `echo` string in the `subscription-credentials` task that currently instructs the user to re-run `mise run credentials` so that it names `subscription-credentials`.
3. THE Task_Registry SHALL NOT contain any occurrence of an old Subscription_Task name after the rename.
