"""Runtime state rebuild — deterministic recovery from stale or inconsistent state.

When to use
-----------
rebuild_runtime_state() is the recovery path for these conditions:

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

Rebuild exclusivity
-------------------
Only one rebuild may run at a time.  A second concurrent call returns
{"already_running": True, ...} immediately without mutating state.
The API route translates this to an HTTP 409 response.

After a successful rebuild, Sync Latest should report all draws applied
(not skipped), and Integrity should show all sessions as fresh.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from bluegrass.engine.client import EngineClientError, fetch_all_draws
from bluegrass.engine.intake import normalize_result
from bluegrass.research.config import ANALYSIS_WINDOW_DAYS
from bluegrass.research.stats_store import reset_stats_state

_log = logging.getLogger(__name__)

# Non-reentrant lock: only one rebuild may execute at a time within the process.
# Non-blocking acquire returns False if another rebuild is already running.
_REBUILD_LOCK = threading.Lock()


def is_rebuild_in_progress() -> bool:
    """Return True if a rebuild is currently executing in this process.

    Used by the scheduler to skip its catch-up tick while rebuild holds
    the write-and-reset lifecycle.
    """
    return _REBUILD_LOCK.locked()


def rebuild_runtime_state(days: int = ANALYSIS_WINDOW_DAYS) -> dict[str, Any]:
    """Clear derived runtime state and replay draw history from scratch.

    Rebuild exclusivity: if another rebuild is already running, returns
    immediately with {"already_running": True, "cleared": False}.

    Parameters
    ----------
    days:
        How many days of draw history to fetch from the engine.
        Default: ANALYSIS_WINDOW_DAYS.

    Returns
    -------
    {
        "already_running": bool,   # True when a rebuild was already in progress
        "cleared": bool,           # True when state was cleared
        "days": int,
        "applied": int,
        "skipped": int,
        "errors": int,
        "error_detail": str | None,
    }
    """
    if not _REBUILD_LOCK.acquire(blocking=False):
        _log.warning("rebuild_runtime_state: already running — rejecting concurrent request")
        return {
            "already_running": True,
            "cleared":         False,
            "days":            days,
            "applied":         0,
            "skipped":         0,
            "errors":          0,
            "error_detail":    "A rebuild is already in progress; try again after it completes.",
        }

    try:
        return _do_rebuild(days)
    finally:
        _REBUILD_LOCK.release()


def _do_rebuild(days: int) -> dict[str, Any]:
    """Internal rebuild body — called only while _REBUILD_LOCK is held."""
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
            "already_running": False,
            "cleared":         True,
            "days":            days,
            "applied":         0,
            "skipped":         0,
            "errors":          1,
            "error_detail":    str(exc),
        }

    if not rows:
        _log.warning("rebuild_runtime_state: engine returned 0 draws for %d days", days)
        return {
            "already_running": False,
            "cleared":         True,
            "days":            days,
            "applied":         0,
            "skipped":         0,
            "errors":          0,
            "error_detail":    "engine returned no draws (no engine URL or empty window)",
        }

    # Step 3: replay in strict chronological order
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
        "already_running": False,
        "cleared":         True,
        "days":            days,
        "applied":         applied,
        "skipped":         skipped,
        "errors":          errors,
        "error_detail":    None,
    }
