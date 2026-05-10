from bluegrass.app.spotlight import get_homepage_spotlight, get_spotlight


def test_spotlight_dedupes_values() -> None:
    rows = get_spotlight(session="Midday", item_type="pair", limit=25)

    values = [row["value"] for row in rows]
    assert len(values) == len(set(values))


def test_homepage_spotlight_shape() -> None:
    payload = get_homepage_spotlight()

    assert set(payload) == {
        "midday_pairs",
        "evening_pairs",
        "night_pairs",
        "midday_combos",
        "evening_combos",
        "night_combos",
    }
    assert all(len(rows) <= 10 for rows in payload.values())
