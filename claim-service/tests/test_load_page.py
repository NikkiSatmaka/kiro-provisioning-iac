"""Unit/example tests for the read-once page loader ``_load_page``.

Validates: Requirements 3.1, 3.2
Design: Testing Strategy > "Dual approach"; the ``_load_page`` contract;
Testing Strategy > "Reading index.html in tests".

``claim_handler._load_page`` reads the packaged ``index.html`` from the module
global ``_PAGE_PATH`` once, caches it in ``_PAGE_HTML``, and returns the cached
value on every warm call (the same lazy memoization style as ``_table``). This
module exercises two contracts:

* **R3.1 — the GET body is the on-disk page.** ``_load_page()`` returns the
  exact, byte-identical contents of ``index.html`` resolved relative to the
  handler module, so the GET response body is the real page and not a
  transformed copy.
* **R3.2 — read-once.** The file is read only on the first call; every
  subsequent call returns the cached string without touching the filesystem.

Two harness notes, mirrored from the sibling ``test_config_reads.py`` /
``conftest.py`` conventions:

* ``_PAGE_HTML`` is module-level state shared across the session, so each test
  resets ``claim_handler._PAGE_HTML = None`` (via a fixture) to re-exercise the
  first-read path and to leave the singleton clean for later tests.
* Locally ``index.html`` is **not** a sibling of ``claim_handler.py`` — it lives
  under ``claim-service/frontend/index.html`` and is only co-located with the
  handler at deploy time, so ``_PAGE_PATH`` points at a path that does not exist
  under test. Tests that drive ``_load_page`` therefore ``monkeypatch`` the
  module global ``claim_handler._PAGE_PATH`` to a real temp file, rather than
  relying on the deploy-time layout.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import claim_handler
import pytest


@pytest.fixture(autouse=True)
def _reset_page_cache() -> Iterator[None]:
    """Reset the read-once page cache around every test.

    ``_PAGE_HTML`` is module-level state; clearing it before and after each test
    re-exercises the first-read path and keeps the shared ``claim_handler``
    singleton clean for sibling test modules that run later in the session.
    """
    claim_handler._PAGE_HTML = None
    try:
        yield
    finally:
        claim_handler._PAGE_HTML = None


# Resolve the packaged page the same way the handler does — relative to the
# claim_handler module — so the "on-disk GET body" assertions compare against
# the real deployed page, wherever it ships (design: "Reading index.html in
# tests").
_FRONTEND_INDEX = os.path.join(
    os.path.dirname(claim_handler.__file__), os.pardir, "frontend", "index.html"
)


def _read_frontend_index() -> str:
    """Return the on-disk ``frontend/index.html`` contents, read directly."""
    with open(_FRONTEND_INDEX, encoding="utf-8") as fh:
        return fh.read()


# --- R3.1: _load_page returns the on-disk index.html contents --------------

def test_load_page_returns_file_contents(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``_load_page`` returns the exact contents of the file at ``_PAGE_PATH``.

    The handler reads ``index.html`` with ``encoding="utf-8"`` and returns it
    verbatim; the body it hands to a GET is therefore byte-identical to the
    file on disk (R3.1).
    """
    contents = "<!DOCTYPE html><html><body>claim page</body></html>\n"
    page = tmp_path / "index.html"
    page.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(claim_handler, "_PAGE_PATH", str(page))

    assert claim_handler._load_page() == contents


def test_load_page_body_equals_packaged_index_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The GET body equals the packaged ``frontend/index.html`` (R3.1, R3.2).

    Point ``_PAGE_PATH`` at the real ``frontend/index.html`` (its deploy-time
    co-location with the handler) and assert ``_load_page`` returns it
    byte-for-byte, so a GET serves the actual claim page unchanged.
    """
    expected = _read_frontend_index()
    monkeypatch.setattr(claim_handler, "_PAGE_PATH", _FRONTEND_INDEX)

    assert claim_handler._load_page() == expected


def test_load_page_preserves_contents_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``_load_page`` performs no transformation on the page contents (R3.1).

    Non-ASCII and whitespace survive the round trip, confirming the loader
    returns the file verbatim rather than normalizing or re-encoding it.
    """
    contents = "<p>café — \u2713 \t trailing spaces  \n\n</p>"
    page = tmp_path / "index.html"
    page.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(claim_handler, "_PAGE_PATH", str(page))

    assert claim_handler._load_page() == contents


# --- R3.2: read-once memoization -------------------------------------------

def test_load_page_caches_contents_in_module_global(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The first call populates the ``_PAGE_HTML`` module cache (R3.2)."""
    contents = "<html>cached</html>"
    page = tmp_path / "index.html"
    page.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(claim_handler, "_PAGE_PATH", str(page))

    assert claim_handler._PAGE_HTML is None  # fixture reset it
    returned = claim_handler._load_page()
    assert claim_handler._PAGE_HTML == contents
    assert returned == contents


def test_load_page_reads_file_only_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The file is opened once; warm calls return the cache (R3.2).

    Spy on the ``open`` the handler module uses: the first ``_load_page`` reads
    the file, but a second call must return the cached string without opening
    the file again.
    """
    contents = "<html>read once</html>"
    page = tmp_path / "index.html"
    page.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(claim_handler, "_PAGE_PATH", str(page))

    open_calls = {"count": 0}
    real_open = open

    def counting_open(*args, **kwargs):
        open_calls["count"] += 1
        return real_open(*args, **kwargs)

    # Patch the builtins the module resolves ``open`` through; _load_page's
    # ``open(...)`` goes through this spy.
    monkeypatch.setattr("builtins.open", counting_open)

    first = claim_handler._load_page()
    second = claim_handler._load_page()

    assert open_calls["count"] == 1  # read-once: only the first call opened it
    assert first == contents
    assert second == contents


def test_load_page_returns_cached_value_after_file_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A warm call returns the cached contents even if the file changes (R3.2).

    Mutating ``index.html`` after the first read must not change what
    ``_load_page`` returns — the warm invocation serves the memoized string,
    proving it did not re-read the file.
    """
    page = tmp_path / "index.html"
    page.write_text("<html>original</html>", encoding="utf-8")
    monkeypatch.setattr(claim_handler, "_PAGE_PATH", str(page))

    first = claim_handler._load_page()
    assert first == "<html>original</html>"

    # Change the file on disk; a re-reading loader would pick this up.
    page.write_text("<html>MUTATED</html>", encoding="utf-8")

    assert claim_handler._load_page() == "<html>original</html>"


def test_load_page_returns_cached_value_after_file_removed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A warm call still succeeds after the file is deleted (R3.2).

    Once the page is cached, deleting the backing file does not break a warm
    read — the second call never touches the filesystem.
    """
    page = tmp_path / "index.html"
    page.write_text("<html>warm</html>", encoding="utf-8")
    monkeypatch.setattr(claim_handler, "_PAGE_PATH", str(page))

    first = claim_handler._load_page()
    assert first == "<html>warm</html>"

    page.unlink()  # a re-reading loader would now raise OSError

    assert claim_handler._load_page() == "<html>warm</html>"
