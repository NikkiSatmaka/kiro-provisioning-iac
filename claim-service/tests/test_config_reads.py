"""Unit/example tests for the handler's import-time configuration reads.

Validates: Requirements 4.1, 4.2
Design: Testing Strategy > "Dual approach" (unit/example tests for import-time
config reads).

``claim_handler`` reads two config values from the environment at import time:

* ``WORKSHOP_CODE`` -> ``CONFIGURED_WORKSHOP_CODE`` (Requirement 4.1)
* ``ALLOWED_ORIGIN`` -> ``ALLOWED_ORIGIN``, defaulting to ``""`` when unset
  (Requirement 4.2)

Because those reads happen *at import*, exercising them under different
environments means re-running the module's top-level code under a patched
``os.environ``. A plain ``importlib.reload(claim_handler)`` would do that, but
it also rebinds module-level classes (notably ``ClaimError``) to brand-new
objects, breaking ``except claim_handler.ClaimError`` / ``from claim_handler
import ClaimError`` identity in sibling test modules that run later in the same
session (this is the documented trap in ``test_claim_transaction.py`` /
``test_per_ip_cap_property.py``).

To re-exercise the import-time reads safely, these tests load the handler
*source* into a throwaway, isolated module object under a patched environment
and inspect that fresh instance, leaving the shared ``claim_handler`` singleton
(and its ``ClaimError`` identity) untouched.
"""

from __future__ import annotations

import importlib.util
import os
from types import ModuleType

import claim_handler

# Resolve the handler source once; the isolated loader reads this exact file so
# it exercises the same top-level config reads the real module runs on import.
_HANDLER_SOURCE = claim_handler.__file__


def _load_isolated_handler(env: dict[str, str]) -> ModuleType:
    """Load the handler source as a fresh module under a patched environment.

    Only the keys in ``env`` are set/overridden for the duration of the load;
    everything else (notably ``AWS_REGION``, pinned by ``conftest.py``) is left
    in place so boto3 resolution still works. A key mapped to ``None`` is
    removed so the "unset" branch of ``os.environ.get(..., default)`` runs.

    The returned module is not registered in ``sys.modules``, so the shared
    ``claim_handler`` singleton other tests imported is unaffected.
    """
    saved: dict[str, str | None] = {}
    try:
        for key, value in env.items():
            saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        spec = importlib.util.spec_from_file_location(
            "claim_handler_isolated_config_probe", _HANDLER_SOURCE
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # runs the module's import-time reads
        return module
    finally:
        # Restore the environment exactly as it was before the load.
        for key, previous in saved.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


# --- Requirement 4.1: WORKSHOP_CODE -> CONFIGURED_WORKSHOP_CODE ------------

def test_workshop_code_is_read_from_environment() -> None:
    """A set ``WORKSHOP_CODE`` lands in ``CONFIGURED_WORKSHOP_CODE`` (R4.1)."""
    module = _load_isolated_handler({"WORKSHOP_CODE": "swordfish-2024"})
    assert module.CONFIGURED_WORKSHOP_CODE == "swordfish-2024"


def test_workshop_code_defaults_to_empty_when_unset() -> None:
    """An unset ``WORKSHOP_CODE`` defaults to ``""`` (R4.1).

    An empty configured code makes every submitted code mismatch under the
    constant-time compare, so the default is a safe, closed state.
    """
    module = _load_isolated_handler({"WORKSHOP_CODE": None})
    assert module.CONFIGURED_WORKSHOP_CODE == ""


# --- Requirement 4.2: ALLOWED_ORIGIN -> ALLOWED_ORIGIN --------------------

def test_allowed_origin_is_read_from_environment() -> None:
    """A set ``ALLOWED_ORIGIN`` lands in ``ALLOWED_ORIGIN`` (R4.2)."""
    module = _load_isolated_handler(
        {"ALLOWED_ORIGIN": "https://workshop.example.com"}
    )
    assert module.ALLOWED_ORIGIN == "https://workshop.example.com"


def test_allowed_origin_defaults_to_empty_when_unset() -> None:
    """An unset ``ALLOWED_ORIGIN`` defaults to ``""`` (R4.2).

    The empty default is the documented sentinel that ``resolve_origin`` later
    maps to the ``"*"`` wildcard.
    """
    module = _load_isolated_handler({"ALLOWED_ORIGIN": None})
    assert module.ALLOWED_ORIGIN == ""


def test_both_config_values_read_independently() -> None:
    """Both reads coexist on a single import without cross-contamination."""
    module = _load_isolated_handler(
        {
            "WORKSHOP_CODE": "code-abc",
            "ALLOWED_ORIGIN": "https://app.example.org",
        }
    )
    assert module.CONFIGURED_WORKSHOP_CODE == "code-abc"
    assert module.ALLOWED_ORIGIN == "https://app.example.org"


def test_shared_module_singleton_is_untouched_by_isolated_loads() -> None:
    """Isolated loads must not rebind the shared module (ClaimError trap).

    Guards the harness invariant other test modules depend on: probing the
    config reads in a throwaway module leaves ``claim_handler`` — and its
    ``ClaimError`` identity — exactly as imported.
    """
    original_claim_error = claim_handler.ClaimError
    _load_isolated_handler({"WORKSHOP_CODE": "transient", "ALLOWED_ORIGIN": None})
    assert claim_handler.ClaimError is original_claim_error
