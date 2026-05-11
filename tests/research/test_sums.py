import pytest

from bluegrass.engine.intake import EngineResult
from bluegrass.research.refresh import refresh_from_result
from bluegrass.research.stats_store import reset_stats_state
from bluegrass.research.sums import (
    SUM_STRAIGHT_QUANT,
    ROOT_STRAIGHT_QUANT,
    build_root_sums_board,
    build_sums_board,
    digit_sum,
    expected_gap,
    root_sum,
)


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


def _draw(result: str, session: str = "Midday", date: str = "2026-05-01") -> EngineResult:
    return EngineResult(date=date, session=session, result=result,
                        jurisdiction="GA", game_family="Pick 3")


# ---------------------------------------------------------------------------
# Pure math
# ---------------------------------------------------------------------------

def test_digit_sum_basic() -> None:
    assert digit_sum("123") == 6
    assert digit_sum("000") == 0
    assert digit_sum("999") == 27


def test_digit_sum_leading_zeros() -> None:
    assert digit_sum("007") == 7
    assert digit_sum("012") == 3


def test_root_sum_zero() -> None:
    assert root_sum("000") == 0


def test_root_sum_multiples_of_nine_become_nine() -> None:
    assert root_sum("999") == 9   # 27 → 9
    assert root_sum("900") == 9   # 9 → 9
    assert root_sum("360") == 9   # 9 → 9


def test_root_sum_non_multiple() -> None:
    assert root_sum("123") == 6   # 6
    assert root_sum("456") == 6   # 15 → 6


def test_root_sum_full_range() -> None:
    for i in range(1000):
        val = str(i).zfill(3)
        rs = root_sum(val)
        assert 0 <= rs <= 9, f"root_sum({val!r}) = {rs} out of 0-9 range"


# ---------------------------------------------------------------------------
# Canonical tables
# ---------------------------------------------------------------------------

def test_sum_quant_covers_all_pick3_sums() -> None:
    assert set(SUM_STRAIGHT_QUANT.keys()) == set(range(28))


def test_sum_quant_totals_1000() -> None:
    assert sum(SUM_STRAIGHT_QUANT.values()) == 1000


def test_root_quant_covers_all_roots() -> None:
    assert set(ROOT_STRAIGHT_QUANT.keys()) == set(range(10))


def test_root_quant_totals_1000() -> None:
    assert sum(ROOT_STRAIGHT_QUANT.values()) == 1000


def test_expected_gap_sum14() -> None:
    # sum 14 has 75 combos → expected gap = 1000/75 ≈ 13.33
    assert abs(expected_gap(75) - 13.33) < 0.01


def test_expected_gap_sum0() -> None:
    # sum 0 has 1 combo (000) → expected gap = 1000
    assert expected_gap(1) == 1000.0


# ---------------------------------------------------------------------------
# Cold-state board behaviour (no runtime draws processed yet)
# ---------------------------------------------------------------------------

def test_sums_board_non_empty() -> None:
    assert len(build_sums_board("Midday")) == 28


def test_root_sums_board_non_empty() -> None:
    assert len(build_root_sums_board("Evening")) == 10


def test_sums_board_covers_all_pick3_sums() -> None:
    board = build_sums_board("Midday")
    assert {int(r["value"]) for r in board} == set(range(28))


def test_root_sums_board_covers_all_roots() -> None:
    board = build_root_sums_board("Night")
    assert {int(r["value"]) for r in board} == set(range(10))


def test_sums_board_sorted_descending() -> None:
    board = build_sums_board("Midday")
    ds = [r["draws_since"] for r in board]
    assert ds == sorted(ds, reverse=True)


def test_root_sums_board_sorted_descending() -> None:
    board = build_root_sums_board("Evening")
    ds = [r["draws_since"] for r in board]
    assert ds == sorted(ds, reverse=True)


def test_sums_board_limit() -> None:
    assert len(build_sums_board("Midday", limit=5)) == 5


def test_root_sums_board_limit() -> None:
    assert len(build_root_sums_board("Night", limit=3)) == 3


