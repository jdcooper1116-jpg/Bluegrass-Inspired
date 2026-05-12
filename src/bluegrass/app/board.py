"""Daily session board builder.

build_session_board returns a compact, operator-ready view of the day's
narrowing signal for a single session. It blends baseline seed data with
any runtime-refreshed state and is sized for a card/grid UI layout.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bluegrass.app.playlist import _VALID_SESSIONS, _last_processed_draw
from bluegrass.app.watchlist import get_watchlist
from bluegrass.research.config import ANALYSIS_WINDOW_DAYS, SYNC_WINDOW_DAYS
from bluegrass.research.stats_engine import (
    PAIR_EXPECTED_GAP,
    PAIR_QUANT,
    ROOT_MAX_QUANT,
    SUM_MAX_QUANT,
    composite_score,
    compute_deviation_metrics,
    describe_deviation,
)
from bluegrass.research.sums import build_root_sums_board, build_sums_board

_SECTION_SIZE = 4   # cards shown per family section
_SHORTLIST_QUOTA = 3  # slots per family in the shortlist (sums, root_sums, pairs)
_COMBO_SHORTLIST_QUOTA = 2  # combinations capped at 2 so they can't dominate the top 5
_PULL = 10           # rows fetched per family before scoring


# ---------------------------------------------------------------------------
# Board-specific shortlist scorer — per-family normalization + recency tuning
# ---------------------------------------------------------------------------

def _recency_factor(last_seen: str) -> float:
    """0.0–1.0: higher for entries seen more recently. Never-hit = 0.0."""
    if not last_seen:
        return 0.0
    try:
        year = int(last_seen[:4])
    except (ValueError, IndexError):
        return 0.0
    if year >= 2022:
        return 1.0
    if year >= 2018:
        return 0.7
    if year >= 2015:
        return 0.4
    if year >= 2010:
        return 0.2
    return 0.0


def _family_max_ds(rows: list[dict[str, Any]]) -> float:
    vals = []
    for r in rows:
        try:
            vals.append(float(r.get("draws_since", 0) or 0))
        except (TypeError, ValueError):
            pass
    return max(vals, default=1.0) or 1.0


def _score_sum(row: dict[str, Any], max_ds: float) -> float:  # max_ds kept for API compat
    """Composite score for sums/root_sums: gap_ratio * mild structural weight.

    Uses gap_ratio pre-computed on the row (by _build_board in sums.py).
    Structural weight (quant/max_quant)^0.25 mildly favors common values:
    sum 13 (quant=75) overdue by 3x expected outranks sum 0 (quant=1) that
    has barely passed its expected gap.
    """
    quant     = row.get("combo_count", 1) or 1
    gr        = row.get("gap_ratio", 0.0)
    family    = row.get("family", "sum")
    mq        = SUM_MAX_QUANT if family == "sum" else ROOT_MAX_QUANT
    pw        = (quant / mq) ** 0.25
    return round(gr * pw, 6)


def _score_pair(row: dict[str, Any], max_ds: float) -> float:
    """Composite score for pairs: gap_ratio weighted by structural probability.

    All pair values have PAIR_QUANT=10, PAIR_EXPECTED_GAP=100.
    The gap_ratio field may not be present on watchlist pair rows, so it is
    computed inline when absent.
    """
    ds = float(row.get("draws_since") or 0)
    # Use pre-computed gap_ratio if available (enriched rows from sums.py)
    gr = row.get("gap_ratio")
    if gr is None:
        gr = ds / PAIR_EXPECTED_GAP

    # Supplement with baseline priority signal if available
    try:
        priority = min(float(row.get("baseline_priority_score") or 0) / 25.0, 1.0)
    except (TypeError, ValueError):
        priority = 0.0

    return round(0.75 * gr + 0.25 * priority, 6)


def _score_combo(row: dict[str, Any], max_ds: float) -> float:
    try:
        ds = float(row.get("draws_since", 0) or 0)
    except (TypeError, ValueError):
        ds = 0.0
    overdue = ds / max_ds

    try:
        times = float(row.get("times_drawn") or 0)
        expected = float(row.get("expected_times") or 0)
        below_exp = max(0.0, (expected - times) / expected) if expected > 0 else 0.0
    except (TypeError, ValueError):
        below_exp = 0.0

    try:
        priority = min(float(row.get("baseline_priority_score") or 0) / 25.0, 1.0)
    except (TypeError, ValueError):
        priority = 0.0

    recency = _recency_factor(str(row.get("last_seen", "") or ""))

    return round(0.40 * overdue + 0.35 * below_exp + 0.10 * priority + 0.15 * recency, 6)


def _pick_quota(
    rows: list[dict[str, Any]],
    family: str,
    score_fn: Any,
    session: str,
    quota: int,
) -> list[tuple[float, dict[str, Any]]]:
    """Score rows within their own family context and return top-quota entries."""
    max_ds = _family_max_ds(rows)
    scored = [(score_fn(r, max_ds), r) for r in rows]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:quota]


def _build_board_shortlist(
    session: str,
    sums: list[dict[str, Any]],
    root_sums: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    combos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a balanced shortlist using per-family quotas and per-family normalization.

    Guarantees _SHORTLIST_QUOTA entries from each of the four families, scored
    independently so no family's extreme draws_since drowns out the others.
    Final list is sorted by each entry's internal score for natural readability.
    """
    buckets = [
        _pick_quota(sums, "sum", _score_sum, session, _SHORTLIST_QUOTA),
        _pick_quota(root_sums, "root_sum", _score_sum, session, _SHORTLIST_QUOTA),
        _pick_quota(pairs, "pair", _score_pair, session, _SHORTLIST_QUOTA),
        _pick_quota(combos, "combination", _score_combo, session, _COMBO_SHORTLIST_QUOTA),
    ]

    family_labels = ("sum", "root_sum", "pair", "combination")
    shortlist: list[dict[str, Any]] = []

    for (scored, family) in zip(buckets, family_labels):
        for score, row in scored:
            entry = _make_shortlist_entry(row, family, session)
            shortlist.append((score, entry))

    shortlist.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in shortlist]


