---
inclusion: always
---

# Git Workflow

How we commit, branch, and open pull requests in this repo. These rules adopt
two established open standards — **Conventional Commits** for message format and
**GitHub Flow** for branching — plus universal commit hygiene. Follow them on
every commit without being re-asked.

## Commit messages: Conventional Commits

Every commit message follows the Conventional Commits format:

```
<type>(<optional scope>): <short description>

<optional body>

<optional footer>
```

- Keep the subject line in the imperative mood ("add", not "added"/"adds") and
  under ~72 characters.
- The description starts lowercase and has no trailing period.
- Use the body to explain *why*, not *what* — the diff already shows what.

### Types

| Type       | Use for                                                        |
| ---------- | -------------------------------------------------------------- |
| `feat`     | A new feature                                                  |
| `fix`      | A bug fix                                                       |
| `docs`     | Documentation only                                             |
| `style`    | Formatting, whitespace — no code behavior change               |
| `refactor` | Code change that neither fixes a bug nor adds a feature        |
| `perf`     | A performance improvement                                      |
| `test`     | Adding or correcting tests                                     |
| `build`    | Build system or dependency changes (uv, mise, pyproject)       |
| `ci`       | CI configuration and scripts                                   |
| `chore`    | Routine maintenance that doesn't fit elsewhere                 |
| `revert`   | Reverts a previous commit                                      |

### Scopes (optional)

Scope narrows the change to an area of the repo. Prefer short, stable scopes
derived from the directory or component, e.g.:

- `feat(usecase-2): add booking confirmation step`
- `docs(workshop): clarify facilitation timing`
- `build(deps): pin boto3 version`

Omit the scope when a change is broad or doesn't map to one area.

### Breaking changes

Mark a breaking change with `!` after the type/scope and a `BREAKING CHANGE:`
footer:

```
feat(api)!: drop support for legacy product IDs

BREAKING CHANGE: product IDs are now UUIDs; integer IDs are no longer accepted.
```

### Examples

```
feat(usecase-1): extract product detail into a service layer
fix(booking): prevent double-submit on the confirm button
docs: add git workflow steering
refactor: replace inline SQL with parameterized queries
chore(deps): bump uv.lock
```

## Branching: GitHub Flow

- `main` is always deployable. Never commit directly to `main` unless the user
  explicitly asks.
- Branch off `main` for every change. Name branches `<type>/<short-slug>`,
  mirroring the commit types:
  - `feat/booking-confirmation`
  - `fix/double-submit`
  - `docs/git-workflow`
- Keep branches short-lived. Merge back to `main` via a pull request, then
  delete the branch.
- Rebase or merge `main` into a stale branch before opening the PR so it merges
  cleanly.

## Commit hygiene

- **Atomic commits.** One logical change per commit. Don't mix a refactor with a
  feature, or a formatting sweep with a bug fix.
- **Stage deliberately.** Add specific files by name rather than `git add .` or
  `git add -A`, so unrelated changes don't ride along.
- **Build before you commit** when a change touches code — a commit should not
  knowingly break the build.
- **Commit only when asked.** Don't create commits unprompted; if it's unclear,
  ask first.

## Pull requests

- Keep PRs scoped to a single concern — easy to review, easy to revert.
- Title the PR using the Conventional Commits format, under ~70 characters.
- In the description, cover: a summary of the change, how it was tested, and any
  known gaps or follow-ups.
- Use the appropriate CLI (`gh pr create` for GitHub) to open PRs.

## Secret safety

This repo contains credential files. Protect them:

- **Never stage or commit** anything under `creds/`, `.aws/credentials`, or any
  `.env` / `*.local.toml` file. These are already in `.gitignore` — keep it that
  way.
- Before committing, double-check that no secret, access key, or token is in the
  staged diff. If a file looks like it holds secrets, flag it rather than
  committing it.
- `.aws/config` (non-secret region/profile settings) is fine to commit; the
  paired `.aws/credentials` is not.