def test_sums_board_entry_shape() -> None:
    row = build_sums_board("Evening", limit=1)[0]
    assert row["family"] == "sum"
    assert "value" in row
    assert "draws_since" in row
    assert "last_seen" in row
    assert "expected_gap_draws" in row
    assert "analysis_window_days" in row
    assert row["session"] == "Evening"


def test_root_sums_board_entry_shape() -> None:
    row = build_root_sums_board("Midday", limit=1)[0]
    assert row["family"] == "root_sum"
    assert row["session"] == "Midday"
    assert "expected_gap_draws" in row
    assert "analysis_window_days" in row


# ---------------------------------------------------------------------------
# Engine-runtime draws_since correctness — the core invariant
# ---------------------------------------------------------------------------

def test_cold_board_all_draws_since_zero() -> None:
    """With no processed draws, every draws_since must be 0 (draws_processed = 0)."""
    board = build_sums_board("Midday")
    assert all(r["draws_since"] == 0 for r in board)


def test_draws_since_never_uses_baseline_values() -> None:
    """draws_since must never contain lotterypost snapshot values (e.g. 827 for sum 1)."""
    board = build_sums_board("Midday")
    # Even on cold state, no value should exceed 0 — not 827, 626, or any baseline number
    assert all(r["draws_since"] == 0 for r in board)


def test_unseen_sum_gets_draws_processed() -> None:
    """A sum never produced by any processed draw shows draws_since == draws_processed."""
    # Process 5 draws all producing sum=6 ("123"). Sum=27 ("999") never appears.
    for i in range(5):
        refresh_from_result(_draw("123", date=f"2026-05-{i+1:02d}"))

    board = build_sums_board("Midday")
    sum27 = next(r for r in board if r["value"] == "27")
    assert sum27["draws_since"] == 5   # draws_processed, not any baseline value


def test_hit_sum_resets_to_zero() -> None:
    """A sum just produced has draws_since == 0."""
    refresh_from_result(_draw("123"))   # sum = 6

    board = build_sums_board("Midday")
    sum6 = next(r for r in board if r["value"] == "6")
    assert sum6["draws_since"] == 0


def test_hit_sum_ages_correctly() -> None:
    """After a hit, subsequent draws age the sum by 1 each."""
    refresh_from_result(_draw("123", date="2026-05-01"))   # sum=6 hits, draws_since=0
    refresh_from_result(_draw("456", date="2026-05-02"))   # sum=15 hits; sum=6 ages to 1
    refresh_from_result(_draw("789", date="2026-05-03"))   # sum=24 hits; sum=6 ages to 2

    board = build_sums_board("Midday")
    sum6 = next(r for r in board if r["value"] == "6")
    assert sum6["draws_since"] == 2


def test_unseen_root_sum_gets_draws_processed() -> None:
    """A root_sum never seen in runtime shows draws_since == draws_processed."""
    # "111" → digit_sum=3, root_sum=3. Process 4 of them.
    for i in range(4):
        refresh_from_result(_draw("111", date=f"2026-05-{i+1:02d}"))

    board = build_root_sums_board("Midday")
    # root_sum 7 never appeared → draws_since should be 4
    root7 = next(r for r in board if r["value"] == "7")
    assert root7["draws_since"] == 4


def test_analysis_window_days_surfaced_per_row() -> None:
    board = build_sums_board("Midday", analysis_window_days=250)
    assert all(r["analysis_window_days"] == 250 for r in board)


def test_analysis_window_days_custom_value() -> None:
    board = build_sums_board("Evening", analysis_window_days=150)
    assert all(r["analysis_window_days"] == 150 for r in board)


def test_sessions_are_independent() -> None:
    """draws_since for Midday should not bleed into Evening."""
    for i in range(10):
        refresh_from_result(_draw("123", session="Midday", date=f"2026-05-{i+1:02d}"))

    midday_board = build_sums_board("Midday")
    evening_board = build_sums_board("Evening")

    midday_sum6 = next(r for r in midday_board if r["value"] == "6")
    evening_sum6 = next(r for r in evening_board if r["value"] == "6")

    assert midday_sum6["draws_since"] == 0   # just hit in Midday
    assert evening_sum6["draws_since"] == 0  # Evening has 0 processed draws → draws_since=0