def _make_shortlist_entry(row: dict[str, Any], family: str, session: str) -> dict[str, Any]:
    if family in ("sum", "root_sum"):
        why = row.get("why_flagged") or (
            f"{family.replace('_', ' ')} {row['value']} overdue – "
            f"{row['draws_since']} draws since last seen"
        )
        return {
            "family":               family,
            "value":                row["value"],
            "draws_since":          row["draws_since"],
            "last_seen":            row.get("last_seen", ""),
            "why_flagged":          why,
            "subtype":              None,
            "session":              session,
            # Explainability fields for UI and debugging
            "gap_ratio":            row.get("gap_ratio"),
            "severity_band":        row.get("severity_band"),
            "multi_window_agreement": row.get("multi_window_agreement"),
            "expected_gap_draws":   row.get("expected_gap_draws"),
            "combo_count":          row.get("combo_count"),
        }
    return {
        "family":               family,
        "value":                row.get("value", ""),
        "draws_since":          row.get("draws_since", ""),
        "last_seen":            row.get("last_seen", ""),
        "why_flagged":          row.get("why_flagged", ""),
        "subtype":              row.get("subtype"),
        "session":              session,
        "gap_ratio":            row.get("gap_ratio"),
        "severity_band":        row.get("severity_band"),
        "multi_window_agreement": row.get("multi_window_agreement"),
    }


# ---------------------------------------------------------------------------
# Compact card builders for section displays
# ---------------------------------------------------------------------------

def _compact_sum_card(row: dict[str, Any], family: str) -> dict[str, Any]:
    return {
        "family": family,
        "value": row["value"],
        "draws_since": row["draws_since"],
        "last_seen": row.get("last_seen", ""),
        "why_flagged": f"{family.replace('_', ' ')} {row['value']} overdue – {row['draws_since']} draws since last seen",
    }


def _compact_watchlist_card(row: dict[str, Any], family: str) -> dict[str, Any]:
    return {
        "family": family,
        "value": row.get("value", ""),
        "subtype": row.get("subtype", ""),
        "draws_since": row.get("draws_since", ""),
        "last_seen": row.get("last_seen", ""),
        "why_flagged": row.get("why_flagged", ""),
    }


def _build_rationale(
    session: str,
    top_sums: list[dict[str, Any]],
    top_root_sums: list[dict[str, Any]],
    top_pairs: list[dict[str, Any]],
    top_combos: list[dict[str, Any]],
    shortlist: list[dict[str, Any]],
) -> str:
    parts: list[str] = [f"{session}"]

    if top_sums:
        s = top_sums[0]
        parts.append(f"sum {s['value']} absent {s['draws_since']} draws (last {s['last_seen']})")

    if top_root_sums:
        rs = top_root_sums[0]
        parts.append(f"root sum {rs['value']} absent {rs['draws_since']} draws")

    if top_pairs:
        p = top_pairs[0]
        parts.append(f"pair {p['value']} absent {p['draws_since']} draws")

    if top_combos:
        c = top_combos[0]
        parts.append(f"combo {c['value']} last seen {c['last_seen']}")

    family_count = len({e["family"] for e in shortlist})
    parts.append(f"shortlist spans {family_count} families ({len(shortlist)} plays)")

    return ". ".join(parts) + "."


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_session_board(session: str) -> dict[str, Any]:
    """Return a compact daily board for one session.

    Sections: top_sums, top_root_sums, top_pairs, top_combinations (4 cards each).
    Shortlist: 3 per family (12 total), balanced via per-family quotas.
    Rationale: one-sentence summary of the day's signal.
    Metadata: session, source, last_processed_draw, generated_at.
    """
    if session not in _VALID_SESSIONS:
        raise ValueError(f"unrecognized session: {session!r}")

    sums_board = build_sums_board(session, limit=_PULL)
    root_sums_board = build_root_sums_board(session, limit=_PULL)
    pairs_raw = get_watchlist(session=session, item_type="pair", limit=_PULL)
    combos_raw = get_watchlist(session=session, item_type="combination", limit=_PULL)

    top_sums = [_compact_sum_card(r, "sum") for r in sums_board[:_SECTION_SIZE]]
    top_root_sums = [_compact_sum_card(r, "root_sum") for r in root_sums_board[:_SECTION_SIZE]]
    top_pairs = [_compact_watchlist_card(r, "pair") for r in pairs_raw[:_SECTION_SIZE]]
    top_combos = [_compact_watchlist_card(r, "combination") for r in combos_raw[:_SECTION_SIZE]]

    shortlist = _build_board_shortlist(session, sums_board, root_sums_board, pairs_raw, combos_raw)

    rationale = _build_rationale(session, top_sums, top_root_sums, top_pairs, top_combos, shortlist)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "session": session,
        "top_sums": top_sums,
        "top_root_sums": top_root_sums,
        "top_pairs": top_pairs,
        "top_combinations": top_combos,
        "shortlist": shortlist,
        "rationale": rationale,
        "metadata": {
            "session": session,
            "source": "engine-runtime",
            "analysis_window_days": ANALYSIS_WINDOW_DAYS,
            "sync_window_days": SYNC_WINDOW_DAYS,
            "last_processed_draw": _last_processed_draw(session),
            "generated_at": generated_at,
        },
    }
