"""moto-backed purge/isolation tests for the per-workshop state cleanup script.

Feature: backend-destroy-workshop, FEAT-001

These tests exercise the REAL ``backend/scripts/destroy_workshop_state.sh`` end
to end. The script shells out to the AWS CLI, which moto's in-process
``mock_aws`` does NOT intercept (it only patches in-process boto3). So instead
of ``mock_aws`` we stand up a ``moto.server.ThreadedMotoServer`` and point BOTH
the subprocess (via ``AWS_ENDPOINT_URL`` + dummy creds + region, honored by AWS
CLI v2) and the boto3 seed/assert clients at the same ``http://127.0.0.1:<port>``
endpoint. The script resolves the shared bucket + lock table from the
STATE_BUCKET / LOCK_TABLE environment contract (the mise task exports them from
the backend/ stack's own Terraform outputs), so the tests pin those two vars to
the moto fixtures instead of writing a backend.hcl.

The cases prove the cleanup is surgical:

* ``--apply`` purges ONLY the target prefix (zero Versions AND zero
  DeleteMarkers), leaving another workshop's prefix byte-for-byte intact;
* ``--apply`` deletes ONLY the target's lock rows (incl. the ``-md5``
  companion), leaving another workshop's rows;
* a dry run deletes NOTHING for either prefix and prints ``would delete:`` lines;
* an empty target prefix is a no-op success (exit 0);
* a missing bucket/table env contract fails closed (non-zero + stderr) and
  deletes nothing.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import boto3
import pytest
import requests
from moto.server import ThreadedMotoServer

# The dev shell may export AWS_PROFILE/AWS_CONFIG_FILE pointing at a real
# profile (e.g. kiro-mgmt). boto3 consults these the moment a Session is built,
# so drop them for THIS test process before any client is created — moto accepts
# any credentials and we pin dummy static ones below. (The subprocess env is
# scrubbed separately in _run_script.)
for _var in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_CONFIG_FILE",
             "AWS_SHARED_CREDENTIALS_FILE"):
    os.environ.pop(_var, None)

# Root conftest does NOT pin a region (unlike the claim-service conftest), so
# set one before any boto3 client is built. setdefault lets an ambient region win.
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
REGION = os.environ.get("AWS_REGION", "us-east-1")

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "backend" / "scripts" / "destroy_workshop_state.sh"

BUCKET = "kiro-tofu-state-000000000000"
TABLE = "kiro-tofu-locks"
STACKS = ("subscription", "governance")


# --- moto server fixture -----------------------------------------------------

@pytest.fixture
def moto_endpoint():
    """Start a ThreadedMotoServer and yield its base URL (stopped on teardown).

    moto keeps its backends in PROCESS-global state, so a fresh server instance
    alone does not clear seeded buckets/tables between tests. Reset the backends
    on both entry and exit so each test starts from a clean slate.
    """
    server = ThreadedMotoServer(port=0)
    server.start()
    host, port = server.get_host_and_port()
    endpoint = f"http://{host}:{port}"
    requests.post(f"{endpoint}/moto-api/reset")
    try:
        yield endpoint
    finally:
        requests.post(f"{endpoint}/moto-api/reset")
        server.stop()


# A dedicated session with dummy static creds so the test clients never consult
# the ambient AWS profile/credentials (the dev shell may export AWS_PROFLE); the
# moto server accepts any credentials.
_SESSION = boto3.session.Session(
    aws_access_key_id="testing",
    aws_secret_access_key="testing",
    aws_session_token="testing",
    region_name=REGION,
)


@pytest.fixture
def s3(moto_endpoint):
    return _SESSION.client("s3", endpoint_url=moto_endpoint)


@pytest.fixture
def ddb(moto_endpoint):
    return _SESSION.client("dynamodb", endpoint_url=moto_endpoint)


# --- seeding helpers ---------------------------------------------------------

def _make_versioned_bucket(client, bucket):
    client.create_bucket(Bucket=bucket)
    client.put_bucket_versioning(
        Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
    )


def _seed_objects(client, bucket, prefix):
    """Seed two keys under ``prefix``: multiple versions AND >=1 delete marker.

    Puts ``<prefix>subscription/terraform.tfstate`` (twice -> two versions) and
    ``<prefix>governance/terraform.tfstate`` (once), then deletes the governance
    key to leave a DELETE MARKER. So the prefix always carries both >1 version
    and >=1 delete marker — the exact shape a versioned backend accumulates.
    """
    key_sub = f"{prefix}subscription/terraform.tfstate"
    key_gov = f"{prefix}governance/terraform.tfstate"
    client.put_object(Bucket=bucket, Key=key_sub, Body=b"v1")
    client.put_object(Bucket=bucket, Key=key_sub, Body=b"v2")
    client.put_object(Bucket=bucket, Key=key_gov, Body=b"g1")
    # Delete without a version id -> creates a delete marker on a versioned bucket.
    client.delete_object(Bucket=bucket, Key=key_gov)


def _make_lock_table(client, table):
    client.create_table(
        TableName=table,
        KeySchema=[{"AttributeName": "LockID", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "LockID", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=table)


def _lock_ids(bucket, wid):
    """The lock rows a workshop leaves: live-lock + -md5 companion per stack."""
    ids = []
    for stack in STACKS:
        base = f"{bucket}/workshops/{wid}/{stack}/terraform.tfstate"
        ids.append(base)
        ids.append(f"{base}-md5")
    return ids


def _seed_locks(client, table, bucket, wid):
    for lock_id in _lock_ids(bucket, wid):
        client.put_item(TableName=table, Item={"LockID": {"S": lock_id}})


# --- assertion helpers -------------------------------------------------------

def _versions_and_markers(client, bucket, prefix):
    resp = client.list_object_versions(Bucket=bucket, Prefix=prefix)
    return resp.get("Versions", []), resp.get("DeleteMarkers", [])


def _all_lock_ids(client, table):
    resp = client.scan(TableName=table, ProjectionExpression="LockID")
    return {item["LockID"]["S"] for item in resp.get("Items", [])}


# --- script runner -----------------------------------------------------------

def _run_script(tmp_path, endpoint, wid, *flags, set_env=True, bucket=BUCKET, table=TABLE):
    """Run the cleanup script in ``tmp_path`` against the moto endpoint.

    The script resolves the shared bucket + lock table from the STATE_BUCKET /
    LOCK_TABLE environment contract (exported by the mise task from the backend
    stack's own Terraform outputs). When ``set_env`` is True (default) both are
    pinned to the moto fixtures; pass ``set_env=False`` to exercise the
    fail-closed path with neither var set.
    """
    env = dict(os.environ)
    # The dev shell may export AWS_PROFILE/AWS_CONFIG_FILE pointing at a real
    # profile the moto subprocess must NOT consult; drop them and pin dummy
    # static creds + the moto endpoint instead.
    for _var in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_CONFIG_FILE",
                 "AWS_SHARED_CREDENTIALS_FILE"):
        env.pop(_var, None)
    # Always start from a clean slate for the bucket/table contract.
    for _var in ("STATE_BUCKET", "LOCK_TABLE"):
        env.pop(_var, None)
    env.update(
        {
            "AWS_ENDPOINT_URL": endpoint,
            "AWS_ACCESS_KEY_ID": "testing",
            "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_SESSION_TOKEN": "testing",
            "AWS_REGION": REGION,
            "AWS_DEFAULT_REGION": REGION,
        }
    )
    if set_env:
        env["STATE_BUCKET"] = bucket
        env["LOCK_TABLE"] = table
    return subprocess.run(
        ["sh", str(SCRIPT), wid, *flags],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


# --- tests -------------------------------------------------------------------

def test_apply_purges_only_target_prefix(s3, ddb, moto_endpoint, tmp_path):
    """``--apply`` empties the target prefix; the other workshop is untouched."""
    _make_versioned_bucket(s3, BUCKET)
    _make_lock_table(ddb, TABLE)
    _seed_objects(s3, BUCKET, "workshops/alpha/")
    _seed_objects(s3, BUCKET, "workshops/beta/")

    # Snapshot beta before the purge to prove byte-for-byte survival.
    beta_v_before, beta_m_before = _versions_and_markers(
        s3, BUCKET, "workshops/beta/"
    )
    beta_vids_before = {(v["Key"], v["VersionId"]) for v in beta_v_before}
    beta_mids_before = {(m["Key"], m["VersionId"]) for m in beta_m_before}
    assert beta_vids_before, "precondition: beta has versions"
    assert beta_mids_before, "precondition: beta has a delete marker"

    proc = _run_script(tmp_path, moto_endpoint, "alpha", "--apply")
    assert proc.returncode == 0, proc.stderr

    alpha_v, alpha_m = _versions_and_markers(s3, BUCKET, "workshops/alpha/")
    assert alpha_v == [], f"alpha versions should be gone: {alpha_v}"
    assert alpha_m == [], f"alpha delete markers should be gone: {alpha_m}"

    beta_v_after, beta_m_after = _versions_and_markers(s3, BUCKET, "workshops/beta/")
    assert {(v["Key"], v["VersionId"]) for v in beta_v_after} == beta_vids_before
    assert {(m["Key"], m["VersionId"]) for m in beta_m_after} == beta_mids_before


def test_apply_deletes_only_target_lock_rows(s3, ddb, moto_endpoint, tmp_path):
    """``--apply`` deletes the target's lock rows (incl. -md5); others remain."""
    _make_versioned_bucket(s3, BUCKET)
    _make_lock_table(ddb, TABLE)
    _seed_locks(ddb, TABLE, BUCKET, "alpha")
    _seed_locks(ddb, TABLE, BUCKET, "beta")

    proc = _run_script(tmp_path, moto_endpoint, "alpha", "--apply")
    assert proc.returncode == 0, proc.stderr

    remaining = _all_lock_ids(ddb, TABLE)
    assert remaining == set(_lock_ids(BUCKET, "beta")), remaining
    # The -md5 companion of each alpha stack is gone, specifically.
    for lock_id in _lock_ids(BUCKET, "alpha"):
        assert lock_id not in remaining
    assert any(lid.endswith("-md5") for lid in remaining), "beta -md5 rows kept"


def test_dry_run_deletes_nothing(s3, ddb, moto_endpoint, tmp_path):
    """A dry run changes nothing and prints ``would delete:`` lines for alpha."""
    _make_versioned_bucket(s3, BUCKET)
    _make_lock_table(ddb, TABLE)
    _seed_objects(s3, BUCKET, "workshops/alpha/")
    _seed_objects(s3, BUCKET, "workshops/beta/")
    _seed_locks(ddb, TABLE, BUCKET, "alpha")
    _seed_locks(ddb, TABLE, BUCKET, "beta")

    alpha_v_before, alpha_m_before = _versions_and_markers(
        s3, BUCKET, "workshops/alpha/"
    )
    beta_v_before, beta_m_before = _versions_and_markers(
        s3, BUCKET, "workshops/beta/"
    )
    locks_before = _all_lock_ids(ddb, TABLE)

    proc = _run_script(tmp_path, moto_endpoint, "alpha")
    assert proc.returncode == 0, proc.stderr
    assert "would delete:" in proc.stdout
    # The dry run names an alpha S3 key and an alpha lock row, not just a banner.
    assert "would delete: s3 workshops/alpha/" in proc.stdout
    assert f"would delete: ddb-lock {BUCKET}/workshops/alpha/" in proc.stdout

    alpha_v_after, alpha_m_after = _versions_and_markers(
        s3, BUCKET, "workshops/alpha/"
    )
    beta_v_after, beta_m_after = _versions_and_markers(
        s3, BUCKET, "workshops/beta/"
    )
    assert {(v["Key"], v["VersionId"]) for v in alpha_v_after} == {
        (v["Key"], v["VersionId"]) for v in alpha_v_before
    }
    assert {(m["Key"], m["VersionId"]) for m in alpha_m_after} == {
        (m["Key"], m["VersionId"]) for m in alpha_m_before
    }
    assert {(v["Key"], v["VersionId"]) for v in beta_v_after} == {
        (v["Key"], v["VersionId"]) for v in beta_v_before
    }
    assert {(m["Key"], m["VersionId"]) for m in beta_m_after} == {
        (m["Key"], m["VersionId"]) for m in beta_m_before
    }
    assert _all_lock_ids(ddb, TABLE) == locks_before


def test_empty_prefix_is_noop_success(s3, ddb, moto_endpoint, tmp_path):
    """An empty target prefix (no objects/rows) is a no-op success (exit 0)."""
    _make_versioned_bucket(s3, BUCKET)
    _make_lock_table(ddb, TABLE)
    # Seed only beta; alpha has nothing.
    _seed_objects(s3, BUCKET, "workshops/beta/")
    _seed_locks(ddb, TABLE, BUCKET, "beta")

    beta_v_before, beta_m_before = _versions_and_markers(s3, BUCKET, "workshops/beta/")
    locks_before = _all_lock_ids(ddb, TABLE)

    proc = _run_script(tmp_path, moto_endpoint, "alpha", "--apply")
    assert proc.returncode == 0, proc.stderr

    beta_v_after, beta_m_after = _versions_and_markers(s3, BUCKET, "workshops/beta/")
    assert {(v["Key"], v["VersionId"]) for v in beta_v_after} == {
        (v["Key"], v["VersionId"]) for v in beta_v_before
    }
    assert {(m["Key"], m["VersionId"]) for m in beta_m_after} == {
        (m["Key"], m["VersionId"]) for m in beta_m_before
    }
    assert _all_lock_ids(ddb, TABLE) == locks_before


def test_missing_bucket_table_env_fails_closed(s3, ddb, moto_endpoint, tmp_path):
    """Neither STATE_BUCKET nor LOCK_TABLE set -> non-zero exit, nothing deleted."""
    _make_versioned_bucket(s3, BUCKET)
    _make_lock_table(ddb, TABLE)
    _seed_objects(s3, BUCKET, "workshops/alpha/")
    _seed_locks(ddb, TABLE, BUCKET, "alpha")

    v_before, m_before = _versions_and_markers(s3, BUCKET, "workshops/alpha/")
    locks_before = _all_lock_ids(ddb, TABLE)

    proc = _run_script(tmp_path, moto_endpoint, "alpha", "--apply", set_env=False)
    assert proc.returncode != 0
    assert "STATE_BUCKET and LOCK_TABLE" in proc.stderr

    v_after, m_after = _versions_and_markers(s3, BUCKET, "workshops/alpha/")
    assert {(v["Key"], v["VersionId"]) for v in v_after} == {
        (v["Key"], v["VersionId"]) for v in v_before
    }
    assert {(m["Key"], m["VersionId"]) for m in m_after} == {
        (m["Key"], m["VersionId"]) for m in m_before
    }
    assert _all_lock_ids(ddb, TABLE) == locks_before
