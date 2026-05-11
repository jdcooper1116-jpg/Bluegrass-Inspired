"""Smoke tests for the Forecast Ledger frontend routes.

Tests run against the real app with an isolated (empty) ledger dir,
ensuring pages render correctly whether or not forecasts exist on disk.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from bluegrass.api import app
from bluegrass.research.ledger import LEDGER_DIR, score_forecast, take_snapshot
from bluegrass.research.stats_store import reset_stats_state

client = TestClient(app, follow_redirects=True)
no_follow_client = TestClient(app, follow_redirects=False)


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    if LEDGER_DIR.exists():
        shutil.rmtree(LEDGER_DIR)
    yield
    reset_stats_state()
    if LEDGER_DIR.exists():
        shutil.rmtree(LEDGER_DIR)


def _vm(session: str = "Midday", tier_1: list[str] | None = None) -> dict:
    def _card(n: str) -> dict:
        return {"number": n, "score": 5.0, "signals": {}}
    return {
        "session": session,
        "plays": {
            "tier_1": [_card(n) for n in (tier_1 or ["123"])],
            "tier_2": [_card("456")],
            "tier_3": [],
        },
        "rail": {
            "due_sums": [{"value": "6", "draws_since": 10}],
            "due_root_sums": [{"value": "6", "draws_since": 8}],
        },
        "pair_families": [
            {"pair": "12", "position": "front", "draws_since": 5},
        ],
    }


# ---------------------------------------------------------------------------
# /ledger overview — empty state
# ---------------------------------------------------------------------------

def test_ledger_overview_returns_200() -> None:
    assert client.get("/ledger").status_code == 200


def test_ledger_overview_is_html() -> None:
    assert "text/html" in client.get("/ledger").headers["content-type"]


def test_ledger_overview_has_reliability_section() -> None:
    body = client.get("/ledger").text
    assert "reliability" in body.lower() or "Reliability" in body


def test_ledger_overview_shows_session_breakdown() -> None:
    body = client.get("/ledger").text
    assert "Midday"  in body
    assert "Evening" in body
    assert "Night"   in body


def test_ledger_overview_has_nav_link_to_ledger() -> None:
    body = client.get("/ledger").text
    assert "/ledger" in body


def test_ledger_overview_has_auto_refresh_script() -> None:
    body = client.get("/ledger").text
    assert "setTimeout" in body


def test_ledger_overview_has_last_refreshed() -> None:
    body = client.get("/ledger").text
    assert "refresh" in body.lower()


def test_ledger_overview_empty_state_message() -> None:
    body = client.get("/ledger").text
    # Should show 0 total / 0 scored gracefully
    assert "0" in body


# ---------------------------------------------------------------------------
# /ledger/session/{session}
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_ledger_session_returns_200(session: str) -> None:
    assert client.get(f"/ledger/session/{session}").status_code == 200


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_ledger_session_is_html(session: str) -> None:
    assert "text/html" in client.get(f"/ledger/session/{session}").headers["content-type"]


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_ledger_session_shows_session_name(session: str) -> None:
    body = client.get(f"/ledger/session/{session}").text
    assert session in body


def test_ledger_session_invalid_returns_404() -> None:
    assert client.get("/ledger/session/Weekend").status_code == 404


def test_ledger_session_case_redirect() -> None:
    response = no_follow_client.get("/ledger/session/midday")
    assert response.status_code == 301
    assert "Midday" in response.headers["location"]


def test_ledger_session_has_back_link() -> None:
    body = client.get("/ledger/session/Midday").text
    assert "/ledger" in body


# ---------------------------------------------------------------------------
# Pages with actual forecast data
# ---------------------------------------------------------------------------

def test_ledger_overview_shows_scored_forecasts() -> None:
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-10")
    score_forecast("2026-05-10", "Midday", "123")
    body = client.get("/ledger").text
    assert "2026-05-10" in body
    assert "123" in body


def test_ledger_overview_shows_hit_flag_on_exact() -> None:
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-10")
    score_forecast("2026-05-10", "Midday", "123")
    body = client.get("/ledger").text
    # EX flag should appear
    assert "EX" in body


def test_ledger_session_shows_tier1_plays() -> None:
    take_snapshot("Midday", _vm(tier_1=["123", "456"]), draw_date="2026-05-10")
    body = client.get("/ledger/session/Midday").text
    assert "123" in body


def test_ledger_session_unscored_shows_pending() -> None:
    take_snapshot("Evening", _vm("Evening"), draw_date="2026-05-10")
    body = client.get("/ledger/session/Evening").text
    assert "pending" in body or "not scored" in body


def test_ledger_overview_any_hit_rate_displayed() -> None:
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-10")
    score_forecast("2026-05-10", "Midday", "123")
    body = client.get("/ledger").text
    # Any hit rate should show as a percentage
    assert "100%" in body or "Any Hit" in body
