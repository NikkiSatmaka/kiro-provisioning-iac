"""Credential Claim Service Lambda handler.

Served by a single AWS Lambda Function URL: GET returns the claim page, POST
runs the claim pipeline. This module is built up across several tasks; this
first slice provides the email + request helpers that later layers build on.

PII note: a normalized email is the sole key-derivation for an email and is
stored only in the ``EMAIL#`` item and the credential's ``claimed_by_email``
attribute. Raw emails and OTPs are never logged.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime

import boto3
from boto3.dynamodb.conditions import Attr

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

    1. Picks an available credential via :func:`pick_available`; raises
       ``ClaimError(409)`` when the pool is exhausted (Requirement 5.1).
    2. Commits a single ``TransactWriteItems`` holding **both** uniqueness
       checks (design: "The claim transaction", Requirement 2.3):
         * a conditional ``Put`` of ``EMAIL#<email>`` guarded by
           ``attribute_not_exists(PK)`` — one claim per email (Req 2.2 / 8.2);
         * a conditional ``Update`` of ``CRED#<username>`` guarded by
           ``status = "available"`` — one claim per credential (Req 2.1 / 8.1).

    There is **no read-then-write** on either uniqueness constraint: correctness
    lives entirely in the transaction's conditions, so concurrent claims can
    neither double-assign a credential nor let an email claim twice
    (Requirement 8.3).

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

    # One pick + transaction per iteration; a credential conflict re-picks and
    # retries, so the loop runs at most RETRY_BOUND times (Requirement 2.4).
    for _attempt in range(RETRY_BOUND):
        username = pick_available()
        if username is None:
            raise ClaimError(409, "all claimed")

        claimed_at = datetime.now(UTC).isoformat()

        try:
            client.transact_write_items(
                TransactItems=[
                    {
                        # One claim per email: fails if this email already
                        # holds a lock.
                        "Put": {
                            "TableName": TABLE_NAME,
                            "Item": {
                                "PK": {"S": f"EMAIL#{email}"},
                                "username": {"S": username},
                                "claimed_at": {"S": claimed_at},
                            },
                            "ConditionExpression": "attribute_not_exists(PK)",
                        },
                    },
                    {
                        # One claim per credential: fails if it was taken since
                        # the pick.
                        "Update": {
                            "TableName": TABLE_NAME,
                            "Key": {"PK": {"S": f"CRED#{username}"}},
                            "UpdateExpression": (
                                "SET #status = :claimed, "
                                "claimed_by_email = :email, "
                                "claimed_at = :claimed_at"
                            ),
                            "ConditionExpression": "#status = :available",
                            "ExpressionAttributeNames": {"#status": "status"},
                            "ExpressionAttributeValues": {
                                ":claimed": {"S": "claimed"},
                                ":available": {"S": "available"},
                                ":email": {"S": email},
                                ":claimed_at": {"S": claimed_at},
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
