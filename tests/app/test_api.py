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
