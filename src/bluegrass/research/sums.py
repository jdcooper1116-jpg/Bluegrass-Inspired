"""Pick 3 digit-sum utilities, canonical expectation tables, and overdue boards.

Architecture
------------
draws_since is built exclusively from engine-verified draw history stored in
stats_state.json. The baseline workbook (v47.xlsx) contains pre-aggregated
snapshots from lotterypost.com — not individual draw records — so it is not
a reliable source for draws_since and is never consulted here.

For any sum / root-sum value not yet observed in the runtime window:
    draws_since = session_state["draws_processed"]
    ("N engine draws have been processed; this value never appeared.")

SUM_STRAIGHT_QUANT   — number of straight combos producing each digit sum (0–27)
ROOT_STRAIGHT_QUANT  — number of straight combos producing each digital root (0–9)
expected_gap(quant)  — expected draws between appearances for a given combo count
"""

from __future__ import annotations

from typing import Any

from bluegrass.research.config import ANALYSIS_WINDOW_DAYS
from bluegrass.research.stats_engine import (
    SUM_MAX_QUANT,
    ROOT_MAX_QUANT,
    compute_deviation_metrics,
    describe_deviation,
)
from bluegrass.research.stats_store import load_stats_state


# ---------------------------------------------------------------------------
# Canonical quantification tables (pure combinatorics, no external data)
# ---------------------------------------------------------------------------

SUM_STRAIGHT_QUANT: dict[int, int] = {
    0: 1,   1: 3,   2: 6,   3: 10,  4: 15,  5: 21,  6: 28,  7: 36,
    8: 45,  9: 55,  10: 63, 11: 69, 12: 73, 13: 75, 14: 75, 15: 73,
    16: 69, 17: 63, 18: 55, 19: 45, 20: 36, 21: 28, 22: 21, 23: 15,
    24: 10, 25: 6,  26: 3,  27: 1,
}

ROOT_STRAIGHT_QUANT: dict[int, int] = {
    0: 1,
    1: 111, 2: 111, 3: 111, 4: 111, 5: 111,
    6: 111, 7: 111, 8: 111, 9: 111,
}


def expected_gap(quant: int) -> float:
    """Expected draws between appearances for a value with *quant* straight combos."""
    return round(1000 / quant, 2) if quant > 0 else float("inf")


# ---------------------------------------------------------------------------
# Pure math helpers (no I/O)
# ---------------------------------------------------------------------------

def digit_sum(value: str) -> int:
    """Sum of the three digits of a Pick 3 result string, e.g. '123' → 6."""
    return sum(int(d) for d in value)


def root_sum(value: str) -> int:
    """Digital root of a Pick 3 result (iterative digit sum to single digit).

    '000' is the only value that returns 0.
    All multiples of 9 except 0 return 9.
    """
    s = digit_sum(value)
    while s >= 10:
        s = sum(int(d) for d in str(s))
    return s


# ---------------------------------------------------------------------------
# Board builder (shared logic)
# ---------------------------------------------------------------------------

def _build_board(
    state_key: str,
    display_family: str,
    quant_table: dict[int, int],
    session: str,
    analysis_window_days: int,
    max_quant_in_family: int,
) -> list[dict[str, Any]]:
    """Build an overdue board from engine-runtime state only.

    state_key            — key used to look up the family dict in stats_state
    display_family       — family label written into every returned row
    quant_table          — canonical combo-count-per-1000 for each value
    max_quant_in_family  — maximum quant in this family (for composite scoring)

    Deviation metrics are computed from (draws_since, times_drawn,
    draws_processed, quant) and merged into each row so that callers can
    use gap_ratio and severity_band directly for scoring and display.

    All values are engine-verified.  No baseline CSVs are read here.
    """
    state = load_stats_state()
    session_state = state.get("by_session", {}).get(session, {})
    runtime_family: dict[str, Any] = session_state.get(state_key, {})
    draws_processed: int = session_state.get("draws_processed", 0)

    rows: list[dict[str, Any]] = []
    for value, quant in quant_table.items():
        key_str = str(value)
        entry = runtime_family.get(key_str)
        if entry is not None:
            draws_since = entry.get("draws_since", draws_processed)
            last_seen   = entry.get("last_seen", "")
            times_drawn = entry.get("times_seen_runtime", 0)
        else:
            draws_since = draws_processed
            last_seen   = ""
            times_drawn = 0

        dev = compute_deviation_metrics(draws_since, times_drawn, draws_processed, quant)
        why = describe_deviation(
            str(value), display_family, draws_since, quant,
            dev["severity_band"], dev["gap_ratio"], dev["multi_window_agreement"],
        )

        rows.append({
            # Core identity
            "family":              display_family,
            "value":               key_str,
            "session":             session,
            # Overdue tracking (engine-verified)
            "draws_since":         draws_since,
            "last_seen":           last_seen,
            "times_drawn":         times_drawn,
            "draws_processed":     draws_processed,
            # Combinatoric
            "combo_count":         quant,
            "expected_gap_draws":  dev["expected_gap_draws"],
            # Deviation metrics
            "expected_hits":       dev["expected_hits"],
            "observed_hits":       dev["observed_hits"],
            "gap_ratio":           dev["gap_ratio"],
            "gap_zscore":          dev["gap_zscore"],
            "severity_band":       dev["severity_band"],
            # Multi-window flags
            "short_term_cold":     dev["short_term_cold"],
            "medium_term_cold":    dev["medium_term_cold"],
            "long_term_cold":      dev["long_term_cold"],
            "multi_window_agreement": dev["multi_window_agreement"],
            # Metadata
            "analysis_window_days": analysis_window_days,
            "why_flagged":         why,
        })

    rows.sort(key=lambda r: r["draws_since"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Public board builders
# ---------------------------------------------------------------------------

def build_sums_board(
    session: str,
    *,
    limit: int | None = None,
    analysis_window_days: int = ANALYSIS_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """All digit-sum groups for a session, sorted most-overdue first.

    Each row includes gap_ratio, severity_band, multi_window_agreement and
    other deviation metrics so callers can use them directly for scoring and
    display without recomputing from raw values.

    draws_since is engine-runtime only. Values never seen in runtime show
    draws_since == session draws_processed (honest lower bound).
    """
    rows = _build_board(
        "sums", "sum", SUM_STRAIGHT_QUANT, session, analysis_window_days,
        max_quant_in_family=SUM_MAX_QUANT,
    )
    return rows[:limit] if limit is not None else rows


def build_root_sums_board(
    session: str,
    *,
    limit: int | None = None,
    analysis_window_days: int = ANALYSIS_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """All root-sum groups for a session, sorted most-overdue first.

    Includes deviation metrics. draws_since is engine-runtime only.
    """
    rows = _build_board(
        "root_sums", "root_sum", ROOT_STRAIGHT_QUANT, session, analysis_window_days,
        max_quant_in_family=ROOT_MAX_QUANT,
    )
    return rows[:limit] if limit is not None else rows
