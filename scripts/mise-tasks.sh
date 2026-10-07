# shellcheck shell=sh
# =============================================================================
# scripts/mise-tasks.sh — shared helpers for the long mise task bodies.
# =============================================================================
# This file is SOURCED (not executed) by the `run` bodies in mise.toml, each of
# which starts with `set -eu`. Every long task has a `dir` that is exactly two
# levels deep (e.g. foundation/terraform, governance/terraform,
# subscription/terraform, claim-service/scripts), so each body sources this lib
# via the uniform relative path:
#
#     . ../../scripts/mise-tasks.sh
#
# which resolves to <repo-root>/scripts/mise-tasks.sh for every task.
#
# Design constraints:
#   * POSIX sh compatible (no bashisms, no `local`); runs cleanly under `set -eu`.
#   * No shebang — it is sourced, never executed directly.
#   * Functions that must leave a variable in the caller's shell (require_workshop_id
#     sets WID) assign a plain variable; they are NOT subshells.
#   * Every user-facing error/hint string is copied byte-for-byte from the
#     original inline task bodies so observable behavior is unchanged.
#
# Exposed functions:
#   require_workshop_id            — validate WORKSHOP_ID, set WID in caller
#   require_backend_hcl <label> [hint...]  — fail if backend.hcl is missing
#   reject_residual_key            — fail if backend.hcl carries a residual `key =`
#   tofu_init_keyed <state-key> <error-msg> — reconfigure-init with an init-time key
#   require_typed_phrase <phrase> <mismatch-trailing> — typed-confirmation gate
# =============================================================================

# --- WORKSHOP_ID guard (R6.1, R6.7, R8.4) ------------------------------------
# Whitespace-only WORKSHOP_ID is treated as unset: strip all whitespace, then
# fail closed (non-zero exit, no action) if what remains is empty. Then
# slug-validate. Leaves WID set in the CALLER's shell (plain assignment, sourced
# function — NOT a subshell), so callers use "$WID" directly afterwards.
require_workshop_id() {
  WID="$(printf '%s' "${WORKSHOP_ID:-}" | tr -d '[:space:]')"
  if [ -z "$WID" ]; then
    echo "ERROR: WORKSHOP_ID is required (unset or whitespace-only)." >&2
    echo "Set it in the git-ignored .env (see .env.example), e.g.:" >&2
    echo "  WORKSHOP_ID=kiro-2025-10-10" >&2
    exit 1
  fi
  # Slug-guard: 1-63 lowercase alphanumeric + hyphens, begin/end alphanumeric,
  # no consecutive hyphens (R5.8, R8.3). Defense-in-depth; the TF variable
  # validation is the authoritative gate.
  if ! printf '%s' "$WID" | grep -Eq '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$' \
     || printf '%s' "$WID" | grep -q -- '--'; then
    echo "ERROR: WORKSHOP_ID '$WID' is not a valid slug." >&2
    echo "Expected: 1-63 lowercase alphanumeric characters and hyphens, starting" >&2
    echo "and ending alphanumeric, with no consecutive hyphens." >&2
    exit 1
  fi
}

# --- backend.hcl existence guard (R4.6) --------------------------------------
# Fail closed if backend.hcl does not exist. Arg 1 is the human-readable file
# label used in the "ERROR: <label> not found." message (the message MUST
# contain the literal substring "backend.hcl not found"). Any remaining args are
# extra stderr hint lines printed verbatim (e.g. the bootstrap / copy-the-example
# hints). Call this BEFORE reject_residual_key when a task hard-requires the file.
require_backend_hcl() {
  _label="$1"
  shift
  if [ ! -f backend.hcl ]; then
    echo "ERROR: $_label not found." >&2
    for _hint in "$@"; do
      echo "$_hint" >&2
    done
    exit 1
  fi
}

# --- backend.hcl residual-key guard (R4.7, R5.9) -----------------------------
# A residual 'key' in backend.hcl conflicts with the init-time key. If the file
# is absent this is a no-op (return 0): callers that hard-require the file call
# require_backend_hcl first, and callers that only soft-check existence
# (provision, claim-destroy) relied on `[ -f backend.hcl ] && grep ...`, which
# this leading guard preserves exactly.
reject_residual_key() {
  [ -f backend.hcl ] || return 0
  if grep -Eq '^[[:space:]]*key[[:space:]]*=' backend.hcl; then
    echo "ERROR: remove the 'key' line from backend.hcl; it is supplied at init time." >&2
    exit 1
  fi
}

# --- keyed fail-closed tofu init (R6.2, R6.3, R6.5) --------------------------
# Reconfigure the backend to THIS task's state key BEFORE the mutating verb and
# fail closed if init exits non-zero. Arg 1 is the state key supplied at init
# time via -backend-config="key=<state-key>"; arg 2 is the exact message placed
# inside `echo "ERROR: <arg2>" >&2` (it varies per task, e.g.
# "backend init failed; not planning." or "backend reconfiguration failed; not
# applying."). Preserves the literal `tofu init -reconfigure` and the exact
# -backend-config="key=<state-key>" argument the tests pin.
tofu_init_keyed() {
  _state_key="$1"
  _err_msg="$2"
  tofu init -reconfigure -input=false -backend-config=backend.hcl \
    -backend-config="key=${_state_key}" \
    || { echo "ERROR: ${_err_msg}" >&2; exit 1; }
}

# --- typed-phrase confirmation guard -----------------------------------------
# Prompt the operator to type an exact phrase before a destructive/high-blast
# action proceeds; a mismatch exits non-zero. Arg 1 is the required phrase; arg 2
# is the trailing clause of the mismatch message (e.g. "destroying nothing." or
# "moving nothing."), placed as:
#   ERROR: confirmation phrase did not match '<phrase>'; <trailing>
# Task-specific WARNING lines above the prompt stay inline in each task.
require_typed_phrase() {
  _phrase="$1"
  _mismatch_trailing="$2"
  printf 'Type exactly "%s" to proceed: ' "$_phrase"
  read -r CONFIRM
  if [ "$CONFIRM" != "$_phrase" ]; then
    echo "ERROR: confirmation phrase did not match '${_phrase}'; ${_mismatch_trailing}" >&2
    exit 1
  fi
}
