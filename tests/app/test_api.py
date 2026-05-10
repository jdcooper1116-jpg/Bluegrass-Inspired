from fastapi.testclient import TestClient

from bluegrass.api import app

client = TestClient(app)


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
