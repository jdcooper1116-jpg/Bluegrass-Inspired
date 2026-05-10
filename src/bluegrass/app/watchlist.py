"""App-facing watchlist helpers powered by the baseline packet."""

from __future__ import annotations

from bluegrass.research.baseline import filter_priority_shortlist


def get_watchlist(
    *,
    session: str | None = None,
    item_type: str | None = None,
    subtype: str | None = None,
    limit: int = 25,
) -> list[dict[str, str]]:
    return filter_priority_shortlist(
        session=session,
        item_type=item_type,
        subtype=subtype,
        limit=limit,
    )


def get_homepage_watchlist() -> dict[str, list[dict[str, str]]]:
    return {
        "midday_pairs": get_watchlist(session="Midday", item_type="pair", limit=10),
        "evening_pairs": get_watchlist(session="Evening", item_type="pair", limit=10),
        "night_pairs": get_watchlist(session="Night", item_type="pair", limit=10),
        "midday_combos": get_watchlist(session="Midday", item_type="combination", limit=10),
        "evening_combos": get_watchlist(session="Evening", item_type="combination", limit=10),
        "night_combos": get_watchlist(session="Night", item_type="combination", limit=10),
    }
