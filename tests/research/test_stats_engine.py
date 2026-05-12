"""Tests for bluegrass.research.stats_engine — all pure functions, no I/O."""

from __future__ import annotations

import math

import pytest

from bluegrass.research.stats_engine import (
    PAIR_EXPECTED_GAP,
    PAIR_QUANT,
    ROOT_MAX_QUANT,
    SUM_MAX_QUANT,
    compute_deviation_metrics,
    composite_score,
    describe_deviation,
    severity_band,
)
from bluegrass.research.sums import SUM_STRAIGHT_QUANT, ROOT_STRAIGHT_QUANT


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------

def test_sum_max_quant_matches_table() -> None:
    assert SUM_MAX_QUANT == max(SUM_STRAIGHT_QUANT.values())  # 75


def test_root_max_quant_matches_table() -> None:
    assert ROOT_MAX_QUANT == max(ROOT_STRAIGHT_QUANT.values())  # 111


def test_pair_quant_expected_gap_consistent() -> None:
    assert PAIR_EXPECTED_GAP == pytest.approx(1000 / PAIR_QUANT)


# ---------------------------------------------------------------------------
# severity_band thresholds
# ---------------------------------------------------------------------------

def test_severity_recent() -> None:
    assert severity_band(0.0)  == "recent"
    assert severity_band(0.4)  == "recent"


def test_severity_normal() -> None:
    assert severity_band(0.5)  == "normal"
    assert severity_band(1.4)  == "normal"


def test_severity_mild() -> None:
    assert severity_band(1.5) == "mild"
    assert severity_band(2.4) == "mild"


def test_severity_elevated() -> None:
    assert severity_band(2.5) == "elevated"
    assert severity_band(3.9) == "elevated"


def test_severity_strong() -> None:
    assert severity_band(4.0) == "strong"
    assert severity_band(6.9) == "strong"


def test_severity_extreme() -> None:
    assert severity_band(7.0) == "extreme"
    assert severity_band(99.0) == "extreme"


# ---------------------------------------------------------------------------
# compute_deviation_metrics — correctness
# ---------------------------------------------------------------------------

def test_gap_ratio_common_sum_overdue() -> None:
    """Sum 13/14 (quant=75, expected_gap=13.3) absent 50 draws → gap_ratio≈3.75."""
    m = compute_deviation_metrics(draws_since=50, times_drawn=3, draws_processed=100, quant=75)
    assert m["expected_gap_draws"] == pytest.approx(13.3, abs=0.1)
    assert m["gap_ratio"] == pytest.approx(3.75, abs=0.01)
    assert m["severity_band"] in ("elevated", "strong")


def test_gap_ratio_rare_sum_not_overdue() -> None:
    """Sum 0 (quant=1, expected_gap=1000) absent 100 draws → gap_ratio=0.1 (normal/recent)."""
    m = compute_deviation_metrics(draws_since=100, times_drawn=0, draws_processed=100, quant=1)
    assert m["expected_gap_draws"] == 1000.0
    assert m["gap_ratio"] == pytest.approx(0.1, abs=0.001)
    assert m["severity_band"] == "recent"


def test_expected_hits_calculation() -> None:
    """100 draws, quant=75 → expected_hits = 100 * 75/1000 = 7.5."""
    m = compute_deviation_metrics(draws_since=0, times_drawn=8, draws_processed=100, quant=75)
    assert m["expected_hits"] == pytest.approx(7.5, abs=0.01)
    assert m["observed_hits"] == 8


def test_gap_zscore_positive_when_overdue() -> None:
    """draws_since > expected_gap → zscore > 0."""
    m = compute_deviation_metrics(draws_since=50, times_drawn=0, draws_processed=200, quant=75)
    assert m["gap_zscore"] > 0


def test_gap_zscore_negative_when_recent() -> None:
    """draws_since < expected_gap → zscore < 0."""
    m = compute_deviation_metrics(draws_since=5, times_drawn=1, draws_processed=200, quant=75)
    assert m["gap_zscore"] < 0


def test_gap_zscore_zero_when_exactly_at_expectation() -> None:
    m = compute_deviation_metrics(draws_since=100, times_drawn=1, draws_processed=200, quant=10)
    # expected_gap = 1000/10 = 100; draws_since = 100 → zscore ≈ 0
    assert m["gap_zscore"] == pytest.approx(0.0, abs=0.001)


def test_multi_window_agreement_all_cold() -> None:
    """Absent for 200 draws → cold_30, cold_90, cold_180 all True → agreement=3."""
    m = compute_deviation_metrics(draws_since=200, times_drawn=0, draws_processed=200, quant=10)
    assert m["short_term_cold"]  is True
    assert m["medium_term_cold"] is True
    assert m["long_term_cold"]   is True
    assert m["multi_window_agreement"] == 3


def test_multi_window_agreement_only_short_cold() -> None:
    """Absent for 50 draws → only short_term_cold=True."""
    m = compute_deviation_metrics(draws_since=50, times_drawn=1, draws_processed=200, quant=10)
    assert m["short_term_cold"]  is True
    assert m["medium_term_cold"] is False
    assert m["long_term_cold"]   is False
    assert m["multi_window_agreement"] == 1


def test_multi_window_agreement_none_cold() -> None:
    m = compute_deviation_metrics(draws_since=20, times_drawn=3, draws_processed=200, quant=10)
    assert m["multi_window_agreement"] == 0


def test_draws_since_bounded_by_draws_processed_no_leakage() -> None:
    """Verify callers cannot accidentally leak: draws_since ≤ draws_processed is
    the only valid state.  If draws_since == draws_processed the value has never
    appeared — gap_ratio = draws_processed / expected_gap, not infinity."""
    m = compute_deviation_metrics(
        draws_since=250, times_drawn=0, draws_processed=250, quant=28
    )
    # draws_since == draws_processed → value never appeared in window
    # expected_gap = 1000/28 ≈ 35.7 → gap_ratio ≈ 7.0
    assert m["gap_ratio"] == pytest.approx(250 / (1000 / 28), abs=0.01)
    assert m["observed_hits"] == 0
    assert m["expected_hits"] == pytest.approx(250 * 28 / 1000, abs=0.01)


def test_degenerate_quant_zero_returns_safe_values() -> None:
    m = compute_deviation_metrics(draws_since=10, times_drawn=0, draws_processed=100, quant=0)
    assert m["gap_ratio"] == 0.0
    assert m["severity_band"] == "unknown"


# ---------------------------------------------------------------------------
# composite_score — ordering correctness
# ---------------------------------------------------------------------------

def test_composite_score_common_overdue_beats_rare_absent() -> None:
    """The fix: sum 13 (quant=75) absent 3x expected outranks sum 0 (quant=1) barely past 10%."""
    # Sum 13: expected_gap=13.3, draws_since=50 → gap_ratio=3.75
    s13 = composite_score(draws_since=50, quant=75, max_quant_in_family=75, draws_processed=200)
    # Sum 0: expected_gap=1000, draws_since=100 → gap_ratio=0.1
    s0  = composite_score(draws_since=100, quant=1, max_quant_in_family=75, draws_processed=200)
    assert s13 > s0, (
        f"Common overdue (sum 13, score={s13:.4f}) should outscore "
        f"rare absent (sum 0, score={s0:.4f})"
    )


def test_composite_score_zero_when_cold_start() -> None:
    s = composite_score(draws_since=0, quant=75, max_quant_in_family=75, draws_processed=0)
    assert s == 0.0


def test_composite_score_increases_with_draws_since() -> None:
    s10 = composite_score(50,  quant=28, max_quant_in_family=75, draws_processed=200)
    s20 = composite_score(100, quant=28, max_quant_in_family=75, draws_processed=200)
    assert s20 > s10


def test_composite_score_same_gap_ratio_prefers_common() -> None:
    """Same gap_ratio → higher quant → higher score (mild structural weight)."""
    # Both at 2x expected gap
    s_common = composite_score(draws_since=26,   quant=75, max_quant_in_family=75, draws_processed=200)
    s_rare   = composite_score(draws_since=2000, quant=1,  max_quant_in_family=75, draws_processed=200)
    assert s_common > s_rare, "Higher probability value should score higher at same gap_ratio"


# ---------------------------------------------------------------------------
# describe_deviation — content check
# ---------------------------------------------------------------------------

def test_describe_deviation_contains_key_fields() -> None:
    text = describe_deviation(
        value="13", family="sum",
        draws_since=50, quant=75,
        severity="elevated", gap_ratio=3.75,
        multi_window_agreement=2,
    )
    assert "13" in text
    assert "50" in text
    assert "elevated" in text
    assert "3.8" in text or "3.7" in text or "×" in text
