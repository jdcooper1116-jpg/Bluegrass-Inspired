"""Catch-up sync — apply all unprocessed draws from the engine in chronological order.

Two operations with distinct purposes:

run_catchup(days=SYNC_WINDOW_DAYS)
    Operational sync. Keeps runtime stats current without fetching large
    history on every scheduler tick. Default: 30 days.

run_analysis_bootstrap(days=ANALYSIS_WINDOW_DAYS)
    Deep bootstrap for the statistical analysis window. Fetches a wider
    rolling window so overdue boards have enough verified draw history for
    meaningful gap calculations. Default: 250 days.
    Run once at startup; the scheduler loop uses run_catchup() thereafter.

Both are idempotent: already-processed draw IDs are skipped by the
refresh_from_result dedup guard, so they are safe to call repeatedly.
"""

from __future__ import annotations

from typing import Any

from bluegrass.engine.client import EngineClientError, fetch_all_draws
from bluegrass.engine.intake import normalize_result
from bluegrass.research.config import ANALYSIS_WINDOW_DAYS, SYNC_WINDOW_DAYS


def run_catchup(days: int = SYNC_WINDOW_DAYS) -> dict[str, Any]:
    """Operational sync — fetch up to `days` of draw history and apply unprocessed draws.

    Default window: SYNC_WINDOW_DAYS (30). Used by the scheduler and
    /refresh/sync-latest. Returns {applied, skipped, errors} counts.
    """
    # Import here to avoid circular import at module level
    from bluegrass.research.refresh import refresh_from_result

    try:
        rows = fetch_all_draws(days)
    except EngineClientError as exc:
        return {"applied": 0, "skipped": 0, "errors": 1, "error_detail": str(exc)}

    applied = skipped = errors = 0
    for raw in rows:
        try:
            result = normalize_result(raw)
        except ValueError:
            errors += 1
            continue
        summary = refresh_from_result(result)
        if summary.get("skipped"):
            skipped += 1
        else:
            applied += 1

    return {"applied": applied, "skipped": skipped, "errors": errors}


def run_analysis_bootstrap(days: int = ANALYSIS_WINDOW_DAYS) -> dict[str, Any]:
    """Deep bootstrap for the statistical analysis window.

    Default window: ANALYSIS_WINDOW_DAYS (250). Fetches a wider rolling
    window than the operational sync so that overdue boards (sums, root
    sums, pairs, box pressure) have enough verified draw history for
    meaningful draws_since values.

    Idempotent — already-processed draw IDs are skipped, so this is safe
    to call at every startup. The scheduler's 30-day sync loop runs after
    this without conflict.
    """
    return run_catchup(days=days)
