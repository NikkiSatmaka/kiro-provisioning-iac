"""Property test for invalid-row handling in the seed script.

Feature: credential-claim-service, Property 10

Property 10 — Invalid seed rows are reported and skipped:
A row of ``otps.csv`` that is missing a username OR an OTP (after trimming
surrounding whitespace) must be classified as an ``InvalidRow`` carrying a
reason, and must NEVER produce a ``SeedRow``. In a mixed file, the valid and
invalid rows partition the input exactly, preserving order.

Validates: Requirements 6.3
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

# ``seed_claim_pool`` is importable because the test conftest adds
# ``claim-service/scripts`` to ``sys.path`` (scripts-import shim).
from seed_claim_pool import (
    Classification,
    InvalidRow,
    SeedRow,
    classify_rows,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# A value that is "blank" from classify_row's point of view: empty, or only
# whitespace (which trims to empty). Includes the field being absent entirely,
# modelled separately below.
_blank_values = st.sampled_from(["", " ", "\t", "   ", "\n", " \t \n "])

# A value that is non-blank after trimming (so it counts as present). We keep
# it simple but allow surrounding whitespace to exercise the trim.
_present_core = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc"), blacklist_characters="\n\r"),
    min_size=1,
    max_size=12,
).filter(lambda s: s.strip() != "")
_present_values = st.builds(
    lambda core, lpad, rpad: f"{lpad}{core}{rpad}",
    _present_core,
    st.sampled_from(["", " ", "  ", "\t"]),
    st.sampled_from(["", " ", "  ", "\t"]),
)


def _row(username: str | None, otp: str | None) -> dict[str, str]:
    """Build a DictReader-style row, omitting a field when its value is None."""
    row: dict[str, str] = {}
    if username is not None:
        row["username"] = username
    if otp is not None:
        row["otp"] = otp
    return row


# A field is either present (non-blank), blank, or absent (None).
_present_field = _present_values
_missing_field = st.one_of(_blank_values, st.none())

# An invalid row: at least one of username/otp is missing (blank or absent).
# Enumerate the three missing-combinations so each is well represented.
_invalid_rows = st.one_of(
    st.builds(_row, _missing_field, _present_field),   # missing username
    st.builds(_row, _present_field, _missing_field),   # missing otp
    st.builds(_row, _missing_field, _missing_field),   # missing both
)

# A valid row: both fields present (non-blank after trim).
_valid_rows = st.builds(_row, _present_field, _present_field)

# A mixed row is either kind.
_any_rows = st.one_of(_valid_rows, _invalid_rows)


def _is_valid(raw: dict[str, str]) -> bool:
    """Reference oracle: a row is valid iff both username and otp trim non-empty."""
    return bool((raw.get("username") or "").strip()) and bool(
        (raw.get("otp") or "").strip()
    )


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(_invalid_rows)
def test_invalid_row_is_reported_and_never_seeded(raw: dict[str, str]) -> None:
    """Any single row missing a username or OTP lands in ``invalid`` with a
    reason and yields no ``SeedRow``. Validates: Requirements 6.3."""
    result = classify_rows([raw])

    # No credential is produced for an invalid row.
    assert result.valid == []
    # Exactly one invalid entry, reported with a non-empty reason and the raw row.
    assert len(result.invalid) == 1
    bad = result.invalid[0]
    assert isinstance(bad, InvalidRow)
    assert bad.reason.strip() != ""
    assert bad.line == 1
    assert bad.raw == raw


@settings(max_examples=200)
@given(st.lists(_any_rows, max_size=25))
def test_mixed_rows_partition_correctly(rows: list[dict[str, str]]) -> None:
    """Valid and invalid rows partition the input exactly, preserving order, and
    only non-blank-both rows become ``SeedRow``s. Validates: Requirements 6.3."""
    result = classify_rows(rows)
    assert isinstance(result, Classification)

    # Partition is exhaustive and disjoint: every input row is accounted for once.
    assert len(result.valid) + len(result.invalid) == len(rows)

    expected_valid = [r for r in rows if _is_valid(r)]
    expected_invalid = [r for r in rows if not _is_valid(r)]
    assert len(result.valid) == len(expected_valid)
    assert len(result.invalid) == len(expected_invalid)

    # Every reported valid row is a SeedRow with trimmed, non-empty fields.
    for seed in result.valid:
        assert isinstance(seed, SeedRow)
        assert seed.username == seed.username.strip()
        assert seed.username != ""
        assert seed.otp == seed.otp.strip()
        assert seed.otp != ""

    # Every reported invalid row carries a reason; none of them would have been
    # a valid row, and line numbers are 1-based and strictly increasing.
    for bad in result.invalid:
        assert isinstance(bad, InvalidRow)
        assert bad.reason.strip() != ""
        assert not _is_valid(bad.raw)
    lines = [bad.line for bad in result.invalid]
    assert all(1 <= ln <= len(rows) for ln in lines)
    assert lines == sorted(lines)
    assert len(set(lines)) == len(lines)
