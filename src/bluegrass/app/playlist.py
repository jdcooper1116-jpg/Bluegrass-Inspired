"""Session stats and playlist builder.

build_session_stats  – all four overdue families for one session (sums,
                        root_sums, pairs, combinations).
build_session_playlist – merges those families into a ranked shortlist with
                          why_flagged rationale on every entry.
"""

from __future__ import annotations

from typing import Any

from bluegrass.app.watchlist import get_watchlist
from bluegrass.research.sums import build_root_sums_board, build_sums_board

_VALID_SESSIONS = frozenset({"Midday", "Evening", "Night"})
_FAMILY_PULL = 8   # items fetched from each family before merging
_DEFAULT_LIMIT = 20


def build_session_stats(session: str) -> dict[str, Any]:
    """Return all four overdue-family boards for a session.

    Response keys: session, sums, root_sums, pairs, combinations.
    """
    if session not in _VALID_SESSIONS:
        raise ValueError(f"unrecognized session: {session!r}")

    return {
        "session": session,
        "sums": build_sums_board(session),
        "root_sums": build_root_sums_board(session),
        "pairs": get_watchlist(session=session, item_type="pair", limit=50),
        "combinations": get_watchlist(session=session, item_type="combination", limit=50),
    }


def build_session_playlist(session: str, *, limit: int = _DEFAULT_LIMIT) -> dict[str, Any]:
    """Build a daily narrowed shortlist for one session.

    Pulls the top items from each family, assembles them with why_flagged
    rationale, and returns the full per-family boards alongside the merged
    shortlist.
    """
    if session not in _VALID_SESSIONS:
        raise ValueError(f"unrecognized session: {session!r}")

    sums = build_sums_board(session, limit=_FAMILY_PULL)
    root_sums = build_root_sums_board(session, limit=_FAMILY_PULL)
    pairs = get_watchlist(session=session, item_type="pair", limit=_FAMILY_PULL)
    combos = get_watchlist(session=session, item_type="combination", limit=_FAMILY_PULL)

    shortlist: list[dict[str, Any]] = []

    for row in sums[:5]:
        shortlist.append({
            "family": "sum",
            "value": row["value"],
            "draws_since": row["draws_since"],
            "last_seen": row.get("last_seen", ""),
            "why_flagged": (
                f"sum {row['value']} overdue – "
                f"{row['draws_since']} draws since last seen"
            ),
            "subtype": None,
            "session": session,
        })

    for row in root_sums[:5]:
        shortlist.append({
            "family": "root_sum",
            "value": row["value"],
            "draws_since": row["draws_since"],
            "last_seen": row.get("last_seen", ""),
            "why_flagged": (
                f"root sum {row['value']} overdue – "
                f"{row['draws_since']} draws since last seen"
            ),
            "subtype": None,
            "session": session,
        })

    for row in pairs[:5]:
        shortlist.append({
            "family": "pair",
            "value": row.get("value", ""),
            "draws_since": row.get("draws_since", ""),
            "last_seen": row.get("last_seen", ""),
            "why_flagged": row.get("why_flagged", ""),
            "subtype": row.get("subtype"),
            "session": session,
        })

    for row in combos[:5]:
        shortlist.append({
            "family": "combination",
            "value": row.get("value", ""),
            "draws_since": row.get("draws_since", ""),
            "last_seen": row.get("last_seen", ""),
            "why_flagged": row.get("why_flagged", ""),
            "subtype": row.get("subtype"),
            "session": session,
        })

    merged = shortlist[:limit]
    return {
        "session": session,
        "sums": sums,
        "root_sums": root_sums,
        "pairs": pairs,
        "combinations": combos,
        "shortlist": merged,
        "shortlist_count": len(merged),
    }
