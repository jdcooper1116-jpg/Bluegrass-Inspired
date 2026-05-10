from bluegrass.app.homepage import build_homepage_view


def test_build_homepage_view_shape() -> None:
    payload = build_homepage_view()

    assert "hero_cards" in payload
    assert "session_spotlights" in payload
    assert "priority_combos" in payload
    assert "metadata" in payload

    assert len(payload["hero_cards"]) == 4
    assert set(payload["session_spotlights"].keys()) == {"midday", "evening", "night"}
    assert set(payload["priority_combos"].keys()) == {"midday", "evening", "night"}

    assert payload["metadata"]["jurisdictions"] == ["GA"]
    assert payload["metadata"]["game_family"] == ["Pick 3"]
