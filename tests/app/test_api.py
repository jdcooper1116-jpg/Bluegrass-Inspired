import pytest
from fastapi.testclient import TestClient

from bluegrass.api import app
from bluegrass.research.stats_store import reset_stats_state

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_baseline_summary_endpoint() -> None:
    response = client.get("/baseline/summary")
    assert response.status_code == 200

    payload = response.json()
    assert payload["total_runs"] == 47
    assert payload["pair_rows"] == 2630
    assert payload["combination_rows"] == 4880


def test_dashboard_homepage_endpoint() -> None:
    response = client.get("/dashboard/homepage")
    assert response.status_code == 200

    payload = response.json()
    assert "baseline_summary" in payload
    assert "spotlight" in payload
    assert "watchlist" in payload


def test_dashboard_homepage_view_endpoint() -> None:
    response = client.get("/dashboard/homepage-view")
    assert response.status_code == 200

    payload = response.json()
    assert "hero_cards" in payload
    assert "session_spotlights" in payload
    assert "priority_combos" in payload
    assert "metadata" in payload


def test_dashboard_session_endpoint() -> None:
    response = client.get("/dashboard/session/Night")
    assert response.status_code == 200

    payload = response.json()
    assert payload["session"] == "Night"
    assert "pair_spotlight" in payload
    assert "combo_spotlight" in payload
    assert payload["metadata"]["selected_session"] == "Night"


def test_dashboard_session_endpoint_rejects_invalid_session() -> None:
    response = client.get("/dashboard/session/Weekend")
    assert response.status_code == 404


def test_dashboard_session_cards_endpoint() -> None:
    response = client.get("/dashboard/session/Night/cards")
    assert response.status_code == 200

    payload = response.json()
    assert payload["session"] == "Night"
    assert "stats_header" in payload
    assert "pair_cards" in payload
    assert "combo_cards" in payload
    assert "why_flagged_summary" in payload


# ---------------------------------------------------------------------------
# Autonomy layer endpoints
# ---------------------------------------------------------------------------

def test_stats_session_endpoint() -> None:
    response = client.get("/stats/session/Midday")
    assert response.status_code == 200
    payload = response.json()
    assert payload["session"] == "Midday"
    assert "sums" in payload
    assert "root_sums" in payload
    assert "pairs" in payload
    assert "combinations" in payload


def test_stats_session_unknown_returns_404() -> None:
    response = client.get("/stats/session/Noon")
    assert response.status_code == 404


def test_playlist_session_endpoint() -> None:
    response = client.get("/playlist/session/Evening")
    assert response.status_code == 200
    payload = response.json()
    assert payload["session"] == "Evening"
    assert "shortlist" in payload
    assert len(payload["shortlist"]) > 0


def test_playlist_session_unknown_returns_404() -> None:
    response = client.get("/playlist/session/Unknown")
    assert response.status_code == 404


def test_refresh_run_endpoint() -> None:
    response = client.post(
        "/refresh/run",
        json={"date": "2026-05-10", "session": "Night", "result": "042"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["session"] == "Night"
    assert payload["result"] == "042"
    assert payload["hit_sum"] == 6
    assert payload["total_draws_processed"] == 1


def test_refresh_run_leading_zero_result() -> None:
    response = client.post(
        "/refresh/run",
        json={"date": "2026-05-10", "session": "Midday", "result": "007"},
    )
    assert response.status_code == 200
    assert response.json()["result"] == "007"


def test_refresh_run_bad_session_returns_422() -> None:
    response = client.post(
        "/refresh/run",
        json={"date": "2026-05-10", "session": "Noon", "result": "123"},
    )
    assert response.status_code == 422


def test_refresh_run_missing_result_returns_422() -> None:
    response = client.post(
        "/refresh/run",
        json={"date": "2026-05-10", "session": "Midday"},
    )
    assert response.status_code == 422


def test_refresh_run_increments_on_repeated_calls() -> None:
    client.post("/refresh/run", json={"date": "2026-05-10", "session": "Midday", "result": "123"})
    response = client.post(
        "/refresh/run",
        json={"date": "2026-05-11", "session": "Midday", "result": "456"},
    )
    assert response.json()["total_draws_processed"] == 2
