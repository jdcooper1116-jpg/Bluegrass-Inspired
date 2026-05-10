from bluegrass.app.session_cards import build_session_cards


def test_build_session_cards_shape() -> None:
    payload = build_session_cards("Night")

    assert payload["session"] == "Night"
    assert "stats_header" in payload
    assert "pair_cards" in payload
    assert "combo_cards" in payload
    assert "why_flagged_summary" in payload
    assert payload["metadata"]["selected_session"] == "Night"


def test_session_cards_are_session_scoped() -> None:
    payload = build_session_cards("Midday")

    assert all(card["session"] == "Midday" for card in payload["pair_cards"])
    assert all(card["session"] == "Midday" for card in payload["combo_cards"])
