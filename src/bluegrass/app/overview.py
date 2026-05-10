"""Cross-session all-draws overview board.

build_all_draws_overview aggregates Midday, Evening, and Night session boards
into a single compact view. Items that appear across multiple sessions are
boosted and their session provenance is preserved.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bluegrass.app.board import (
    _SHORTLIST_QUOTA,
    _family_max_ds,
    _recency_factor,
    _score_combo,
    _score_pair,
    _score_sum,
    build_session_board,
)

_SESSIONS = ("Midday", "Evening", "Night")
_SECTION_LIMIT = 5   # top cards per family section in overview
_SESSION_BOOST = 0.3  # score multiplier bonus per additional session


def _ds_float(val: Any) -> float:
    try:
        return float(val or 0)
    except (TypeError, ValueError):
        return 0.0


def _aggregate_section(
    section_key: str,
    session_boards: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge one family section across all sessions, adding provenance fields.

    Groups by value. draws_since = max across sessions (most-overdue wins).
    last_seen = max (most recent). Boosts score for multi-session items.
    """
    by_value: dict[str, dict[str, Any]] = {}

    # Track (session, value) pairs to avoid double-counting same-value multi-subtype cards
    seen_session_value: set[tuple[str, str]] = set()

    for session, board in session_boards.items():
        for card in board.get(section_key, []):
            key = str(card.get("value", ""))
            if not key:
                continue
            sv = (session, key)
            if sv in seen_session_value:
                continue
            seen_session_value.add(sv)

            if key not in by_value:
                by_value[key] = {
                    k: v for k, v in card.items()
                    if k not in ("session",)
                }
                by_value[key]["sessions_present"] = []
                by_value[key]["support_count"] = 0

            by_value[key]["sessions_present"].append(session)
            by_value[key]["support_count"] += 1

            # Keep the most-overdue draws_since
            existing_ds = _ds_float(by_value[key].get("draws_since", 0))
            incoming_ds = _ds_float(card.get("draws_since", 0))
            if incoming_ds > existing_ds:
                by_value[key]["draws_since"] = card["draws_since"]
                by_value[key]["why_flagged"] = card.get("why_flagged", "")
                by_value[key]["last_seen"] = card.get("last_seen", "")
                if "subtype" in card:
                    by_value[key]["subtype"] = card["subtype"]

    # Score with session boost and sort
    all_rows = list(by_value.values())
    max_ds = max((_ds_float(r.get("draws_since", 0)) for r in all_rows), default=1.0) or 1.0

    for row in all_rows:
        ds = _ds_float(row.get("draws_since", 0))
        boost = 1.0 + _SESSION_BOOST * (row["support_count"] - 1)
        row["_score"] = (ds / max_ds) * boost

    all_rows.sort(key=lambda r: r["_score"], reverse=True)
    return [{k: v for k, v in r.items() if k != "_score"} for r in all_rows[:_SECTION_LIMIT]]


