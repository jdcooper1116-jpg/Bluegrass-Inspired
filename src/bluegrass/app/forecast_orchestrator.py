"""Forecast snapshot and scoring orchestrator.

Coordinates between the Play Builder (app layer) and the on-disk forecast
ledger (research layer) so that:

  1. A pre-draw snapshot is captured for each session before results arrive.
  2. Each successfully applied draw result is immediately scored against
     the matching snapshot.

Public API
----------
ensure_todays_snapshots()     — write today's Play Builder state to the ledger
                                 for each session; idempotent (write-once).
run_catchup_with_ledger()     — ensure snapshots, then apply new draws and score
                                 each one.  Drop-in replacement for run_catchup()
                                 at the call sites in frontend.py and scheduler.py.
"""

from __future__ import annotations

import logging
from datetime import date as _date_type
from typing import Any

from bluegrass.app.play_builder import build_play_builder_session
from bluegrass.engine.client import EngineClientError, fetch_all_draws
from bluegrass.engine.intake import normalize_result
from bluegrass.research.config import SYNC_WINDOW_DAYS
from bluegrass.research.ledger import score_forecast, take_snapshot
from bluegrass.research.refresh import refresh_from_result

_log = logging.getLogger(__name__)

_SESSIONS = ("Midday", "Evening", "Night")


def ensure_todays_snapshots(
    *,
    sessions: tuple[str, ...] = _SESSIONS,
    draw_date: str | None = None,
) -> dict[str, Any]:
    """Write a pre-draw forecast snapshot for each session (idempotent).

    Calls build_play_builder_session to capture the current analysis state
    and passes it to ledger.take_snapshot, which is write-once per
    (date, session) pair.

    Per-session errors are caught and logged — a failure on one session
    never aborts the others.

    Returns:
        {
            "created": ["Midday"],          # sessions where a new file was written
            "skipped": ["Evening", "Night"],# sessions already snapshotted today
            "errors":  [],                  # sessions where build/write failed
        }
    """
    today = draw_date or _date_type.today().isoformat()
    created: list[str] = []
    skipped: list[str] = []
    errors:  list[str] = []

    for session in sessions:
        try:
            vm = build_play_builder_session(session)
            written = take_snapshot(session, vm, draw_date=today)
            if written:
                created.append(session)
                _log.debug("snapshot created: %s %s", today, session)
            else:
                skipped.append(session)
                _log.debug("snapshot already exists: %s %s", today, session)
        except Exception:
            _log.exception("ensure_todays_snapshots failed for %s %s", today, session)
            errors.append(session)

    return {"created": created, "skipped": skipped, "errors": errors}


def run_catchup_with_ledger(days: int = SYNC_WINDOW_DAYS) -> dict[str, Any]:
    """Apply new draws and maintain the forecast ledger.

    Sequence:
        1. ensure_todays_snapshots() — write today's snapshots before ingesting
           new results so the snapshot reflects pre-draw analysis state.
        2. Fetch `days` of draws from the engine.
        3. For each draw: apply via refresh_from_result; if applied (not skipped),
           score the matching forecast snapshot.

    Scoring is a silent no-op when no snapshot exists for a (date, session)
    pair — it never raises and never breaks the refresh cycle.

    Returns a dict compatible with run_catchup() ({applied, skipped, errors})
    plus ledger-specific fields ({snapshots_created, scored}).
    """
    snap_result = ensure_todays_snapshots()
    snapshots_created = len(snap_result["created"])

    try:
        rows = fetch_all_draws(days)
    except EngineClientError as exc:
        return {
            "applied": 0, "skipped": 0, "errors": 1,
            "error_detail": str(exc),
            "snapshots_created": snapshots_created,
            "scored": 0,
        }

    applied = skipped = errors = scored = 0

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
            # Score the forecast for this draw; no-op if snapshot absent
            try:
                hits = score_forecast(summary["date"], summary["session"], summary["result"])
                if hits:
                    scored += 1
            except Exception:
                _log.exception(
                    "score_forecast failed for %s %s %s",
                    summary.get("date"), summary.get("session"), summary.get("result"),
                )

    return {
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
        "snapshots_created": snapshots_created,
        "scored": scored,
    }
