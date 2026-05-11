"""Forecast Ledger view builders.

Reads from the on-disk ledger (data/runtime/forecasts/*.json) via the
existing ledger module.  No writes happen here — this is presentation-only.

Public API
----------
compute_reliability_metrics(snaps)  — pure function, testable in isolation
build_ledger_overview()             — data for /ledger
build_ledger_session(session)       — data for /ledger/session/{session}
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bluegrass.app.playlist import _VALID_SESSIONS
from bluegrass.research.ledger import list_forecasts

_HIT_KEYS = ("exact", "box", "pair_hit", "sum_hit", "root_hit", "any_hit", "near_miss")
_RECENT_WINDOW = 30


# ---------------------------------------------------------------------------
# Metrics computation (pure — no I/O)
# ---------------------------------------------------------------------------

def compute_reliability_metrics(snaps: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute hit-rate metrics from a list of forecast snapshots.

    Handles empty lists and unscored snapshots gracefully.
    All rates are in [0.0, 1.0]; formatted as percentages in templates.
    """
    scored = [s for s in snaps if s.get("result") is not None and s.get("hits")]
    n = len(scored)

    def _rate(key: str) -> float:
        if n == 0:
            return 0.0
        return round(sum(1 for s in scored if s["hits"].get(key)) / n, 4)

    return {
        "total_snapshots":    len(snaps),
        "scored_snapshots":   n,
        "unscored_snapshots": len(snaps) - n,
        "exact_rate":         _rate("exact"),
        "box_rate":           _rate("box"),
        "pair_rate":          _rate("pair_hit"),
        "sum_rate":           _rate("sum_hit"),
        "root_rate":          _rate("root_hit"),
        "any_hit_rate":       _rate("any_hit"),
        "near_miss_rate":     _rate("near_miss"),
    }


def _pct(rate: float) -> str:
    """Format a [0,1] rate as an integer-percent string, e.g. '67%'."""
    return f"{round(rate * 100)}%"


def _enrich_snap(snap: dict[str, Any]) -> dict[str, Any]:
    """Add display-ready fields to a raw snapshot dict."""
    s = dict(snap)
    hits = s.get("hits") or {}
    s["is_scored"] = s.get("result") is not None
    s["hit_exact"]    = hits.get("exact", False)
    s["hit_box"]      = hits.get("box", False)
    s["hit_pair"]     = hits.get("pair_hit", False)
    s["hit_sum"]      = hits.get("sum_hit", False)
    s["hit_root"]     = hits.get("root_hit", False)
    s["hit_any"]      = hits.get("any_hit", False)
    s["hit_near"]     = hits.get("near_miss", False)
    # Tier 1 play numbers (up to 5 for display)
    s["tier_1_preview"] = [c["number"] for c in s.get("tier_1", [])[:5]]
    s["tier_2_count"]   = len(s.get("tier_2", []))
    s["tier_3_count"]   = len(s.get("tier_3", []))
    return s


# ---------------------------------------------------------------------------
# Public view builders
# ---------------------------------------------------------------------------

def build_ledger_overview() -> dict[str, Any]:
    """Data for the /ledger overview page.

    Returns:
        overall    — reliability metrics for all sessions combined
        by_session — {session: metrics} for each of Midday/Evening/Night
        recent     — most recent RECENT_WINDOW snapshots (enriched, all sessions)
        generated_at — ISO timestamp
    """
    all_snaps = list_forecasts()   # already sorted date-desc
    overall   = compute_reliability_metrics(all_snaps)

    by_session: dict[str, Any] = {}
    for sess in _VALID_SESSIONS:
        sess_snaps = [s for s in all_snaps if s.get("session") == sess]
        m = compute_reliability_metrics(sess_snaps)
        by_session[sess] = {
            **m,
            "any_hit_pct":  _pct(m["any_hit_rate"]),
            "exact_pct":    _pct(m["exact_rate"]),
            "box_pct":      _pct(m["box_rate"]),
            "pair_pct":     _pct(m["pair_rate"]),
            "sum_pct":      _pct(m["sum_rate"]),
            "root_pct":     _pct(m["root_rate"]),
        }

    recent_all = [_enrich_snap(s) for s in all_snaps[:_RECENT_WINDOW]]

    return {
        "overall": {
            **overall,
            "any_hit_pct":  _pct(overall["any_hit_rate"]),
            "exact_pct":    _pct(overall["exact_rate"]),
            "box_pct":      _pct(overall["box_rate"]),
            "pair_pct":     _pct(overall["pair_rate"]),
            "sum_pct":      _pct(overall["sum_rate"]),
            "root_pct":     _pct(overall["root_rate"]),
        },
        "by_session":    by_session,
        "recent":        recent_all,
        "generated_at":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def build_ledger_session(session: str) -> dict[str, Any]:
    """Data for the /ledger/session/{session} page.

    Returns:
        session    — session name
        metrics    — reliability metrics for this session
        forecasts  — all snapshots for this session (enriched, date-desc)
        recent     — same but capped to RECENT_WINDOW
        generated_at — ISO timestamp
    """
    if session not in _VALID_SESSIONS:
        raise ValueError(f"unrecognized session: {session!r}")

    snaps = list_forecasts(session=session)
    metrics = compute_reliability_metrics(snaps)
    enriched = [_enrich_snap(s) for s in snaps]
    recent   = enriched[:_RECENT_WINDOW]

    return {
        "session":      session,
        "metrics": {
            **metrics,
            "any_hit_pct":  _pct(metrics["any_hit_rate"]),
            "exact_pct":    _pct(metrics["exact_rate"]),
            "box_pct":      _pct(metrics["box_rate"]),
            "pair_pct":     _pct(metrics["pair_rate"]),
            "sum_pct":      _pct(metrics["sum_rate"]),
            "root_pct":     _pct(metrics["root_rate"]),
            "near_miss_pct": _pct(metrics["near_miss_rate"]),
        },
        "forecasts":    enriched,
        "recent":       recent,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
