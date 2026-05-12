"""Runtime state rebuild — deterministic recovery from stale or inconsistent state.

When to use
-----------
``rebuild_runtime_state()`` is the recovery path for these conditions:

* Integrity shows stale but Sync Latest reports only skipped draws
  (draws_behind > SYNC_WINDOW_DAYS — the sync window is too small to reach the gap)
* stats_state.json is suspected of out-of-order entries or corruption
* After a fresh deploy that wiped the runtime filesystem

What it does
------------
1. Deletes stats_state.json  (clears all derived runtime state)
2. Fetches up to `days` of draws from the engine in chronological order
3. Replays every draw through refresh_from_result

What it preserves
-----------------
* Baseline seed CSVs (data/baseline/seeds/)
* Forecast ledger files  (data/runtime/forecasts/)

After a successful rebuild, Sync Latest should report all draws applied
(not skipped), and Integrity should show all sessions as fresh.
"""

from __future__ import annotations

import logging
from typing import Any

from bluegrass.engine.client import EngineClientError, fetch_all_draws
from bluegrass.engine.intake import normalize_result
from bluegrass.research.config import ANALYSIS_WINDOW_DAYS
from bluegrass.research.stats_store import reset_stats_state

_log = logging.getLogger(__name__)


def rebuild_runtime_state(days: int = ANALYSIS_WINDOW_DAYS) -> dict[str, Any]:
    """Clear derived runtime state and replay draw history from scratch.

    Parameters
    ----------
    days:
        How many days of draw history to fetch from the engine.
        Default: ANALYSIS_WINDOW_DAYS (250).  Use a larger value if the
        system has been offline for more than 250 days.

    Returns
    -------
    {
        "cleared": True,
        "days": int,
        "applied": int,
        "skipped": int,      # should be 0 after a clean rebuild
        "errors": int,
        "error_detail": str | None,
    }

    If ``skipped > 0`` after a rebuild, something re-processed draws before
    this function completed (e.g., a concurrent scheduler tick).  The state
    is still valid — duplicate draw IDs are idempotently ignored.
    """
    # Import here to avoid circular import (research → research is fine,
    # but this function is called from app layer so the import is safe either way)
    from bluegrass.research.refresh import refresh_from_result

    _log.warning(
        "rebuild_runtime_state: clearing stats_state.json and replaying %d days", days
    )

    # Step 1: clear all derived runtime state
    reset_stats_state()

    # Step 2: fetch draw history
    try:
        rows = fetch_all_draws(days)
    except EngineClientError as exc:
        _log.error("rebuild_runtime_state: engine fetch failed: %s", exc)
        return {
            "cleared": True,
            "days": days,
            "applied": 0,
            "skipped": 0,
            "errors": 1,
            "error_detail": str(exc),
        }

    if not rows:
        _log.warning("rebuild_runtime_state: engine returned 0 draws for %d days", days)
        return {
            "cleared": True,
            "days": days,
            "applied": 0,
            "skipped": 0,
            "errors": 0,
            "error_detail": "engine returned no draws (no engine URL or empty window)",
        }

    # Step 3: replay in strict chronological order
    # fetch_all_draws already sorts by (date, session_order)
    applied = skipped = errors = 0
    for raw in rows:
        try:
            result = normalize_result(raw)
        except ValueError as exc:
            _log.debug("rebuild: normalize_result failed: %s", exc)
            errors += 1
            continue

        summary = refresh_from_result(result)
        if summary.get("skipped"):
            skipped += 1
        else:
            applied += 1

    _log.info(
        "rebuild_runtime_state complete: applied=%d skipped=%d errors=%d",
        applied, skipped, errors,
    )
    return {
        "cleared": True,
        "days": days,
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
        "error_detail": None,
    }
