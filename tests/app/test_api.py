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


def test_refresh_run_duplicate_is_skipped() -> None:
    payload = {"date": "2026-05-10", "session": "Midday", "result": "123"}
    client.post("/refresh/run", json=payload)
    response = client.post("/refresh/run", json=payload)
    assert response.status_code == 200
    assert response.json()["skipped"] is True
    assert response.json()["total_draws_processed"] == 1


# ---------------------------------------------------------------------------
# Sync-latest endpoint
# ---------------------------------------------------------------------------

def test_sync_latest_no_url_returns_empty(monkeypatch):
    monkeypatch.delenv("LOTTERY_ENGINE_BASE_URL", raising=False)
    response = client.post("/refresh/sync-latest")
    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] == []
    assert payload["skipped"] == []


def test_sync_latest_processes_new_draws(monkeypatch):
    import bluegrass.engine.client as ec
    raw = [
        {"date": "2026-05-10", "session": "Midday", "result": "123"},
        {"date": "2026-05-10", "session": "Evening", "result": "456"},
    ]
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://fake")
    monkeypatch.setattr(ec, "_http_get_json", lambda url: raw)
    response = client.post("/refresh/sync-latest")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["processed"]) == 2
    assert payload["skipped"] == []


def test_sync_latest_skips_duplicates(monkeypatch):
    import bluegrass.engine.client as ec
    raw = [{"date": "2026-05-10", "session": "Night", "result": "789"}]
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://fake")
    monkeypatch.setattr(ec, "_http_get_json", lambda url: raw)
    client.post("/refresh/sync-latest")
    response = client.post("/refresh/sync-latest")
    payload = response.json()
    assert len(payload["skipped"]) == 1
    assert len(payload["processed"]) == 0


def test_sync_latest_bad_engine_result_goes_to_errors(monkeypatch):
    import bluegrass.engine.client as ec
    raw = [{"date": "2026-05-10", "session": "Noon", "result": "123"}]
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://fake")
    monkeypatch.setattr(ec, "_http_get_json", lambda url: raw)
    response = client.post("/refresh/sync-latest")
    assert response.status_code == 200
    assert len(response.json()["errors"]) == 1


def test_stats_session_includes_metadata() -> None:
    response = client.get("/stats/session/Night")
    assert response.status_code == 200
    payload = response.json()
    assert "metadata" in payload
    assert payload["metadata"]["session"] == "Night"


def test_stats_session_includes_playlist_preview() -> None:
    response = client.get("/stats/session/Midday")
    assert response.status_code == 200
    payload = response.json()
    assert "playlist_preview" in payload
    assert len(payload["playlist_preview"]) > 0
