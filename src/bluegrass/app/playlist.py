"""Session stats and playlist builder."""

from __future__ import annotations

from typing import Any

from bluegrass.app.watchlist import get_watchlist
from bluegrass.research.stats_store import load_stats_state
from bluegrass.research.sums import build_root_sums_board, build_sums_board

_VALID_SESSIONS = frozenset({"Midday", "Evening", "Night"})
_FAMILY_PULL = 10
_DEFAULT_LIMIT = 20
_FAMILY_CAP = 5   # max entries per family in the merged shortlist


def _score_sum_row(row: dict[str, Any], max_draws_since: float) -> float:
    """Blend overdue pressure (60%) into a 0-1 score."""
    overdue = row["draws_since"] / max_draws_since if max_draws_since > 0 else 0.0
    return round(0.6 * overdue, 6)


def _score_watchlist_row(row: dict[str, Any], max_ds: float) -> float:
    """Blend overdue pressure (60%) + below-expected frequency (40%)."""
    ds_raw = row.get("draws_since", 0)
    try:
        draws_since = float(ds_raw)
    except (TypeError, ValueError):
        draws_since = 0.0

    overdue = draws_since / max_ds if max_ds > 0 else 0.0

    try:
        times = float(row.get("times_drawn") or 0)
        expected = float(row.get("expected_times") or 0)
        below_expected = max(0.0, (expected - times) / expected) if expected > 0 else 0.0
    except (TypeError, ValueError):
        below_expected = 0.0

    try:
        priority = float(row.get("baseline_priority_score") or 0)
        priority_norm = min(priority / 25.0, 1.0)
    except (TypeError, ValueError):
        priority_norm = 0.0

    raw = 0.6 * overdue + 0.3 * below_expected + 0.1 * priority_norm
    return round(raw, 6)


def _build_shortlist(
    session: str,
    sums: list[dict[str, Any]],
    root_sums: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    combos: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    all_ds: list[float] = []
    for r in sums + root_sums:
        try:
            all_ds.append(float(r["draws_since"]))
        except (TypeError, ValueError):
            pass
    for r in pairs + combos:
        try:
            all_ds.append(float(r.get("draws_since", 0)))
        except (TypeError, ValueError):
            pass
    max_ds = max(all_ds, default=1.0) or 1.0

    candidates: list[dict[str, Any]] = []

    for row in sums:
        candidates.append({
            "family": "sum",
            "value": row["value"],
            "draws_since": row["draws_since"],
            "last_seen": row.get("last_seen", ""),
            "why_flagged": f"sum {row['value']} overdue – {row['draws_since']} draws since last seen",
            "subtype": None,
            "session": session,
            "_score": _score_sum_row(row, max_ds),
        })

    for row in root_sums:
        candidates.append({
            "family": "root_sum",
            "value": row["value"],
            "draws_since": row["draws_since"],
            "last_seen": row.get("last_seen", ""),
            "why_flagged": f"root sum {row['value']} overdue – {row['draws_since']} draws since last seen",
            "subtype": None,
            "session": session,
            "_score": _score_sum_row(row, max_ds),
        })

    for row in pairs:
        candidates.append({
            "family": "pair",
            "value": row.get("value", ""),
            "draws_since": row.get("draws_since", ""),
            "last_seen": row.get("last_seen", ""),
            "why_flagged": row.get("why_flagged", ""),
            "subtype": row.get("subtype"),
            "session": session,
            "_score": _score_watchlist_row(row, max_ds),
        })

    for row in combos:
        candidates.append({
            "family": "combination",
            "value": row.get("value", ""),
            "draws_since": row.get("draws_since", ""),
            "last_seen": row.get("last_seen", ""),
            "why_flagged": row.get("why_flagged", ""),
            "subtype": row.get("subtype"),
            "session": session,
            "_score": _score_watchlist_row(row, max_ds),
        })

    candidates.sort(key=lambda r: r["_score"], reverse=True)

    # Enforce family diversity: cap each family at _FAMILY_CAP before final cutoff
    family_counts: dict[str, int] = {}
    shortlist: list[dict[str, Any]] = []
    for c in candidates:
        fam = c["family"]
        if family_counts.get(fam, 0) >= _FAMILY_CAP:
            continue
        family_counts[fam] = family_counts.get(fam, 0) + 1
        entry = {k: v for k, v in c.items() if k != "_score"}
        shortlist.append(entry)
        if len(shortlist) >= limit:
            break

    return shortlist


def _last_processed_draw(session: str) -> str:
    state = load_stats_state()
    ids = (
        state.get("by_session", {})
        .get(session, {})
        .get("processed_draw_ids", [])
    )
    return ids[-1] if ids else ""


def build_session_stats(session: str) -> dict[str, Any]:
    """Return all four overdue-family boards plus playlist_preview and metadata."""
    if session not in _VALID_SESSIONS:
        raise ValueError(f"unrecognized session: {session!r}")

    sums = build_sums_board(session)
    root_sums = build_root_sums_board(session)
    pairs = get_watchlist(session=session, item_type="pair", limit=50)
    combinations = get_watchlist(session=session, item_type="combination", limit=50)

    preview = _build_shortlist(
        session,
        sums[:_FAMILY_PULL],
        root_sums[:_FAMILY_PULL],
        pairs[:_FAMILY_PULL],
        combinations[:_FAMILY_PULL],
        limit=10,
    )

    return {
        "session": session,
        "sums": sums,
        "root_sums": root_sums,
        "pairs": pairs,
        "combinations": combinations,
        "playlist_preview": preview,
        "metadata": {
            "session": session,
            "source": "baseline+runtime",
            "last_processed_draw": _last_processed_draw(session),
        },
    }


def build_session_playlist(session: str, *, limit: int = _DEFAULT_LIMIT) -> dict[str, Any]:
    """Build a daily narrowed shortlist for one session with blended ranking."""
    if session not in _VALID_SESSIONS:
        raise ValueError(f"unrecognized session: {session!r}")

    sums = build_sums_board(session, limit=_FAMILY_PULL)
    root_sums = build_root_sums_board(session, limit=_FAMILY_PULL)
    pairs = get_watchlist(session=session, item_type="pair", limit=_FAMILY_PULL)
    combos = get_watchlist(session=session, item_type="combination", limit=_FAMILY_PULL)

    shortlist = _build_shortlist(session, sums, root_sums, pairs, combos, limit=limit)

    return {
        "session": session,
        "sums": sums,
        "root_sums": root_sums,
        "pairs": pairs,
        "combinations": combos,
        "shortlist": shortlist,
        "shortlist_count": len(shortlist),
    }
