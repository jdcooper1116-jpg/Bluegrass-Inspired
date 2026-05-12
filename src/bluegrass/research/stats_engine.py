"""Pick 3 statistical deviation engine — pure functions, no I/O.

All functions here take only numeric arguments and return plain dicts or
scalars.  They never read from disk, never call the engine, and never look
at stats_state.  This makes them trivially testable and safely callable
from any context.

Key design decisions
--------------------
* All metrics are derived from draws already processed (via stats_state),
  so there is no look-ahead leakage.  The caller is responsible for
  passing values that respect the processing cutoff.

* Multi-window flags are implicit: ``short_term_cold = draws_since >= 30``
  means "this value has not appeared in at least the last 30 draws."  It
  does NOT imply that per-window statistics were computed from separate
  data — only a single aggregate window is stored in runtime state.  These
  flags are labeled clearly in the returned dict to avoid false precision.

* gap_zscore uses a geometric-distribution approximation.  Under the
  geometric, mean = expected_gap and std ≈ expected_gap (CV ≈ 1).  So
  z = (draws_since - expected_gap) / expected_gap.  This is approximate;
  the field name includes "_approx" in the docstring and the severity_band
  label is preferred for human-facing display.

Pair quant constants
--------------------
Front, back, and split pairs each have 100 possible values (00–99).
Each specific pair value is produced by exactly 10 out of 1000 straight
combos (fix 2 digits, 10 choices for the third).  Expected gap = 100 draws.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Canonical quant constants for families without external tables
# ---------------------------------------------------------------------------

PAIR_QUANT: int  = 10    # combos-per-1000 for any specific pair value
PAIR_EXPECTED_GAP: float = 100.0   # 1000 / PAIR_QUANT

# Maximum quant values for structural weighting (from sums.py tables)
SUM_MAX_QUANT: int  = 75    # max(SUM_STRAIGHT_QUANT.values())
ROOT_MAX_QUANT: int = 111   # max(ROOT_STRAIGHT_QUANT.values())

# ---------------------------------------------------------------------------
# Severity band thresholds (gap_ratio)
# ---------------------------------------------------------------------------

_BANDS: tuple[tuple[float, str], ...] = (
    (0.0,  "recent"),    # gap_ratio < 0.5  — seen recently
    (0.5,  "normal"),    # 0.5 ≤ ratio < 1.5 — within expectation
    (1.5,  "mild"),      # 1.5 ≤ ratio < 2.5 — mildly elevated
    (2.5,  "elevated"),  # 2.5 ≤ ratio < 4.0 — clearly elevated
    (4.0,  "strong"),    # 4.0 ≤ ratio < 7.0 — strongly elevated
    (7.0,  "extreme"),   # ratio ≥ 7.0        — grossly abnormal
)


def severity_band(gap_ratio: float) -> str:
    """Return a human-readable severity label for a given gap_ratio.

    gap_ratio = draws_since / expected_gap_draws
    """
    label = "recent"
    for threshold, band in _BANDS:
        if gap_ratio >= threshold:
            label = band
    return label


# ---------------------------------------------------------------------------
# Core deviation metric computation
# ---------------------------------------------------------------------------

def compute_deviation_metrics(
    draws_since: int,
    times_drawn: int,
    draws_processed: int,
    quant: int,
) -> dict[str, Any]:
    """Compute statistical deviation metrics for one family value.

    Parameters
    ----------
    draws_since:
        Draws elapsed since this value last appeared.  Equal to
        draws_processed if the value has never appeared.
    times_drawn:
        Times this value appeared in the processed window (times_seen_runtime).
    draws_processed:
        Total draws processed for this session in the analysis window.
    quant:
        Number of straight combos out of 1000 that produce this value.
        E.g. sum 14 → 75, any specific pair → 10, any straight → 1.

    Returns
    -------
    dict with keys:
        expected_hits        — float: draws_processed * quant / 1000
        observed_hits        — int: same as times_drawn input
        expected_gap_draws   — float: 1000 / quant (theoretical)
        gap_ratio            — float: draws_since / expected_gap (primary)
        gap_zscore           — float: (draws_since - expected_gap) / expected_gap
                               (geometric approximation; prefer severity_band for display)
        severity_band        — str: "recent" | "normal" | "mild" | "elevated" | "strong" | "extreme"
        short_term_cold      — bool: draws_since >= 30 (implicit 30-draw window flag)
        medium_term_cold     — bool: draws_since >= 90
        long_term_cold       — bool: draws_since >= 180
        multi_window_agreement — int: count of cold window flags (0–3)
    """
    if quant <= 0:
        # Degenerate case: undefined probability.  Return safe zeros.
        return {
            "expected_hits":          0.0,
            "observed_hits":          times_drawn,
            "expected_gap_draws":     float("inf"),
            "gap_ratio":              0.0,
            "gap_zscore":             0.0,
            "severity_band":          "unknown",
            "short_term_cold":        False,
            "medium_term_cold":       False,
            "long_term_cold":         False,
            "multi_window_agreement": 0,
        }

    expected_gap = 1000.0 / quant
    gap_ratio = draws_since / expected_gap if expected_gap > 0 else 0.0
    # Geometric approximation: CV ≈ 1, so std ≈ mean
    gap_zscore = (draws_since - expected_gap) / expected_gap if expected_gap > 0 else 0.0

    expected_hits = round(draws_processed * quant / 1000.0, 2) if draws_processed > 0 else 0.0

    stc = draws_since >= 30
    mtc = draws_since >= 90
    ltc = draws_since >= 180
    agreement = sum([stc, mtc, ltc])

    return {
        "expected_hits":          expected_hits,
        "observed_hits":          times_drawn,
        "expected_gap_draws":     round(expected_gap, 1),
        "gap_ratio":              round(gap_ratio, 4),
        "gap_zscore":             round(gap_zscore, 4),
        "severity_band":          severity_band(gap_ratio),
        "short_term_cold":        stc,
        "medium_term_cold":       mtc,
        "long_term_cold":         ltc,
        "multi_window_agreement": agreement,
    }


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

def composite_score(
    draws_since: int,
    quant: int,
    max_quant_in_family: int,
    draws_processed: int,
) -> float:
    """Return a composite overdue score suitable for board ranking.

    The score blends gap_ratio (how overdue relative to expectation) with a
    mild structural probability weight (how common this value should be).

    This corrects the raw draws_since ranker: a rare value (quant=1,
    expected_gap=1000) that has been absent for 100 draws is NOT overdue
    (gap_ratio=0.1).  A common value (quant=75, expected_gap=13) absent for
    50 draws IS severely overdue (gap_ratio=3.8).  Raw draws_since ranking
    would wrongly elevate the rare value.

    Formula:
        gap_ratio = draws_since / (1000 / quant)
        prob_weight = (quant / max_quant_in_family) ^ 0.25
        score = gap_ratio * prob_weight

    The 0.25 exponent gives mild structural preference without crushing rare
    values entirely.  A value with quant=1 vs max_quant=75 gets prob_weight
    ≈ 0.34, which is a meaningful dampener but not a veto.
    """
    if draws_processed == 0 or quant <= 0 or max_quant_in_family <= 0:
        return 0.0
    expected_gap = 1000.0 / quant
    gr = draws_since / expected_gap
    pw = (quant / max_quant_in_family) ** 0.25
    return round(gr * pw, 6)


# ---------------------------------------------------------------------------
# Human-readable score components for why_flagged
# ---------------------------------------------------------------------------

def describe_deviation(
    value: str,
    family: str,
    draws_since: int,
    quant: int,
    severity: str,
    gap_ratio: float,
    multi_window_agreement: int,
) -> str:
    """Build a concise human-readable explanation of why an item is flagged.

    Returns a plain string suitable for the why_flagged field.
    """
    expected_gap = round(1000.0 / quant, 1) if quant > 0 else float("inf")

    window_words = ["30d", "90d", "180d"]
    cold_count = multi_window_agreement
    if cold_count == 0:
        window_ctx = ""
    elif cold_count == 3:
        window_ctx = " · cold across all windows"
    else:
        window_ctx = f" · cold {cold_count}/3 windows"

    ratio_str = f"{gap_ratio:.1f}×" if gap_ratio > 0 else ""

    return (
        f"{family} {value} — {draws_since} draws absent"
        f" (expected every {expected_gap:.0f};"
        f" {ratio_str} expected gap; {severity})"
        f"{window_ctx}"
    )
