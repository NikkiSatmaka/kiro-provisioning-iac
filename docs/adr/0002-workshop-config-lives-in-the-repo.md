# Workshop folders live inside the repo, git-ignored

Status: accepted.

Each workshop's configuration, AWS sign-in, outputs, and credentials live in `workshops/<id>/` inside the checkout (overridable with `KIRO_WORKSHOPS_DIR`), not in a per-user directory outside it. Admins use different operating systems, and a relative in-repo path works on all of them without platform-specific home-directory rules. The cost is that the folder is not under version control and is not recreated by `git clone`, so backing it up is the admin's responsibility, and the supported install and upgrade path is `git clone` and `git pull` rather than downloading a zip.

Agent worktrees do not need workshop folders, because agents and CI never have AWS access.

## Considered Options

- A per-user directory outside the repo (for example under the home directory): rejected because it needs per-OS path rules and hides secrets-bearing state from the project.
- One repo copy per workshop (the previous model): rejected because the admin must manage N copies and hand-copy shared backend files.
