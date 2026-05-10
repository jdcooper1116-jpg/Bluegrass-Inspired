from bluegrass.app.homepage import build_homepage_view, build_session_homepage_view


def test_homepage_metadata_sessions_are_normalized() -> None:
    payload = build_homepage_view()

    assert payload["metadata"]["sessions"] == ["Midday", "Evening", "Night"]


def test_build_session_homepage_view_shape() -> None:
    payload = build_session_homepage_view("night")

    assert payload["session"] == "Night"
    assert "hero_cards" in payload
    assert "pair_spotlight" in payload
    assert "combo_spotlight" in payload
    assert "metadata" in payload
    assert payload["metadata"]["selected_session"] == "Night"
    assert all(item["session"] == "Night" for item in payload["pair_spotlight"])
    assert all(item["session"] == "Night" for item in payload["combo_spotlight"])
