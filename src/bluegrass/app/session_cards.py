from __future__ import annotations

from collections import Counter
from typing import Any

from bluegrass.app.homepage import build_session_homepage_view


def _compact_card(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_type": item.get("item_type"),
        "session": item.get("session"),
        "subtype": item.get("subtype"),
        "value": item.get("value"),
        "times_drawn": item.get("times_drawn"),
        "expected_times": item.get("expected_times"),
        "draws_since": item.get("draws_since"),
        "last_seen": item.get("last_seen"),
        "baseline_priority_score": item.get("baseline_priority_score"),
        "why_flagged": item.get("why_flagged"),
    }


def _summarize_reasons(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()

    for item in items:
        reason = str(item.get("why_flagged") or "priority").strip() or "priority"
        counts[reason] += 1

    return [
        {"reason": reason, "count": count}
        for reason, count in counts.most_common(5)
    ]


def build_session_cards(session: str) -> dict[str, Any]:
    payload = build_session_homepage_view(session)

    pair_cards = [_compact_card(item) for item in payload["pair_spotlight"]]
    combo_cards = [_compact_card(item) for item in payload["combo_spotlight"]]

    return {
        "session": payload["session"],
        "stats_header": {
            "pair_count": len(pair_cards),
            "combo_count": len(combo_cards),
            "selected_session": payload["metadata"]["selected_session"],
        },
        "pair_cards": pair_cards,
        "combo_cards": combo_cards,
        "why_flagged_summary": {
            "pairs": _summarize_reasons(pair_cards),
            "combinations": _summarize_reasons(combo_cards),
        },
        "metadata": payload["metadata"],
    }
