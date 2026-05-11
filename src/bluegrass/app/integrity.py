"""Integrity view-model: per-session comparison of engine state vs Bluegrass applied state.

Shows whether each session is matched, stale, or has gaps, and exposes the
most recent applied stat resets so operators can verify correctness.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bluegrass.app.audit import build_audit_overview
from bluegrass.app.playlist import _VALID_SESSIONS
from bluegrass.research.stats_store import load_stats_state

_SESSIONS = ("Midday", "Evening", "Night")


def _last_applied(session_state: dict[str, Any]) -> str | None:
    ids: list[str] = session_state.get("processed_draw_ids", [])
    if not ids:
        return None
    # id format: "YYYY-MM-DD:Session:result"
    return ids[-1]


def _last_resets(session_state: dict[str, Any]) -> dict[str, Any]:
    """Extract the most recently reset value for each tracked family."""
    def _recent(family: dict[str, Any]) -> dict[str, Any] | None:
        zeros = {v: e for v, e in family.items() if e.get("draws_since", 1) == 0}
        if not zeros:
            return None
        v, e = next(iter(zeros.items()))
        return {"value": v, "last_seen": e.get("last_seen", ""), "times_seen": e.get("times_seen_runtime", 0)}

    sums = session_state.get("sums", {})
    roots = session_state.get("root_sums", {})
    pairs = session_state.get("pairs", {})
    straight = session_state.get("straight_combos", {})
    boxes = session_state.get("box_families", {})
    patterns = session_state.get("patterns", {})

    return {
        "sum":          _recent(sums),
        "root_sum":     _recent(roots),
        "front_pair":   _recent(pairs.get("front", {})),
        "back_pair":    _recent(pairs.get("back", {})),
        "split_pair":   _recent(pairs.get("split", {})),
        "straight":     _recent(straight),
        "box_family":   _recent(boxes),
        "pattern":      {
            pt: e for pt, e in patterns.items() if e.get("draws_since", 1) == 0
        } or None,
    }


def build_integrity_view() -> dict[str, Any]:
    """Build the integrity view-model for all sessions."""
    audit_ov = build_audit_overview()
    stats = load_stats_state()
    by_session = stats.get("by_session", {})

    sessions: dict[str, Any] = {}
    for sess in _SESSIONS:
        sess_state = by_session.get(sess, {})
        audit_sess = audit_ov.get("sessions", {}).get(sess, {})

        last_id = _last_applied(sess_state)
        if last_id:
            parts = last_id.split(":")
            last_date = parts[0]
            last_result = parts[2] if len(parts) >= 3 else "?"
        else:
            last_date = None
            last_result = None

        engine_date = audit_sess.get("engine_latest_date")
        freshness = audit_sess.get("freshness_status", "engine-unknown")

        if freshness == "fresh":
            match_status = "matched"
        elif freshness in ("stale", "baseline-only"):
            match_status = "stale"
        else:
            match_status = "unknown"

        gap = audit_sess.get("draws_behind")

        sessions[sess] = {
            "session": sess,
            "engine_latest_date": engine_date,
            "bluegrass_latest_date": last_date,
            "bluegrass_latest_result": last_result,
            "match_status": match_status,
            "freshness_status": freshness,
            "draws_behind": gap,
            "gap_detected": bool(gap and gap > 1),
            "draws_processed": sess_state.get("draws_processed", 0),
            "last_resets": _last_resets(sess_state),
            "rebuild_needed": match_status != "matched",
        }

    total_processed = stats.get("total_draws_processed", 0)
    any_stale = any(s["match_status"] != "matched" for s in sessions.values())

    return {
        "sessions": sessions,
        "total_draws_processed": total_processed,
        "overall_status": "stale" if any_stale else "matched",
        "generated_at": datetime.now(UTC).isoformat(),
    }
