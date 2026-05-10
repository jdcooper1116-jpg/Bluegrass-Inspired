"""Audit builders comparing Bluegrass processed state against engine freshness.

build_session_audit and build_audit_overview call fetch_latest_results()
to get the latest engine draw per session, then compare against what
Bluegrass has processed via stats_store.

Both sides use full draw IDs ("date:session:result") for symmetry.
Dates are derived from those IDs for draws_behind calculation.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any

from bluegrass.app.playlist import _VALID_SESSIONS, _last_processed_draw
from bluegrass.engine.client import EngineClientError, fetch_latest_results
from bluegrass.research.stats_store import load_stats_state

_SESSIONS = ("Midday", "Evening", "Night")


def _parse_draw_date(draw_id: str | None) -> str | None:
    """Extract date string from a full draw ID like '2026-05-10:Night:347'."""
    if not draw_id:
        return None
    try:
        return draw_id.split(":")[0]
    except (IndexError, AttributeError):
        return None


def _to_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


def _processed_draw_count(session: str) -> int:
    state = load_stats_state()
    ids = state.get("by_session", {}).get(session, {}).get("processed_draw_ids", [])
    return len(ids)


def _engine_latest_by_session() -> tuple[dict[str, str], str | None]:
    """Return ({session: full_draw_id}, error_reason | None).

    full_draw_id = "date:session:result", matching Bluegrass draw ID format.
    Returns ({}, error_reason) on any failure without raising.
    """
    try:
        raw_rows = fetch_latest_results()
    except EngineClientError:
        return {}, "engine_unavailable"
    if not raw_rows:
        if not os.environ.get("LOTTERY_ENGINE_BASE_URL", "").strip():
            return {}, "no_engine_url"
        return {}, "no_draws_in_window"
    result: dict[str, str] = {}
    for row in raw_rows:
        session = row.get("session", "")
        d = row.get("date", "")
        r = row.get("result", "")
        if session and d and r:
            result[session] = f"{d}:{session}:{r}"
    return result, None


def _build_one(
    session: str,
    engine_map: dict[str, str],
    engine_error: str | None,
) -> dict[str, Any]:
    bluegrass_draw_id = _last_processed_draw(session) or None
    engine_draw_id = engine_map.get(session)

    bluegrass_date_str = _parse_draw_date(bluegrass_draw_id)
    engine_date_str = _parse_draw_date(engine_draw_id)

    processed_count = _processed_draw_count(session)
    coverage = "runtime-updated" if processed_count > 0 else "baseline-only"

    # Compute draws_behind when both dates are known
    draws_behind: int | None = None
    if engine_date_str and bluegrass_date_str:
        ed = _to_date(engine_date_str)
        bd = _to_date(bluegrass_date_str)
        if ed is not None and bd is not None:
            draws_behind = max(0, (ed - bd).days)

    # Determine comparison_status, gap_detected, gap_reason
    if coverage == "baseline-only" and engine_draw_id is not None:
        # Engine has data but Bluegrass has never processed this session
        comparison_status = "gap"
        gap_detected: bool | None = True
        gap_reason = "no_bluegrass_coverage"
    elif coverage == "baseline-only" and (engine_error or engine_draw_id is None):
        # No Bluegrass data and engine is unknown — can't determine gap magnitude,
        # but absence of coverage is itself a known gap
        comparison_status = "gap"
        gap_detected = True
        gap_reason = "no_bluegrass_coverage"
    elif engine_error or engine_draw_id is None:
        # Engine unknown but Bluegrass has data — inconclusive
        comparison_status = "inconclusive"
        gap_detected = None
        gap_reason = engine_error or "no_engine_data_for_session"
    elif draws_behind == 0:
        comparison_status = "matched"
        gap_detected = False
        gap_reason = "up_to_date"
    elif draws_behind is not None and draws_behind > 0:
        comparison_status = "gap"
        gap_detected = True
        gap_reason = f"{draws_behind}_draws_behind"
    else:
        comparison_status = "inconclusive"
        gap_detected = None
        gap_reason = "date_parse_error"

    if coverage == "baseline-only":
        freshness_status = "baseline-only"
    elif comparison_status == "inconclusive":
        freshness_status = "engine-unknown"
    elif comparison_status == "matched":
        freshness_status = "fresh"
    else:
        freshness_status = "stale"

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "session": session,
        "engine_latest_draw": engine_draw_id,
        "engine_latest_date": engine_date_str,
        "bluegrass_last_processed_draw": bluegrass_draw_id,
        "bluegrass_last_processed_date": bluegrass_date_str,
        "draws_behind": draws_behind,
        "freshness_status": freshness_status,
        "coverage": coverage,
        "processed_draw_count": processed_count,
        "comparison_status": comparison_status,
        "gap_detected": gap_detected,
        "gap_reason": gap_reason,
        "generated_at": generated_at,
    }


def build_session_audit(session: str) -> dict[str, Any]:
    """Audit a single session against engine freshness."""
    if session not in _VALID_SESSIONS:
        raise ValueError(f"unrecognized session: {session!r}")
    engine_map, engine_error = _engine_latest_by_session()
    return _build_one(session, engine_map, engine_error)


def build_audit_overview() -> dict[str, Any]:
    """Audit all three sessions with a single engine call."""
    engine_map, engine_error = _engine_latest_by_session()

    sessions: dict[str, Any] = {
        s: _build_one(s, engine_map, engine_error) for s in _SESSIONS
    }

    statuses = [a["comparison_status"] for a in sessions.values()]
    if all(s == "matched" for s in statuses):
        overall_status = "fresh"
    elif all(s == "inconclusive" for s in statuses):
        overall_status = "engine-unknown"
    elif any(s == "gap" for s in statuses):
        overall_status = "degraded"
    else:
        overall_status = "inconclusive"

    gap_sessions = [s for s, a in sessions.items() if a["comparison_status"] == "gap"]
    inconclusive_sessions = [s for s, a in sessions.items() if a["comparison_status"] == "inconclusive"]

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "sessions": sessions,
        "overall_status": overall_status,
        "gap_sessions": gap_sessions,
        "inconclusive_sessions": inconclusive_sessions,
        "engine_error": engine_error,
        "generated_at": generated_at,
    }
