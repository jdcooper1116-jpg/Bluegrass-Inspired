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

# Freshness statuses that are explicitly untrustworthy.
# Snapshots with no freshness field at all are treated as trusted (backward compat).
_UNTRUSTED_FRESHNESS: frozenset[str] = frozenset(
    {"stale", "baseline-only", "engine-unknown"}
)


def _is_trusted(snap: dict[str, Any]) -> bool:
    """Return True if the snapshot is trustworthy for reliability metrics.

    A snapshot is untrusted only when its freshness status is explicitly one
    of the known-bad values.  Snapshots with no freshness field (written before
    the transparency slice) are treated as trusted so that existing test data
    and older ledger files do not collapse the headline metrics to zero.
    """
    status = snap.get("snapshot_freshness_status")
    if status is None:
        return True   # no field → old snapshot → assume trusted
    return status not in _UNTRUSTED_FRESHNESS


# ---------------------------------------------------------------------------
# Metrics computation (pure — no I/O)
# ---------------------------------------------------------------------------

def compute_reliability_metrics(
    snaps: list[dict[str, Any]],
    *,
    trusted_only: bool = False,
) -> dict[str, Any]:
    """Compute hit-rate metrics from a list of forecast snapshots.

    Parameters
    ----------
    trusted_only:
        If True, only snapshots considered trusted (see _is_trusted) are
        counted.  The returned dict includes "untrusted_excluded" to show
        how many were filtered out.

    Handles empty lists and unscored snapshots gracefully.
    All rates are in [0.0, 1.0]; formatted as percentages in templates.
    """
    if trusted_only:
        working = [s for s in snaps if _is_trusted(s)]
        untrusted_excluded = len(snaps) - len(working)
    else:
        working = snaps
        untrusted_excluded = 0

    scored = [s for s in working if s.get("result") is not None and s.get("hits")]
    n = len(scored)

    def _rate(key: str) -> float:
        if n == 0:
            return 0.0
        return round(sum(1 for s in scored if s["hits"].get(key)) / n, 4)

    return {
        "total_snapshots":    len(working),
        "scored_snapshots":   n,
        "unscored_snapshots": len(working) - n,
        "untrusted_excluded": untrusted_excluded,
        "trusted_only":       trusted_only,
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
    """Add display-ready fields to a raw snapshot dict.

    Handles both old snapshots (missing attribution fields) and new ones
    gracefully — all new fields fall back to safe defaults.
    """
    s = dict(snap)
    hits = s.get("hits") or {}
    s["is_scored"] = s.get("result") is not None

    # ── Original boolean flags ────────────────────────────────────────────
    s["hit_exact"]  = hits.get("exact", False)
    s["hit_box"]    = hits.get("box", False)
    s["hit_pair"]   = hits.get("pair_hit", False)
    s["hit_sum"]    = hits.get("sum_hit", False)
    s["hit_root"]   = hits.get("root_hit", False)
    s["hit_any"]    = hits.get("any_hit", False)
    s["hit_near"]   = hits.get("near_miss", False)

    # ── Richer attribution (new — may be absent in old snapshots) ─────────
    s["verdict"]            = hits.get("verdict", "")
    s["result_in_tier"]     = hits.get("result_in_tier")
    s["result_box_in_tier"] = hits.get("result_box_in_tier")
    s["support_channels"]   = hits.get("support_channels", [])

    # ── Snapshot freshness metadata ───────────────────────────────────────
    s["snapshot_freshness_status"]  = s.get("snapshot_freshness_status")   # None → old snap
    s["snapshot_source_state_date"] = s.get("snapshot_source_state_date")
    s["snapshot_draws_behind"]      = s.get("snapshot_draws_behind")

    # ── Trust flag ────────────────────────────────────────────────────────
    s["is_trusted"] = _is_trusted(s)

    # ── Tier contents for templates ───────────────────────────────────────
    tier_1 = s.get("tier_1", [])
    tier_2 = s.get("tier_2", [])
    tier_3 = s.get("tier_3", [])

    s["tier_1_numbers"]   = [c["number"] for c in tier_1]
    s["tier_2_numbers"]   = [c["number"] for c in tier_2]
    s["tier_3_numbers"]   = [c["number"] for c in tier_3]
    s["tier_1_preview"]   = s["tier_1_numbers"][:5]
    s["tier_1_count"]     = len(tier_1)
    s["tier_2_count"]     = len(tier_2)
    s["tier_3_count"]     = len(tier_3)
    s["total_candidates"] = len(tier_1) + len(tier_2) + len(tier_3)

    return s


def _add_pct(m: dict[str, Any]) -> dict[str, Any]:
    """Attach percentage-formatted strings to a metrics dict (mutates in place)."""
    m["any_hit_pct"]   = _pct(m["any_hit_rate"])
    m["exact_pct"]     = _pct(m["exact_rate"])
    m["box_pct"]       = _pct(m["box_rate"])
    m["pair_pct"]      = _pct(m["pair_rate"])
    m["sum_pct"]       = _pct(m["sum_rate"])
    m["root_pct"]      = _pct(m["root_rate"])
    m["near_miss_pct"] = _pct(m["near_miss_rate"])
    return m


# ---------------------------------------------------------------------------
# Public view builders
# ---------------------------------------------------------------------------

def build_ledger_overview() -> dict[str, Any]:
    """Data for the /ledger overview page.

    Keys
    ----
    overall         — metrics over ALL snapshots (backward-compatible default)
    overall_trusted — metrics over trusted-only snapshots
    by_session      — per-session dict; each value has "all" and "trusted" sub-dicts
    recent          — most recent RECENT_WINDOW snapshots (enriched)
    generated_at    — ISO timestamp
    """
    all_snaps = list_forecasts()

    overall     = _add_pct(compute_reliability_metrics(all_snaps, trusted_only=False))
    overall_trusted = _add_pct(compute_reliability_metrics(all_snaps, trusted_only=True))

    by_session: dict[str, Any] = {}
    for sess in _VALID_SESSIONS:
        sess_snaps = [s for s in all_snaps if s.get("session") == sess]
        by_session[sess] = {
            "all":     _add_pct(compute_reliability_metrics(sess_snaps, trusted_only=False)),
            "trusted": _add_pct(compute_reliability_metrics(sess_snaps, trusted_only=True)),
            # Flat keys kept for backward-compat with existing templates
            **_add_pct(compute_reliability_metrics(sess_snaps, trusted_only=False)),
        }

    recent_all = [_enrich_snap(s) for s in all_snaps[:_RECENT_WINDOW]]

    return {
        "overall":          overall,          # all snapshots — backward-compat default
        "overall_trusted":  overall_trusted,  # trusted-only — new
        "by_session":       by_session,
        "recent":           recent_all,
        "generated_at":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def build_ledger_session(session: str) -> dict[str, Any]:
    """Data for the /ledger/session/{session} page.

    Keys
    ----
    session         — session name
    metrics         — metrics over ALL snapshots (backward-compatible default)
    metrics_trusted — metrics over trusted-only snapshots
    forecasts       — all snapshots (enriched, date-desc)
    recent          — same, capped to RECENT_WINDOW
    generated_at    — ISO timestamp
    """
    if session not in _VALID_SESSIONS:
        raise ValueError(f"unrecognized session: {session!r}")

    snaps           = list_forecasts(session=session)
    metrics         = _add_pct(compute_reliability_metrics(snaps, trusted_only=False))
    metrics_trusted = _add_pct(compute_reliability_metrics(snaps, trusted_only=True))
    enriched        = [_enrich_snap(s) for s in snaps]

    return {
        "session":          session,
        "metrics":          metrics,          # all snapshots — backward-compat default
        "metrics_trusted":  metrics_trusted,  # trusted-only — new
        "forecasts":        enriched,
        "recent":           enriched[:_RECENT_WINDOW],
        "generated_at":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }