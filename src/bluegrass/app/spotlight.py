"""Deduped spotlight helpers for app-facing homepage cards."""

from __future__ import annotations

from bluegrass.app.watchlist import get_watchlist


def get_spotlight(
    *,
    session: str,
    item_type: str,
    limit: int = 10,
) -> list[dict[str, str]]:
    rows = get_watchlist(session=session, item_type=item_type, limit=200)

    best_by_value: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row["value"]
        score = float(row.get("baseline_priority_score") or "0")

        existing = best_by_value.get(value)
        if existing is None:
            best_by_value[value] = row
            continue

        existing_score = float(existing.get("baseline_priority_score") or "0")
        if score > existing_score:
            best_by_value[value] = row

    deduped = sorted(
        best_by_value.values(),
        key=lambda row: float(row.get("baseline_priority_score") or "0"),
        reverse=True,
    )

    return deduped[:limit]


def get_homepage_spotlight() -> dict[str, list[dict[str, str]]]:
    return {
        "midday_pairs": get_spotlight(session="Midday", item_type="pair", limit=10),
        "evening_pairs": get_spotlight(session="Evening", item_type="pair", limit=10),
        "night_pairs": get_spotlight(session="Night", item_type="pair", limit=10),
        "midday_combos": get_spotlight(session="Midday", item_type="combination", limit=10),
        "evening_combos": get_spotlight(session="Evening", item_type="combination", limit=10),
        "night_combos": get_spotlight(session="Night", item_type="combination", limit=10),
    }
