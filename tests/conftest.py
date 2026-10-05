"""Shared pytest configuration for the repo-root test suite.

Feature: idc-region-account-mapping, Task 1.3

Makes the local test helpers (``_env_assembler``) importable from the test
modules without installing ``tests/`` as a package, mirroring the additive
``sys.path`` shim the claim-service suite uses (claim-service/tests/conftest.py).
It also exposes the subscription operator scripts under
``subscription/scripts/`` so renderer tests can ``import
provision_passwords_and_output`` directly (Task 4.x).
Keep this additive: sibling test tasks extend the same shim rather than
replacing it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

# Make the subscription operator scripts importable from the renderer property
# tests (Properties 2, 3, 5, 6) without installing the subtree as a package, so
# tests can ``import provision_passwords_and_output`` directly. Mirrors the
# additive shim the claim-service suite uses (claim-service/tests/conftest.py).
# Keep this additive: sibling test tasks extend the same shim rather than
# replacing it.
_REPO_ROOT = _TESTS_DIR.parent
_SUBSCRIPTION_SCRIPTS = _REPO_ROOT / "subscription" / "scripts"
if str(_SUBSCRIPTION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SUBSCRIPTION_SCRIPTS))

# The credentials renderer lives at subscription/scripts/; expose it so renderer
# tests can import it without packaging the subtree (mirrors the claim-service
# shim). Additive: later tasks reuse this same entry.
_REPO_ROOT = _TESTS_DIR.parent
_SUBSCRIPTION_SCRIPTS = str(_REPO_ROOT / "subscription" / "scripts")
if _SUBSCRIPTION_SCRIPTS not in sys.path:
    sys.path.insert(0, _SUBSCRIPTION_SCRIPTS)
