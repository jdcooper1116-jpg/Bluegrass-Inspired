from bluegrass.app.dashboard import get_dashboard_payload


def test_dashboard_payload_shape() -> None:
    payload = get_dashboard_payload()

    assert set(payload) == {"baseline_summary", "spotlight", "watchlist"}

    summary = payload["baseline_summary"]
    spotlight = payload["spotlight"]
    watchlist = payload["watchlist"]

    assert summary["total_runs"] == 47
    assert summary["pair_rows"] == 2630
    assert summary["combination_rows"] == 4880

    assert "midday_pairs" in spotlight
    assert "evening_pairs" in spotlight
    assert "night_pairs" in spotlight
    assert "midday_combos" in spotlight
    assert "evening_combos" in spotlight
    assert "night_combos" in spotlight

    assert "midday_pairs" in watchlist
    assert "evening_pairs" in watchlist
    assert "night_pairs" in watchlist
    assert "midday_combos" in watchlist
    assert "evening_combos" in watchlist
    assert "night_combos" in watchlist
