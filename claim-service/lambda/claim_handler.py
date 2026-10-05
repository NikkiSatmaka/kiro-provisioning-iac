"""Credential Claim Service Lambda handler.

Served by a single AWS Lambda Function URL: GET returns the claim page, POST
runs the claim pipeline. This module is built up across several tasks; this
first slice provides the email + request helpers that later layers build on.

PII note: a normalized email is the sole key-derivation for an email and is
stored only in the ``EMAIL#`` item and the credential's ``claimed_by_email``
attribute. Raw emails and OTPs are never logged.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import time
from datetime import UTC, datetime

import boto3
from boto3.dynamodb.conditions import Attr

# Module logger for operational diagnostics. On Lambda, records emitted here go
# to the function's CloudWatch log group. We log the traceback of an unexpected
# (non-ClaimError) failure so a 500 is never silent again — but we log ONLY the
# exception and its stack via ``exc_info``, never the request event, email, or
# OTP, preserving the PII discipline in the module docstring (Requirement 7.4).
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level configuration (read once from the environment)
# ---------------------------------------------------------------------------
# The deployment region comes from the environment, never hardcoded. On Lambda
# the runtime always sets AWS_REGION to the region the function runs in, so the
# DynamoDB client resolves to the right region automatically; an operator can
# still override it by setting AWS_REGION explicitly. When unset (empty string)
# we pass no region to boto3 and let its own resolution chain decide. The table
# name is injected by OpenTofu as the TABLE_NAME env var (design: "Lambda
# packaging and configuration").
REGION = os.environ.get("AWS_REGION", "")
TABLE_NAME = os.environ.get("TABLE_NAME", "")

# The workshop code every claim must present, and the single CORS origin the
# handler echoes back. Both are injected by OpenTofu as env vars; when unset we
# default to the empty string. An empty ALLOWED_ORIGIN later resolves to the
# "*" wildcard, while an empty CONFIGURED_WORKSHOP_CODE makes every submitted
# code mismatch under the constant-time compare (design: "Module
# configuration"; Requirements 4.1, 4.2).
CONFIGURED_WORKSHOP_CODE = os.environ.get("WORKSHOP_CODE", "")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "")

# Read-once cache for the claim page. The HTML ships next to this module as
# index.html; _load_page populates _PAGE_HTML on first GET and reuses it across
# warm invocations, mirroring the lazy _table memoization (design: "Module-level
# additions").
_PAGE_PATH = os.path.join(os.path.dirname(__file__), "index.html")
_PAGE_HTML: str | None = None

# Max POST attempts allowed from a single source IP before the per-IP cap
# trips (Requirement 12.2). Injected by OpenTofu as PER_IP_CAP; defaults to a
# conservative workshop value when unset.
PER_IP_CAP = int(os.environ.get("PER_IP_CAP", "20"))

# How many times :func:`claim` re-picks an available credential after losing a
# pick-then-claim race (Requirement 2.4). Each lost race means a *different*
# claimant took the picked credential between the pick and the transaction, so
# a fresh pick almost always succeeds; a small bound keeps contention graceful
# without unbounded spinning. Injected by OpenTofu as RETRY_BOUND; defaults to
# a modest workshop value when unset.
RETRY_BOUND = int(os.environ.get("RETRY_BOUND", "5"))

# How long a RATE#<ip> counter lives before DynamoDB TTL reaps it. The counter
# only needs to span the workshop window, so a short horizon keeps the table
# self-cleaning and free-tier friendly (design: "Rate item").
RATE_TTL_SECONDS = int(os.environ.get("RATE_TTL_SECONDS", str(60 * 60)))

# A lazily-created DynamoDB resource/table pair. Kept module-level so the client
# (and its connection pool) is reused across warm Lambda invocations rather than
# rebuilt per request.
_dynamodb = None
_table = None


def _get_table():
    """Return the memoized DynamoDB Table handle for the configured table.

    Resolved lazily so importing this module (e.g. in unit tests) does not
    require AWS configuration; tests can also override ``_table`` directly.
    """
    global _dynamodb, _table
    if _table is None:
        # Only pin region_name when AWS_REGION is set; otherwise let boto3's
        # own resolution chain (AWS_REGION / AWS_DEFAULT_REGION / config)
        # decide, rather than forcing a hardcoded region.
        kwargs = {"region_name": REGION} if REGION else {}
        _dynamodb = boto3.resource("dynamodb", **kwargs)
        _table = _dynamodb.Table(TABLE_NAME)
    return _table


def _load_page() -> str:
    """Return the claim page HTML, reading ``index.html`` once and caching it.

    On the first call the packaged ``index.html`` (a sibling of this module at
    the deployment-package root) is read from ``_PAGE_PATH`` and cached in the
    module-level ``_PAGE_HTML``; warm invocations reuse the cache, mirroring the
    lazy ``_table`` memoization above (design: "_load_page"; Requirements 3.1,
    3.2).

    A read failure raises ``OSError`` rather than being swallowed, so the
    handler layer (``html_response``) can map it to a 500 ``Error_Envelope``
    (Requirement 3.3).
    """
    global _PAGE_HTML
    if _PAGE_HTML is None:
        with open(_PAGE_PATH, encoding="utf-8") as fh:
            _PAGE_HTML = fh.read()
    return _PAGE_HTML


class ClaimError(Exception):
    """A claim-pipeline failure that maps to an HTTP response.

    Carries the HTTP ``status`` to return and a human-readable ``message``.
    The top-level handler converts a ClaimError into the JSON error envelope
    ``{"error": "<message>"}`` with the given status.
    """

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def normalize_email(raw: str) -> str:
    """Normalize an email to its canonical key form.

    Lowercases and strips leading/trailing whitespace. This is the sole
    key-derivation for an email across the service (Requirement 1.5), so the
    operation is idempotent: ``normalize_email(normalize_email(e))`` equals
    ``normalize_email(e)``.
    """
    return raw.strip().lower()


def is_valid_email(email: str) -> bool:
    """Format-only validity check (Requirements 1.3, 13.2).

    An email is considered valid when it has a non-empty local part, exactly
    one ``@`` separator, and a non-empty domain part. No verification round
    trip is performed.
    """
    if email.count("@") != 1:
        return False
    local, _, domain = email.partition("@")
    return bool(local) and bool(domain)


def parse_post(event: dict) -> dict:
    """Parse and validate the JSON POST body.

    Returns a dict with the ``email`` and ``workshop_code`` fields. Raises
    ``ClaimError(400)`` when the body is absent, is not valid JSON, is not a
    JSON object, or omits either required field (Requirement 1.4).
    """
    body = event.get("body")
    if body is None:
        raise ClaimError(400, "request body is required")

    if event.get("isBase64Encoded"):
        import base64

        try:
            body = base64.b64decode(body).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            raise ClaimError(400, "request body is not valid")

    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        raise ClaimError(400, "request body must be valid JSON")

    if not isinstance(parsed, dict):
        raise ClaimError(400, "request body must be a JSON object")

    email = parsed.get("email")
    workshop_code = parsed.get("workshop_code")
    if email is None:
        raise ClaimError(400, "email field is required")
    if workshop_code is None:
        raise ClaimError(400, "workshop_code field is required")

    return {"email": email, "workshop_code": workshop_code}


# ---------------------------------------------------------------------------
# Abuse gate — per-IP attempt cap (Requirement 12.2)
# ---------------------------------------------------------------------------

def source_ip(event: dict) -> str:
    """Extract the caller's source IP from a Function URL event.

    Function URL (and API Gateway v2 "HTTP API") events carry the client IP at
    ``event["requestContext"]["http"]["sourceIp"]``. Returns ``"unknown"`` when
    the field is absent so the rate counter still functions (all such callers
    simply share one bucket) rather than crashing the pipeline.
    """
    return (
        event.get("requestContext", {})
        .get("http", {})
        .get("sourceIp")
        or "unknown"
    )


def request_method(event: dict) -> str:
    """Return the request's HTTP method, upper-cased, or ``""`` when unreadable.

    Reads the method from ``event["requestContext"]["http"]["method"]`` and
    upper-cases it so the handler's routing compares case-insensitively — ``get``,
    ``Post`` and ``options`` all match (Requirements 2.1–2.4).

    When the method is absent, empty, or not a string, returns the empty-string
    sentinel ``""``; the handler maps that to a ``GET`` so an unreadable method
    is treated as a page request (Requirement 2.5; design: "request_method").
    """
    raw = (
        event.get("requestContext", {})
        .get("http", {})
        .get("method")
    )
    if not isinstance(raw, str) or raw == "":
        return ""
    return raw.upper()


def check_and_increment_ip(ip: str, cap: int) -> None:
    """Count one POST attempt from ``ip`` and enforce the per-IP cap.

    Performs a single atomic ``UpdateItem`` with ``ADD #count :one`` on the
    ``RATE#<ip>`` item (design: "Rate item"). Because the ``ADD`` is atomic,
    concurrent attempts from the same IP cannot race past the cap — DynamoDB
    serializes the increments and ``ReturnValues="UPDATED_NEW"`` hands back the
    post-increment total. The ``ttl`` attribute is written **only on first
    touch** via ``if_not_exists`` so the counter auto-expires a fixed horizon
    after the IP's first attempt (DynamoDB TTL), keeping the table self-cleaning.

    Raises ``ClaimError(429)`` once the running count exceeds ``cap`` so the
    attempt that pushes an IP over the limit — and every attempt after it — is
    rejected (Requirement 12.2). The increment happens before the check, so the
    rejected attempt is itself counted; attempts from other IPs touch distinct
    items and are unaffected.
    """
    table = _get_table()
    expires_at = int(time.time()) + RATE_TTL_SECONDS

    response = table.update_item(
        Key={"PK": f"RATE#{ip}"},
        UpdateExpression="ADD #count :one SET #ttl = if_not_exists(#ttl, :ttl)",
        ExpressionAttributeNames={"#count": "count", "#ttl": "ttl"},
        ExpressionAttributeValues={":one": 1, ":ttl": expires_at},
        ReturnValues="UPDATED_NEW",
    )
    count = response.get("Attributes", {}).get("count", 0)

    if count > cap:
        raise ClaimError(429, "too many attempts; please try again later")


# ---------------------------------------------------------------------------
# Workshop-code gate (Requirement 5)
# ---------------------------------------------------------------------------

def verify_workshop_code(submitted: str) -> None:
    """Gate a claim on the configured workshop code (Requirement 5).

    Trims the submitted code and compares it against the module-level
    ``CONFIGURED_WORKSHOP_CODE`` with :func:`hmac.compare_digest`, the stdlib
    constant-time comparison (R5.2) — so a wrong code reveals nothing through
    timing. Returns ``None`` on a match so the pipeline proceeds; raises
    ``ClaimError(403, "invalid workshop code")`` when the trimmed code is empty
    (R5.3) or does not match (R5.3).

    This gate runs *before* ``normalize_email`` and ``claim`` in the pipeline
    (design: "run_claim_pipeline"), so a wrong or empty code touches no
    credential, locks no email, and never normalizes-for-claim (R5.3, R5.4) —
    this function itself only trims, compares, and raises.

    ``submitted`` is always a present value: ``parse_post`` already raises 400
    for a missing ``workshop_code`` field (R6.3), so a "missing" field is a 400
    while a "present-but-wrong/empty" code is this 403.

    Fail-closed: when ``WORKSHOP_CODE`` is unset ``CONFIGURED_WORKSHOP_CODE`` is
    ``""``, and every submission is rejected — a non-empty trimmed candidate
    never equals ``""`` under ``compare_digest``, and an empty candidate is
    caught by the explicit empty check.
    """
    candidate = submitted.strip()  # R5.1 (trim submitted)
    if candidate == "":
        raise ClaimError(403, "invalid workshop code")  # R5.3 (empty after trim)
    if not hmac.compare_digest(candidate, CONFIGURED_WORKSHOP_CODE):  # R5.2
        raise ClaimError(403, "invalid workshop code")  # R5.3 (wrong code)


# ---------------------------------------------------------------------------
# Response builders and CORS (the wiring layer; Requirements 3, 7, 9)
# ---------------------------------------------------------------------------

def resolve_origin() -> str:
    """Return the CORS origin to echo on every response (R9.1, R9.2).

    Resolves to the configured ``ALLOWED_ORIGIN`` when it is a non-empty string
    (R9.1), otherwise the ``"*"`` wildcard (R9.2), mirroring the Function URL
    CORS fallback in ``lambda.tf``. Reads only a module string, so it cannot
    raise — the handler calls it *before* its ``try`` so even a 500 still
    carries CORS headers (R9.3).
    """
    return ALLOWED_ORIGIN if ALLOWED_ORIGIN else "*"


def cors_headers(origin: str) -> dict:
    """Return the base header map carrying the single CORS origin (R9.3, R9.5).

    This is the *one* place ``Access-Control-Allow-Origin`` is set, so every
    response funnels its ACAO through here and carries exactly one such header
    equal to ``resolve_origin()`` — no second, conflicting value from the
    handler side (R9.5).
    """
    return {"Access-Control-Allow-Origin": origin}


def json_response(status: int, obj: dict, origin: str) -> dict:
    """Build a JSON Function URL response (R7.3, R8.2).

    JSON-encodes ``obj`` to a string ``body`` (so the Function URL serializes it
    verbatim, R1.3), sets ``Content-Type: application/json`` (R7.3), and includes
    the single CORS origin via :func:`cors_headers` (R9.3). Used for POST
    success bodies, every ``Error_Envelope``, and the 405 response.
    """
    headers = cors_headers(origin)
    headers["Content-Type"] = "application/json"  # R7.3, R8.2
    return {"statusCode": status, "headers": headers, "body": json.dumps(obj)}


def html_response(origin: str) -> dict:
    """Serve the cached claim page, or a 500 envelope if it is unreadable (R3).

    Reads the page via :func:`_load_page` (R3.1, R3.2) and returns it with HTTP
    200 and ``Content-Type: text/html; charset=utf-8``. If ``_load_page`` raises
    ``OSError`` (``index.html`` unreadable), returns a 500 ``Error_Envelope``
    with the uniform CORS + JSON headers (R3.3) rather than letting the failure
    escape.
    """
    try:
        page = _load_page()  # R3.1, R3.2
    except OSError:
        return json_response(500, {"error": "internal error"}, origin)  # R3.3
    headers = cors_headers(origin)
    headers["Content-Type"] = "text/html; charset=utf-8"  # R2.1
    return {"statusCode": 200, "headers": headers, "body": page}


def preflight_response(origin: str) -> dict:
    """Build the CORS preflight response for an OPTIONS request (R2.3, R9.4).

    Returns HTTP 204 with an empty-string ``body`` (R2.3), the single CORS
    origin via :func:`cors_headers`, and the preflight headers:
    ``Access-Control-Allow-Methods: GET, POST`` and
    ``Access-Control-Allow-Headers: content-type`` (R9.4).
    """
    headers = cors_headers(origin)
    headers["Access-Control-Allow-Methods"] = "GET, POST"  # R9.4
    headers["Access-Control-Allow-Headers"] = "content-type"  # R9.4
    return {"statusCode": 204, "headers": headers, "body": ""}


# ---------------------------------------------------------------------------
# Core claim path (the correctness core)
# ---------------------------------------------------------------------------

def pick_available() -> str | None:
    """Return the ``username`` of one available credential, or ``None``.

    Scans the single table with a ``FilterExpression`` of
    ``status = "available"`` and returns the ``username`` of the first match
    (design: "Single-table DynamoDB model" — a GSI is unnecessary at workshop
    scale). Returns ``None`` when no available credential remains, which the
    caller maps to pool exhaustion (Requirement 5.1).

    This is only a *hint*: the credential it names may be taken by a concurrent
    claim before the transaction commits. Correctness does not depend on the
    pick being exclusive — the conditional ``Update`` in :func:`claim` rejects a
    stale pick, so a lost race is retried rather than mis-assigned
    (Requirements 2.1, 8.1).
    """
    table = _get_table()
    response = table.scan(
        FilterExpression=Attr("status").eq("available"),
        ProjectionExpression="username",
        Limit=1,
    )
    items = response.get("Items", [])
    if items:
        return items[0]["username"]

    # A filtered Scan can return an empty page while more items remain beyond
    # the LastEvaluatedKey; keep paging until we find one or exhaust the table.
    while "LastEvaluatedKey" in response:
        response = table.scan(
            FilterExpression=Attr("status").eq("available"),
            ProjectionExpression="username",
            Limit=1,
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items = response.get("Items", [])
        if items:
            return items[0]["username"]
    return None


def _credential_response(item: dict) -> dict:
    """Project a ``CRED#`` item down to the API success body.

    Returns exactly the four fields the ``200`` contract promises — ``username``,
    ``otp``, ``sign_in_url`` and ``region`` (Requirements 4.1, 4.2) — and nothing
    else, so an item's internal attributes (status, claimed_by_email, …) never
    leak to the participant.
    """
    return {
        "username": item["username"],
        "otp": item["otp"],
        "sign_in_url": item["sign_in_url"],
        "region": item["region"],
    }


def reclaim(email: str) -> dict:
    """Return the credential ``email`` already claimed (idempotent re-claim).

    Invoked when a claim's ``EMAIL#`` ``Put`` is rejected because the email
    already holds a lock (design: "Idempotent re-scan", F4). Reads the
    ``EMAIL#<email>`` item to recover the username it was bound to, loads that
    ``CRED#`` item, and returns the **same** credential the participant first
    received (Requirements 2.5, 3.1, 3.2). A participant who closes the tab and
    re-submits gets their credential back, not an error and not a second one.

    ``email`` must already be normalized (:func:`normalize_email`). Raises
    ``ClaimError(409)`` only if the lock has vanished between the cancelled
    transaction and this read — a should-not-happen case that we surface rather
    than return a partial response.
    """
    table = _get_table()

    lock = table.get_item(Key={"PK": f"EMAIL#{email}"}).get("Item")
    if not lock:
        raise ClaimError(409, "all claimed")

    username = lock["username"]
    item = table.get_item(Key={"PK": f"CRED#{username}"}).get("Item", {})
    return _credential_response(item)


def _reason_code(reasons: list, index: int) -> str | None:
    """Return the cancellation reason ``Code`` at ``index``, or ``None``.

    ``CancellationReasons`` is positionally aligned with the ``TransactItems``
    list: index 0 is the ``EMAIL#`` ``Put``, index 1 is the ``CRED#``
    ``Update``. An item that did not itself cause the cancellation carries the
    code ``"None"``; the offending item(s) carry ``"ConditionalCheckFailed"``.
    This helper reads one slot defensively so a short or malformed list never
    raises while we are already handling a cancellation.
    """
    if index < len(reasons):
        return (reasons[index] or {}).get("Code")
    return None


def claim(email: str) -> dict:
    """Claim one credential for ``email`` and return its credential dict.

    ``email`` must already be normalized by the caller (:func:`normalize_email`)
    — it is the sole key-derivation for the email (Requirement 1.5). The method
    runs an optimistic claim with bounded retry (design: "Selecting which
    credential to hand out"):

    0. **Re-claim fast path.** First reads the ``EMAIL#<email>`` lock; if it
       already exists, this email has claimed before, so :func:`reclaim`
       returns the **same** credential (Requirements 2.5, 3.1, 3.2). This check
       runs *before* the pool is consulted so a returning participant always
       gets their credential back — even once every credential has been claimed
       and the pool is exhausted. (Previously the pool-exhaustion check ran
       first, so a returning participant wrongly saw "all claimed".)
    1. Picks an available credential via :func:`pick_available`; raises
       ``ClaimError(409)`` when the pool is exhausted (Requirement 5.1).
    2. Commits a single ``TransactWriteItems`` holding **both** uniqueness
       checks (design: "The claim transaction", Requirement 2.3):
         * a conditional ``Put`` of ``EMAIL#<email>`` guarded by
           ``attribute_not_exists(PK)`` — one claim per email (Req 2.2 / 8.2).
           The lock item also carries the picked credential's ``account_id``
           (read before the transaction, default ``""``), copied so the audit
           can read it directly without a second lookup; it is operator-only and
           never reaches ``_credential_response`` (Requirements 7.2, 8.2, 8.3);
         * a conditional ``Update`` of ``CRED#<username>`` guarded by
           ``status = "available"`` — one claim per credential (Req 2.1 / 8.1).

    The step-0 read is only a fast path, **not** the uniqueness boundary: the
    authoritative one-per-email guarantee still lives in the transaction's
    conditional ``Put``. Two concurrent first-time claims for the same email can
    both pass the step-0 read (neither lock exists yet), but only one can commit
    the ``Put`` guarded by ``attribute_not_exists(PK)``; the loser's transaction
    is cancelled and routed to :func:`reclaim`, so an email still never
    double-claims (Requirement 8.3). Likewise a credential is never
    double-assigned, since its ``Update`` is guarded by ``status = available``.

    When the transaction is cancelled, ``CancellationReasons`` tells us which
    condition failed (design: "Claim decision flow"):

    * **Email-lock failed** (index 0 ``ConditionalCheckFailed``): this email has
      already claimed, so :func:`reclaim` returns the same credential, 200
      (Requirements 2.5, 3.1, 3.2). This holds even when the credential update
      *also* failed — the email lock wins, since the participant already has a
      credential and must get that one back idempotently.
    * **Only the credential failed** (index 1 ``ConditionalCheckFailed``): the
      picked credential was taken between pick and write (a lost race), so we
      re-pick and retry, up to ``RETRY_BOUND`` attempts (Requirement 2.4). On
      exhaustion of the retry budget we raise ``ClaimError(409)``
      (Requirements 5.1, 5.2).

    On success this reads back the just-claimed ``CRED#`` item and returns its
    ``username``, ``otp``, ``sign_in_url`` and ``region`` (Requirements 4.1,
    4.2).
    """
    table = _get_table()
    client = table.meta.client
    cancelled = client.exceptions.TransactionCanceledException

    # Idempotent re-claim FIRST: if this email already holds a lock, hand back
    # the same credential before touching the pool. This must run before
    # pick_available(), otherwise a returning participant hits a "all claimed"
    # 409 the moment the pool is exhausted — even though they already have a
    # credential waiting for them. The authoritative one-per-email guarantee
    # still lives in the transaction's conditional Put below (an email that
    # races to claim twice is caught there); this read is a fast path for the
    # common "closed the tab and came back" case, not the correctness boundary.
    existing = table.get_item(Key={"PK": f"EMAIL#{email}"}).get("Item")
    if existing:
        return reclaim(email)

    # One pick + transaction per iteration; a credential conflict re-picks and
    # retries, so the loop runs at most RETRY_BOUND times (Requirement 2.4).
    for _attempt in range(RETRY_BOUND):
        username = pick_available()
        if username is None:
            raise ClaimError(409, "all claimed")

        # Read the picked credential's account_id before the transaction so it
        # can be copied onto the EMAIL# lock. The seed stamps account_id onto
        # each CRED# item; pre-change items (or an IdC with no mapping) lack it,
        # so we default to "" rather than fail the claim. This value is for the
        # operator audit only and never enters _credential_response (design:
        # "Claim handler"; Requirements 7.2, 8.2, 8.3).
        picked = table.get_item(Key={"PK": f"CRED#{username}"}).get("Item", {})
        cred_account_id = picked.get("account_id", "")

        claimed_at = datetime.now(UTC).isoformat()

        try:
            client.transact_write_items(
                TransactItems=[
                    {
                        # One claim per email: fails if this email already
                        # holds a lock. Values are native Python, not typed
                        # {"S": ...} descriptors: this transaction runs on the
                        # resource's auto-serializing client (table.meta.client),
                        # which marshals native values itself. Passing pre-typed
                        # descriptors here makes it double-serialize them into a
                        # Map, so DynamoDB rejects PK with "expected: S actual: M"
                        # and cancels the transaction with a ValidationError.
                        "Put": {
                            "TableName": TABLE_NAME,
                            "Item": {
                                "PK": f"EMAIL#{email}",
                                "username": username,
                                "claimed_at": claimed_at,
                                "account_id": cred_account_id,
                            },
                            "ConditionExpression": "attribute_not_exists(PK)",
                        },
                    },
                    {
                        # One claim per credential: fails if it was taken since
                        # the pick. Native values for the same reason as above.
                        "Update": {
                            "TableName": TABLE_NAME,
                            "Key": {"PK": f"CRED#{username}"},
                            "UpdateExpression": (
                                "SET #status = :claimed, "
                                "claimed_by_email = :email, "
                                "claimed_at = :claimed_at"
                            ),
                            "ConditionExpression": "#status = :available",
                            "ExpressionAttributeNames": {"#status": "status"},
                            "ExpressionAttributeValues": {
                                ":claimed": "claimed",
                                ":available": "available",
                                ":email": email,
                                ":claimed_at": claimed_at,
                            },
                        },
                    },
                ]
            )
        except cancelled as exc:
            reasons = exc.response.get("CancellationReasons", [])
            email_failed = _reason_code(reasons, 0) == "ConditionalCheckFailed"
            cred_failed = _reason_code(reasons, 1) == "ConditionalCheckFailed"

            # Email lock wins: the email has already claimed, so hand back the
            # same credential idempotently — even if the credential update also
            # failed its condition (Requirements 2.5, 3.1, 3.2).
            if email_failed:
                return reclaim(email)

            # Only the credential was taken between pick and write: re-pick and
            # retry within the bound (Requirement 2.4).
            if cred_failed:
                continue

            # A cancellation we do not recognize (neither uniqueness condition
            # failed) is not ours to interpret; let it propagate.
            raise

        item = table.get_item(Key={"PK": f"CRED#{username}"}).get("Item", {})
        return _credential_response(item)

    # Exhausted the retry budget while still losing credential races: treat as
    # no credential available to this claimant (Requirements 5.1, 5.2).
    raise ClaimError(409, "all claimed")


# ---------------------------------------------------------------------------
# POST pipeline composition (Requirement 6)
# ---------------------------------------------------------------------------

def run_claim_pipeline(event: dict) -> dict:
    """Run the POST claim pipeline and return the credential dict (R6).

    Composes the existing functions in the one fixed order the design mandates
    (design: "run_claim_pipeline"), raising ``ClaimError`` at the first failing
    step and letting it propagate to the handler layer, which maps it to an
    HTTP ``Error_Envelope`` — this layer never maps to HTTP itself:

    1. **Per-IP cap** — :func:`source_ip` then :func:`check_and_increment_ip`
       with ``PER_IP_CAP``. An IP already over the cap is rejected with
       ``ClaimError(429)`` *before* the body is parsed, so a flooding caller
       never reaches body parse, code verification, or any credential
       (R6.1, R6.2).
    2. **Body parse** — :func:`parse_post` yields ``email`` and
       ``workshop_code`` or raises ``ClaimError(400)`` (R6.3).
    3. **Email format** — :func:`is_valid_email`; a malformed address raises
       ``ClaimError(400)`` here, before the workshop-code gate (R6.4).
    4. **Workshop-code gate** — :func:`verify_workshop_code` raises
       ``ClaimError(403)`` on a wrong/empty code. Running it *before*
       normalize-for-claim guarantees a bad code touches no credential, locks
       no email, and never normalizes-for-claim or accesses a credential
       (R5.3, R5.4).
    5. **Normalize** — :func:`normalize_email` derives the canonical key only
       after the gate has passed (R6.5).
    6. **Claim** — :func:`claim` returns the four-field success body on success
       or raises ``ClaimError(409)`` when the pool is exhausted (R6.6).
    """
    ip = source_ip(event)
    check_and_increment_ip(ip, PER_IP_CAP)  # 1. per-IP cap → 429 (R6.1, R6.2)
    fields = parse_post(event)  # 2. body parse → 400 (R6.3)
    if not is_valid_email(fields["email"]):  # 3. email format
        raise ClaimError(400, "email is not valid")  # (R6.4)
    verify_workshop_code(fields["workshop_code"])  # 4. gate → 403 (R5, R5.3, R5.4)
    email = normalize_email(fields["email"])  # 5. normalize (R6.5)
    return claim(email)  # 6. claim → 200 / 409 (R6.6)


# ---------------------------------------------------------------------------
# Lambda entrypoint (the wiring layer; Requirements 1, 2, 7, 9)
# ---------------------------------------------------------------------------

def handler(event, context) -> dict:
    """Single Lambda Function URL entrypoint composing the wiring layer (R1, R2, R7).

    Resolves the CORS origin, routes on the HTTP method, and wraps the dispatch
    in one ``try/except`` so no failure escapes unmapped (design:
    "handler(event, context) -> dict").

    ``resolve_origin()`` runs *before* the ``try`` so even a 500 still carries
    the CORS origin header (R9.3); it only reads a module string and cannot
    raise. Routing is case-insensitive via :func:`request_method`:

    * ``OPTIONS`` → :func:`preflight_response` (R2.3).
    * ``POST`` → ``json_response(200, run_claim_pipeline(event), origin)``
      (R2.2, R6.6, R8).
    * ``GET`` or ``""`` (an unreadable method, treated as GET) →
      :func:`html_response` (R2.1, R2.5, R3).
    * anything else → a 405 ``Error_Envelope`` (R2.4).

    A ``ClaimError`` maps to its carried status and message (R7.1). Any other
    exception maps to a fixed 500 ``{"error": "internal error"}`` — no exception
    type, detail, stack trace, email, or OTP (R7.2, R7.4).
    """
    origin = resolve_origin()  # R9.1, R9.2 (before try so a 500 still has CORS, R9.3)
    try:
        method = request_method(event)  # R2 (case-insensitive)
        if method == "OPTIONS":
            return preflight_response(origin)  # R2.3, R9.4
        if method == "POST":
            return json_response(200, run_claim_pipeline(event), origin)  # R2.2, R6.6, R8
        if method in ("GET", ""):  # "" == unreadable → GET (R2.5)
            return html_response(origin)  # R2.1, R3
        return json_response(405, {"error": "method not allowed"}, origin)  # R2.4
    except ClaimError as exc:
        return json_response(exc.status, {"error": exc.message}, origin)  # R7.1
    except Exception:
        # Fixed 500 message, no detail/trace/PII in the response (R7.2, R7.4).
        # Log the traceback for operators (CloudWatch) so an unexpected failure
        # is diagnosable instead of a silent 500. ``exc_info=True`` records only
        # the exception type, its message, and the stack — NOT the request
        # event, email, or OTP — so no PII leaks into the logs (R7.4). The
        # participant still receives the fixed, detail-free envelope below.
        logger.exception("unhandled error while serving claim request")
        return json_response(500, {"error": "internal error"}, origin)
