#!/usr/bin/env sh
# =============================================================================
# backend/scripts/destroy_workshop_state.sh
# =============================================================================
# Surgical, per-workshop purge of the SHARED remote-state backend. Multiple
# workshops share ONE versioned+encrypted S3 bucket and ONE DynamoDB lock table
# (owned by the backend/ stack); each workshop's state is isolated by the
# init-time key workshops/<WID>/<stack>/terraform.tfstate. Hand-destroying a
# workshop's stacks leaves its state OBJECTS (every version + delete marker
# under workshops/<WID>/) and its DynamoDB lock rows behind. This script removes
# exactly those, and nothing else.
#
# Contract:
#   * $1 is an ALREADY-VALIDATED workshop id (the mise task runs
#     require_workshop_id before calling us); we re-check only that it is
#     non-empty and fail closed otherwise.
#   * An optional --apply flag switches from the default DRY RUN to the mutating
#     purge. The typed-phrase confirmation gate is the mise TASK's job (so it is
#     byte-identical to governance-destroy and reuses require_typed_phrase); this
#     script stays NON-INTERACTIVE so it is directly drivable by tests.
#   * We NEVER touch anything outside the workshops/<WID>/ prefix, NEVER delete
#     the bucket or the lock table, and NEVER use `aws s3 rm` (which would leave
#     old versions + delete markers on a versioned bucket). All deletes are
#     scoped: S3 to the prefix, DynamoDB to LockIDs beginning
#     <bucket>/workshops/<WID>/.
#
# POSIX sh: no bashisms (no `local`, no arrays, no `[[ ]]`). Runs under `set -eu`.
# Reads backend.hcl from the CURRENT directory (the mise task sets dir =
# backend/terraform, where require_backend_hcl has just verified it exists).
# =============================================================================
set -eu

# --- Arg parse ---------------------------------------------------------------
# First positional is the (already-validated) workshop id; remaining args are
# flags. --apply switches to the mutating purge; anything else is a usage error.
if [ "$#" -eq 0 ]; then
  echo "ERROR: workshop id is required (usage: destroy_workshop_state.sh <workshop-id> [--apply])." >&2
  exit 1
fi
WID="$1"
shift
if [ -z "$WID" ]; then
  echo "ERROR: workshop id is empty (usage: destroy_workshop_state.sh <workshop-id> [--apply])." >&2
  exit 1
fi
APPLY=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    *)
      echo "ERROR: unknown argument '$1' (usage: destroy_workshop_state.sh <workshop-id> [--apply])." >&2
      exit 1
      ;;
  esac
  shift
done

# --- Parse backend.hcl (same idiom as subscription-apply) --------------------
if [ ! -f backend.hcl ]; then
  echo "ERROR: backend.hcl not found in $(pwd); cannot resolve the state bucket/table." >&2
  exit 1
fi
BUCKET="$(grep -E '^[[:space:]]*bucket' backend.hcl | sed -E 's/.*= *"(.*)".*/\1/')"
TABLE="$(grep -E '^[[:space:]]*dynamodb_table' backend.hcl | sed -E 's/.*= *"(.*)".*/\1/')"
if [ -z "$BUCKET" ] || [ -z "$TABLE" ]; then
  echo "ERROR: could not parse bucket/dynamodb_table from backend.hcl." >&2
  exit 1
fi

# The ONLY S3 prefix this script ever touches, and the ONLY lock-id prefix it
# ever matches. Everything downstream is scoped to these.
PREFIX="workshops/${WID}/"
LOCK_PREFIX="${BUCKET}/workshops/${WID}/"

if [ "$APPLY" = "1" ]; then
  _MODE="APPLY"
else
  _MODE="DRY RUN"
fi
echo "backend-destroy-workshop: bucket=${BUCKET} table=${TABLE} prefix=${PREFIX} mode=${_MODE}"

