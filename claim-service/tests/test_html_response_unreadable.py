"""Unit/example test for the index.html-unreadable -> 500 edge (R3.3).

Validates: Requirements 3.3
Design: Testing Strategy > "Reading index.html in tests" (read-failure edge);
``html_response`` OSError -> 500 path.

When the packaged ``index.html`` cannot be read, ``claim_handler._load_page``
raises ``OSError``. ``html_response(origin)`` must catch that and return a 500
``Error_Envelope`` (``{"error": ...}``) with the uniform CORS + JSON headers
rather than letting the failure escape (R3.3). This module drives that path
directly through ``html_response`` — it does not require the ``handler``
entrypoint, since ``html_response`` is the function that owns the OSError map.

Harness notes (mirrored from ``test_load_page.py`` / ``conftest.py``):

* ``_PAGE_HTML`` is module-level read-once state shared across the session, so
  each test resets ``claim_handler._PAGE_HTML = None`` (via a fixture) to force
  ``_load_page`` down its first-read path, and restores it afterwards so sibling
  modules see a clean singleton.
* "Unreadable" is simulated two ways: by pointing ``_PAGE_PATH`` at a path that
  does not exist (``_load_page``'s ``open`` raises ``FileNotFoundError``, an
  ``OSError`` subclass), and by monkeypatching ``_load_page`` itself to raise a
  bare ``OSError`` — both exercise the same ``except OSError`` branch.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

import claim_handler
import pytest


@pytest.fixture(autouse=True)
def _reset_page_cache() -> Iterator[None]:
    """Reset the read-once page cache around every test.

    ``_PAGE_HTML`` is module-level state; clearing it before and after each test
    re-exercises the first-read (and thus the read-failure) path and keeps the
    shared ``claim_handler`` singleton clean for sibling test modules.
    """
    claim_handler._PAGE_HTML = None
    try:
        yield
    finally:
        claim_handler._PAGE_HTML = None


def _assert_500_error_envelope(response: dict, origin: str) -> None:
    """Assert ``response`` is the uniform 500 Error_Envelope for ``origin``.

    A 500 ``Error_Envelope`` is: ``statusCode`` 500, a string ``body`` that is
    a JSON object carrying an ``"error"`` key, ``Content-Type:
    application/json``, and exactly one ``Access-Control-Allow-Origin`` equal to
    the passed ``origin`` (R3.3; the single-ACAO CORS contract).
    """
    assert response["statusCode"] == 500

    # Body is a JSON string decoding to an object with an "error" key (R3.3).
    body = response["body"]
    assert isinstance(body, str)
    parsed = json.loads(body)
    assert isinstance(parsed, dict)
    assert "error" in parsed

    # Uniform CORS + JSON headers.
    headers = response["headers"]
    assert headers["Content-Type"] == "application/json"
    assert headers["Access-Control-Allow-Origin"] == origin


# --- R3.3: unreadable index.html -> 500 via a nonexistent _PAGE_PATH -------

def test_html_response_returns_500_when_page_path_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A nonexistent ``_PAGE_PATH`` yields a 500 Error_Envelope (R3.3).

    Point ``_PAGE_PATH`` at a path that does not exist and reset the read-once
    cache so ``_load_page`` performs a real ``open`` and raises
    ``FileNotFoundError`` (an ``OSError``); ``html_response`` must catch it and
    return the 500 envelope rather than propagating.
    """
    missing = os.path.join(str(tmp_path), "does-not-exist", "index.html")
    monkeypatch.setattr(claim_handler, "_PAGE_PATH", missing)
    claim_handler._PAGE_HTML = None

    origin = claim_handler.resolve_origin()
    response = claim_handler.html_response(origin)

    _assert_500_error_envelope(response, origin)


# --- R3.3: unreadable index.html -> 500 via _load_page raising OSError -----

def test_html_response_returns_500_when_load_page_raises_oserror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_load_page`` raising ``OSError`` yields a 500 Error_Envelope (R3.3).

    Monkeypatch ``_load_page`` to raise a bare ``OSError`` (e.g. a permission
    error at read time); ``html_response`` must map it to the uniform 500
    envelope with CORS + ``application/json``.
    """

    def _raise_oserror() -> str:
        raise OSError("index.html is unreadable")

    monkeypatch.setattr(claim_handler, "_load_page", _raise_oserror)

    origin = claim_handler.resolve_origin()
    response = claim_handler.html_response(origin)

    _assert_500_error_envelope(response, origin)


def test_html_response_500_echoes_passed_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 500 envelope echoes the exact ``origin`` passed in (R3.3, CORS).

    ``html_response`` funnels its ACAO through the ``origin`` argument, so an
    explicit non-wildcard origin must appear verbatim on the error response —
    even a 500 carries the caller's CORS origin.
    """

    def _raise_oserror() -> str:
        raise OSError("unreadable")

    monkeypatch.setattr(claim_handler, "_load_page", _raise_oserror)

    origin = "https://workshop.example.com"
    response = claim_handler.html_response(origin)

    _assert_500_error_envelope(response, origin)
    assert response["headers"]["Access-Control-Allow-Origin"] == origin
