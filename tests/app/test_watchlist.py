from bluegrass.app.watchlist import get_homepage_watchlist, get_watchlist


def test_get_watchlist_filters_session_and_type() -> None:
    rows = get_watchlist(session="Night", item_type="combination", limit=5)

    assert rows
    assert len(rows) == 5
    assert all(row["session"] == "Night" for row in rows)
    assert all(row["item_type"] == "combination" for row in rows)


def test_homepage_watchlist_has_expected_sections() -> None:
    payload = get_homepage_watchlist()

    assert set(payload) == {
        "midday_pairs",
        "evening_pairs",
        "night_pairs",
        "midday_combos",
        "evening_combos",
        "night_combos",
    }
    assert all(len(rows) <= 10 for rows in payload.values())
