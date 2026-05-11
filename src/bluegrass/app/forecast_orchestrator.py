"""Forecast snapshot and scoring orchestrator.

Coordinates between the Play Builder (app layer) and the on-disk forecast
ledger (research layer) so that:

  1. A pre-draw snapshot is captured for each session before results arrive,
     with freshness enforcement — stale state triggers an auto-catchup so
     snapshots are always built from the most current data available.
  2. Each successfully applied draw result is immediately scored against
     the matching snapshot.

Public API
----------
ensure_todays_snapshots()     — write today's Play Builder state to the ledger
                                 for each session; idempotent (write-once).
                                 Includes freshness gate: attempts catch-up
                                 before snapshotting if state is stale.
run_catchup_with_ledger()     — ensure snapshots, then apply new draws and score
                                 each one.  Drop-in replacement for run_catchup()
                                 at the call sites in frontend.py and scheduler.py.
"""

from __future__ import annotations

import logging
from datetime import date as _date_type
from typing import Any

from bluegrass.app.audit import build_audit_overview
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

    Freshness gate
    --------------
    Before snapshotting, checks session freshness via build_audit_overview().
    If any session is stale and the engine is reachable, triggers run_catchup()
    to update state, then re-checks freshness.  The resulting freshness status
    is stored in every snapshot's metadata so the ledger records whether
    predictions were built from fresh or stale data.

    Idempotency
    -----------
    take_snapshot is write-once per (date, session) pair.  Safe to call
    many times per day — only the first call per session writes a file.

    Per-session errors are caught and logged — a failure on one session
    never aborts the others.

    Returns
    -------
    {
        "created": ["Midday"],           # sessions where a new file was written
        "skipped": ["Evening", "Night"], # sessions already snapshotted today
        "errors":  [],                   # sessions where build/write failed
    }
    """
    today = draw_date or _date_type.today().isoformat()

    # ── Step 1: fetch all session freshness in a single engine call ───────
    try:
        audit_ov = build_audit_overview()
        session_audits: dict[str, Any] = audit_ov.get("sessions", {})
    except Exception:
        _log.warning("ensure_todays_snapshots: build_audit_overview failed; "
                     "proceeding with engine-unknown freshness")
        session_audits = {}

    # ── Step 2: if any session is stale, attempt one catch-up run ────────
    any_stale = any(
        session_audits.get(s, {}).get("freshness_status") == "stale"
        for s in sessions
    )
    if any_stale:
        _log.info("ensure_todays_snapshots: stale sessions detected — running catch-up")
        try:
            from bluegrass.research.catchup import run_catchup
            run_catchup()
            # Re-fetch freshness with updated state
            audit_ov = build_audit_overview()
            session_audits = audit_ov.get("sessions", {})
        except Exception:
            _log.warning("ensure_todays_snapshots: catch-up before snapshot failed; "
                         "proceeding with current state")

    # ── Step 3: snapshot each session with freshness metadata ─────────────
    created: list[str] = []
    skipped: list[str] = []
    errors:  list[str] = []

    for session in sessions:
        sess_audit = session_audits.get(session, {})
        freshness_meta = {
            "snapshot_freshness_status":   sess_audit.get("freshness_status", "engine-unknown"),
            "snapshot_source_state_date":  sess_audit.get("bluegrass_last_processed_date"),
            "snapshot_draws_behind":       sess_audit.get("draws_behind"),
        }
        try:
            vm = build_play_builder_session(session)
            written = take_snapshot(session, vm, draw_date=today, freshness_meta=freshness_meta)
            if written:
                created.append(session)
                _log.debug(
                    "snapshot created: %s %s (freshness=%s, draws_behind=%s)",
                    today, session,
                    freshness_meta["snapshot_freshness_status"],
                    freshness_meta["snapshot_draws_behind"],
                )
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
        1. ensure_todays_snapshots() — write today's snapshots (with freshness
           gate) before ingesting new results, so snapshots reflect pre-draw
           analysis state.
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
