"""Shared pytest configuration for the claim-service test suite.

Makes the operator scripts under ``claim-service/scripts/`` and the Lambda
sources under ``claim-service/lambda/`` importable from tests without
installing the subtree as a package. Both directories are prepended to
``sys.path`` so tests can ``import seed_claim_pool`` / ``import claim_handler``
directly.

Keep this additive: sibling test tasks extend the same shim rather than
replacing it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_CLAIM_SERVICE_ROOT = Path(__file__).resolve().parent.parent

for _subdir in ("scripts", "lambda"):
    _path = str(_CLAIM_SERVICE_ROOT / _subdir)
    if _path not in sys.path:
        sys.path.insert(0, _path)

# The handler reads its region from AWS_REGION (never hardcoded). On Lambda the
# runtime always sets it; under test it is not set, so pin it here before the
# handler module is imported. This mirrors the Lambda environment and gives the
# moto-backed DynamoDB client a concrete region to resolve to.
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-southeast-1")