# --- Apply-mode S3 batch state -----------------------------------------------
# In --apply mode we accumulate {"Key":...,"VersionId":...} entries into a JSON
# string (no arrays) and flush a delete-objects call whenever the batch reaches
# the API's 1000-object cap, then flush the remainder after pagination.
S3_COUNT=0
_batch=""
_batch_n=0

# Flush the accumulated delete-objects batch (apply mode only). Strips the
# trailing comma, wraps in the Delete payload, and resets the accumulator.
_flush_batch() {
  [ "$_batch_n" -eq 0 ] && return 0
  _objects="$(printf '%s' "$_batch" | sed -E 's/,$//')"
  aws s3api delete-objects --bucket "$BUCKET" \
    --delete "{\"Objects\":[${_objects}],\"Quiet\":true}" >/dev/null
  _batch=""
  _batch_n=0
}

# --- S3: enumerate every object version + delete marker under the prefix -----
# Paginate list-object-versions over BOTH .Versions[] and .DeleteMarkers[].
# Each read is a single-valued --query text read so parsing stays sh-friendly; a
# null marker comes back as the literal "None", which we treat as "stop".
#
# The per-page pairs are iterated in THIS shell (a `for` over an IFS=newline
# split, not a `while` pipeline), so S3_COUNT and the apply-mode batch
# accumulator persist across the loop under POSIX sh. Each column of the
# --output text projection is tab-separated; cut -f1/-f2 splits Key / VersionId.
_key_marker=""
_version_marker=""
while :; do
  if [ -z "$_key_marker" ] && [ -z "$_version_marker" ]; then
    _versions="$(aws s3api list-object-versions \
      --bucket "$BUCKET" --prefix "$PREFIX" --max-keys 1000 \
      --query 'Versions[].[Key,VersionId]' --output text)"
    _markers="$(aws s3api list-object-versions \
      --bucket "$BUCKET" --prefix "$PREFIX" --max-keys 1000 \
      --query 'DeleteMarkers[].[Key,VersionId]' --output text)"
    _truncated="$(aws s3api list-object-versions \
      --bucket "$BUCKET" --prefix "$PREFIX" --max-keys 1000 \
      --query 'IsTruncated' --output text)"
    _next_key="$(aws s3api list-object-versions \
      --bucket "$BUCKET" --prefix "$PREFIX" --max-keys 1000 \
      --query 'NextKeyMarker' --output text)"
    _next_version="$(aws s3api list-object-versions \
      --bucket "$BUCKET" --prefix "$PREFIX" --max-keys 1000 \
      --query 'NextVersionIdMarker' --output text)"
  else
    _versions="$(aws s3api list-object-versions \
      --bucket "$BUCKET" --prefix "$PREFIX" --max-keys 1000 \
      --key-marker "$_key_marker" --version-id-marker "$_version_marker" \
      --query 'Versions[].[Key,VersionId]' --output text)"
    _markers="$(aws s3api list-object-versions \
      --bucket "$BUCKET" --prefix "$PREFIX" --max-keys 1000 \
      --key-marker "$_key_marker" --version-id-marker "$_version_marker" \
      --query 'DeleteMarkers[].[Key,VersionId]' --output text)"
    _truncated="$(aws s3api list-object-versions \
      --bucket "$BUCKET" --prefix "$PREFIX" --max-keys 1000 \
      --key-marker "$_key_marker" --version-id-marker "$_version_marker" \
      --query 'IsTruncated' --output text)"
    _next_key="$(aws s3api list-object-versions \
      --bucket "$BUCKET" --prefix "$PREFIX" --max-keys 1000 \
      --key-marker "$_key_marker" --version-id-marker "$_version_marker" \
      --query 'NextKeyMarker' --output text)"
    _next_version="$(aws s3api list-object-versions \
      --bucket "$BUCKET" --prefix "$PREFIX" --max-keys 1000 \
      --key-marker "$_key_marker" --version-id-marker "$_version_marker" \
      --query 'NextVersionIdMarker' --output text)"
  fi

  # In --apply mode, delete this page's versions + markers directly here (not in
  # a pipeline subshell) so the batch accumulator and S3_COUNT persist. We build
  # the batch by iterating pairs via a temp here-string-free loop using `set`.
  _page_pairs="$(printf '%s\n%s\n' "$_versions" "$_markers")"
  _OLDIFS="$IFS"
  IFS='