def _consensus_shortlist(
    session_boards: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a balanced 12-entry shortlist from the aggregated section cards.

    Uses the same 3-per-family quota as board.py, scored by the per-family
    normalized draws_since with session-count boost.
    """
    section_map = {
        "sum": "top_sums",
        "root_sum": "top_root_sums",
        "pair": "top_pairs",
        "combination": "top_combinations",
    }

    scored_buckets: list[list[tuple[float, dict[str, Any]]]] = []

    for family, section_key in section_map.items():
        # Re-aggregate to get full candidate pool (not truncated to _SECTION_LIMIT)
        by_value: dict[str, dict[str, Any]] = {}
        seen_session_value_inner: set[tuple[str, str]] = set()
        for session, board in session_boards.items():
            for card in board.get(section_key, []):
                key = str(card.get("value", ""))
                if not key:
                    continue
                sv = (session, key)
                if sv in seen_session_value_inner:
                    continue
                seen_session_value_inner.add(sv)
                if key not in by_value:
                    by_value[key] = {k: v for k, v in card.items() if k != "session"}
                    by_value[key]["sessions_present"] = []
                    by_value[key]["support_count"] = 0
                by_value[key]["sessions_present"].append(session)
                by_value[key]["support_count"] += 1
                existing_ds = _ds_float(by_value[key].get("draws_since", 0))
                incoming_ds = _ds_float(card.get("draws_since", 0))
                if incoming_ds > existing_ds:
                    by_value[key]["draws_since"] = card["draws_since"]
                    by_value[key]["why_flagged"] = card.get("why_flagged", "")
                    by_value[key]["last_seen"] = card.get("last_seen", "")
                    if "subtype" in card:
                        by_value[key]["subtype"] = card["subtype"]

        rows = list(by_value.values())
        max_ds = _family_max_ds(rows) or 1.0

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            boost = 1.0 + _SESSION_BOOST * (row["support_count"] - 1)
            if family in ("sum", "root_sum"):
                base = _score_sum({"draws_since": _ds_float(row.get("draws_since", 0))}, max_ds)
            elif family == "pair":
                base = _score_pair(row, max_ds)
            else:
                base = _score_combo(row, max_ds)
            scored.append((base * boost, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        scored_buckets.append(scored[:_SHORTLIST_QUOTA])

    # Merge quota slots and sort by score
    merged: list[tuple[float, dict[str, Any]]] = []
    for bucket in scored_buckets:
        merged.extend(bucket)

    merged.sort(key=lambda x: x[0], reverse=True)

    return [{k: v for k, v in row.items() if k != "_score"} for _, row in merged]


def _session_overlap(
    session_boards: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Items appearing in 2+ sessions across all family sections."""
    section_map = {
        "sum": "top_sums",
        "root_sum": "top_root_sums",
        "pair": "top_pairs",
        "combination": "top_combinations",
    }

    seen: dict[str, dict[str, Any]] = {}
    seen_session_value: set[tuple[str, str]] = set()

    for family, section_key in section_map.items():
        for session, board in session_boards.items():
            for card in board.get(section_key, []):
                value = str(card.get("value", ""))
                if not value:
                    continue
                sv = (session, f"{family}:{value}")
                if sv in seen_session_value:
                    continue
                seen_session_value.add(sv)
                key = f"{family}:{value}"
                if key not in seen:
                    seen[key] = {
                        "family": family,
                        "value": value,
                        "draws_since": card.get("draws_since", ""),
                        "last_seen": card.get("last_seen", ""),
                        "sessions_present": [],
                        "support_count": 0,
                    }
                seen[key]["sessions_present"].append(session)
                seen[key]["support_count"] += 1
                existing_ds = _ds_float(seen[key].get("draws_since", 0))
                incoming_ds = _ds_float(card.get("draws_since", 0))
                if incoming_ds > existing_ds:
                    seen[key]["draws_since"] = card["draws_since"]

    overlap = [v for v in seen.values() if v["support_count"] >= 2]
    overlap.sort(key=lambda x: (x["support_count"], _ds_float(x["draws_since"])), reverse=True)
    return overlap


def _build_rationale(
    top_sums: list[dict[str, Any]],
    top_pairs: list[dict[str, Any]],
    overlap: list[dict[str, Any]],
    shortlist: list[dict[str, Any]],
) -> str:
    parts = ["All draws"]

    if top_sums:
        s = top_sums[0]
        sc = s["support_count"]
        parts.append(
            f"sum {s['value']} absent {s['draws_since']} draws"
            f" ({sc} session{'s' if sc > 1 else ''})"
        )

    if top_pairs:
        p = top_pairs[0]
        parts.append(f"pair {p['value']} absent {p['draws_since']} draws")

    if overlap:
        parts.append(f"{len(overlap)} item{'s' if len(overlap) != 1 else ''} flagged in 2+ sessions")

    family_count = len({e["family"] for e in shortlist})
    parts.append(f"consensus shortlist spans {family_count} families ({len(shortlist)} plays)")

    return ". ".join(parts) + "."


def build_all_draws_overview() -> dict[str, Any]:
    """Aggregate Midday, Evening, and Night into one cross-session board.

    Each section card carries sessions_present and support_count provenance.
    Items appearing across multiple sessions receive a score boost.
    Consensus shortlist uses 3-per-family quotas for balance.
    """
    session_boards = {s: build_session_board(s) for s in _SESSIONS}

    top_sums = _aggregate_section("top_sums", session_boards)
    top_root_sums = _aggregate_section("top_root_sums", session_boards)
    top_pairs = _aggregate_section("top_pairs", session_boards)
    top_combinations = _aggregate_section("top_combinations", session_boards)

    shortlist = _consensus_shortlist(session_boards)
    overlap = _session_overlap(session_boards)

    rationale = _build_rationale(top_sums, top_pairs, overlap, shortlist)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "top_sums": top_sums,
        "top_root_sums": top_root_sums,
        "top_pairs": top_pairs,
        "top_combinations": top_combinations,
        "consensus_shortlist": shortlist,
        "session_overlap": overlap,
        "rationale": rationale,
        "metadata": {
            "sessions": list(_SESSIONS),
            "source": "baseline+runtime",
            "generated_at": generated_at,
        },
    }
