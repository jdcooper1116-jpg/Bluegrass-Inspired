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


def _engine_row(date: str, draw_time: str, result: str) -> dict:
    return {"draw_date": date, "draw_time": draw_time, "winning_number": result, "state": "GA"}


def test_sync_latest_processes_new_draws(monkeypatch):
    import bluegrass.engine.client as ec
    raw = [
        _engine_row("2026-05-10", "midday", "123"),
        _engine_row("2026-05-10", "evening", "456"),
        _engine_row("2026-05-10", "night", "789"),
    ]
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://fake")
    monkeypatch.setattr(ec, "_http_get_json", lambda url: raw)
    response = client.post("/refresh/sync-latest")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["processed"]) == 3
    assert payload["skipped"] == []
    assert payload["errors"] == []


def test_sync_latest_skips_duplicates(monkeypatch):
    import bluegrass.engine.client as ec
    raw = [_engine_row("2026-05-10", "night", "789")]
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://fake")
    monkeypatch.setattr(ec, "_http_get_json", lambda url: raw)
    client.post("/refresh/sync-latest")
    response = client.post("/refresh/sync-latest")
    payload = response.json()
    assert len(payload["skipped"]) == 1
    assert len(payload["processed"]) == 0


def test_sync_latest_engine_error_goes_to_errors(monkeypatch):
    import bluegrass.engine.client as ec
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://fake")
    monkeypatch.setattr(ec, "_http_get_json",
                        lambda url: (_ for _ in ()).throw(OSError("connection refused")))
    response = client.post("/refresh/sync-latest")
    assert response.status_code == 200
    payload = response.json()
    assert payload["error_count"] == 1
    assert "connection refused" in payload["errors"][0]["error"]


# ---------------------------------------------------------------------------
# Daily board endpoint
# ---------------------------------------------------------------------------

def test_board_session_endpoint() -> None:
    response = client.get("/board/session/Midday")
    assert response.status_code == 200
    payload = response.json()
    assert payload["session"] == "Midday"
    assert "top_sums" in payload
    assert "top_root_sums" in payload
    assert "top_pairs" in payload
    assert "top_combinations" in payload
    assert "shortlist" in payload
    assert "rationale" in payload
    assert "metadata" in payload


def test_board_overview_endpoint() -> None:
    response = client.get("/board/overview")
    assert response.status_code == 200
    payload = response.json()
    assert "top_sums" in payload
    assert "consensus_shortlist" in payload
    assert "session_overlap" in payload
    assert "metadata" in payload
    assert set(payload["metadata"]["sessions"]) == {"Midday", "Evening", "Night"}


def test_board_session_rejects_invalid() -> None:
    response = client.get("/board/session/Weekend")
    assert response.status_code == 404


def test_board_session_metadata_shape() -> None:
    response = client.get("/board/session/Night")
    assert response.status_code == 200
    meta = response.json()["metadata"]
    assert meta["session"] == "Night"
    assert "generated_at" in meta
    assert "last_processed_draw" in meta


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


# ---------------------------------------------------------------------------
# Audit endpoints
# ---------------------------------------------------------------------------

def test_audit_session_endpoint() -> None:
    response = client.get("/audit/session/Night")
    assert response.status_code == 200
    payload = response.json()
    assert payload["session"] == "Night"
    assert "comparison_status" in payload
    assert "gap_detected" in payload
    assert "freshness_status" in payload
    assert "engine_latest_draw" in payload
    assert "bluegrass_last_processed_draw" in payload


def test_audit_session_invalid_returns_404() -> None:
    response = client.get("/audit/session/Weekend")
    assert response.status_code == 404


def test_audit_overview_endpoint() -> None:
    response = client.get("/audit/overview")
    assert response.status_code == 200
    payload = response.json()
    assert "sessions" in payload
    assert "overall_status" in payload
    assert set(payload["sessions"].keys()) == {"Midday", "Evening", "Night"}