'
  for _line in $_page_pairs; do
    [ -z "$_line" ] && continue
    [ "$_line" = "None" ] && continue
    # Split the line on the tab into key + version id.
    _key="$(printf '%s' "$_line" | cut -f1)"
    _vid="$(printf '%s' "$_line" | cut -f2)"
    [ -z "$_key" ] && continue
    [ "$_key" = "None" ] && continue
    S3_COUNT=$((S3_COUNT + 1))
    if [ "$APPLY" = "1" ]; then
      _batch="${_batch}{\"Key\":\"${_key}\",\"VersionId\":\"${_vid}\"},"
      _batch_n=$((_batch_n + 1))
      if [ "$_batch_n" -ge 1000 ]; then
        IFS="$_OLDIFS"
        _flush_batch
        IFS='
'
      fi
    else
      echo "would delete: s3 ${_key} ${_vid}"
    fi
  done
  IFS="$_OLDIFS"

  # Stop unless the listing is truncated and we have markers to continue from.
  if [ "$_truncated" != "True" ]; then
    break
  fi
  if { [ -z "$_next_key" ] || [ "$_next_key" = "None" ]; } \
     && { [ -z "$_next_version" ] || [ "$_next_version" = "None" ]; }; then
    break
  fi
  _key_marker="$_next_key"
  _version_marker="$_next_version"
  [ "$_key_marker" = "None" ] && _key_marker=""
  [ "$_version_marker" = "None" ] && _version_marker=""
done

# Flush any remaining accumulated deletes (apply mode).
if [ "$APPLY" = "1" ]; then
  _flush_batch
fi

# --- DynamoDB: delete the workshop's lock rows (incl. the -md5 companion) -----
# Scan the lock table projecting LockID and act on every LockID that begins
# <bucket>/workshops/<WID>/. That prefix matches both the live-lock row
# (<bucket>/<state-key>) and its persistent digest companion
# (<bucket>/<state-key>-md5) for every stack of this workshop. The AWS CLI
# auto-paginates `scan` (fetching all DynamoDB pages before applying --query),
# so a single call returns every LockID; the lock table is tiny in any case.
LOCK_COUNT=0
_ids="$(aws dynamodb scan --table-name "$TABLE" \
  --projection-expression LockID \
  --query 'Items[].LockID.S' --output text)"

_OLDIFS="$IFS"
IFS='
	'
for _lockid in $_ids; do
  [ -z "$_lockid" ] && continue
  [ "$_lockid" = "None" ] && continue
  case "$_lockid" in
    "$LOCK_PREFIX"*)
      LOCK_COUNT=$((LOCK_COUNT + 1))
      if [ "$APPLY" = "1" ]; then
        IFS="$_OLDIFS"
        aws dynamodb delete-item --table-name "$TABLE" \
          --key "{\"LockID\":{\"S\":\"${_lockid}\"}}" >/dev/null
        IFS='
	'
      else
        echo "would delete: ddb-lock ${_lockid}"
      fi
      ;;
    *) : ;;
  esac
done
IFS="$_OLDIFS"

# --- Summary -----------------------------------------------------------------
if [ "$APPLY" = "1" ]; then
  echo "backend-destroy-workshop: APPLY complete — deleted ${S3_COUNT} S3 object version(s)/delete marker(s) and ${LOCK_COUNT} lock row(s) for '${WID}'."
else
  echo "backend-destroy-workshop: DRY RUN complete — ${S3_COUNT} S3 object version(s)/delete marker(s) and ${LOCK_COUNT} lock row(s) WOULD be deleted for '${WID}' (set --apply to delete)."
fi
