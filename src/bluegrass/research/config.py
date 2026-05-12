"""Bluegrass window constants — single source of truth.

Two windows serve different purposes and must never be conflated:

SYNC_WINDOW_DAYS
    Operational catch-up / scheduler horizon. Keeps the runtime stats
    state current without fetching large history on every tick.

ANALYSIS_WINDOW_DAYS
    Rolling window for overdue analysis boards (sums, root sums, pairs,
    box pressure). 250 days gives enough verified draw history for
    statistically meaningful gap and overdue calculations.

    The baseline workbook (v47.xlsx) contains pre-aggregated snapshots
    from lotterypost.com, not individual draw records, so it cannot serve
    as a reliable floor for draws_since. All overdue figures are built
    exclusively from engine-verified draws stored in stats_state.json.
"""

from __future__ import annotations

SYNC_WINDOW_DAYS: int = 30
ANALYSIS_WINDOW_DAYS: int = 540
