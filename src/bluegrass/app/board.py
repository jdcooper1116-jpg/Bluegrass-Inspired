"""Daily session board builder.

build_session_board returns a compact, operator-ready view of the day's
narrowing signal for a single session. It blends baseline seed data with
any runtime-refreshed state and is sized for a card/grid UI layout.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bluegrass.app.playlist import (
    _VALID_SESSIONS,
    _build_shortlist,
    _last_processed_draw,
)
from bluegrass.app.watchlist import get_watchlist
from bluegrass.research.sums import build_root_sums_board, build_sums_board

_SECTION_SIZE = 4   # cards shown per family section
_SHORTLIST_LIMIT = 12
_PULL = 10          # rows fetched per family before scoring


def _compact_sum_card(row: dict[str, Any], family: str) -> dict[str, Any]:
    return {
        "family": family,
        "value": row["value"],
        "draws_since": row["draws_since"],
        "last_seen": row.get("last_seen", ""),
        "why_flagged": row.get("why_flagged", f"{family} {row['value']} overdue – {row['draws_since']} draws since last seen"),
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


def build_session_board(session: str) -> dict[str, Any]:
    """Return a compact daily board for one session.

    Sections: top_sums, top_root_sums, top_pairs, top_combinations (4 cards each).
    Shortlist: top 12 blended across all families with diversity cap.
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

    shortlist = _build_shortlist(
        session,
        sums_board,
        root_sums_board,
        pairs_raw,
        combos_raw,
        limit=_SHORTLIST_LIMIT,
    )

    rationale = _build_rationale(
        session, top_sums, top_root_sums, top_pairs, top_combos, shortlist
    )

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
            "source": "baseline+runtime",
            "last_processed_draw": _last_processed_draw(session),
            "generated_at": generated_at,
        },
    }
