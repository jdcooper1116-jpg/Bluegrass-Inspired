"""Trust + classification UI smoke tests."""

import pytest
from fastapi.testclient import TestClient

from bluegrass.api import app
from bluegrass.research.stats_store import reset_stats_state

client = TestClient(app, follow_redirects=False)
following_client = TestClient(app, follow_redirects=True)


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


# ---------------------------------------------------------------------------
# Refresh action
# ---------------------------------------------------------------------------

def test_refresh_post_redirects() -> None:
    response = client.post("/refresh?next=/")
    assert response.status_code == 303


def test_refresh_redirects_back_to_root() -> None:
    response = client.post("/refresh?next=/")
    assert response.headers["location"].startswith("/")


def test_refresh_redirects_back_to_session() -> None:
    response = client.post("/refresh?next=/session/Midday")
    loc = response.headers["location"]
    assert "/session/Midday" in loc


def test_refresh_result_shows_on_overview() -> None:
    response = following_client.post("/refresh?next=/")
    assert response.status_code == 200
    body = response.text
    # sync result banner should mention processed/skipped counts
    assert "processed" in body.lower() or "sync" in body.lower()


def test_refresh_result_shows_on_session_page() -> None:
    response = following_client.post("/refresh?next=/session/Night")
    assert response.status_code == 200
    body = response.text
    assert "Night" in body
    assert "processed" in body.lower() or "sync" in body.lower()


def test_refresh_unsafe_next_falls_back_to_root() -> None:
    response = client.post("/refresh?next=https://evil.example.com")
    loc = response.headers["location"]
    assert loc.startswith("/")


# ---------------------------------------------------------------------------
# Overview: freshness strip and refresh form
# ---------------------------------------------------------------------------

def test_overview_has_refresh_form() -> None:
    body = following_client.get("/").text
    assert "<form" in body
    assert "/refresh" in body


def test_overview_has_freshness_strip() -> None:
    body = following_client.get("/").text
    # Freshness strip shows session coverage/status info
    assert "Midday" in body
    assert "Evening" in body
    assert "Night" in body


def test_overview_freshness_strip_shows_coverage() -> None:
    body = following_client.get("/").text
    assert "coverage" in body.lower() or "baseline" in body.lower() or "runtime" in body.lower()


def test_overview_freshness_strip_shows_comparison_status() -> None:
    body = following_client.get("/").text
    # One of the known statuses must appear
    statuses = {"fresh", "stale", "baseline-only", "engine-unknown", "inconclusive", "matched", "gap"}
    assert any(s in body.lower() for s in statuses)


# ---------------------------------------------------------------------------
# Session: audit strip as source of truth
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_has_audit_strip(session: str) -> None:
    body = following_client.get(f"/session/{session}").text
    # Audit strip should show engine/processed draw labels
    assert "engine" in body.lower() or "processed" in body.lower()


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_audit_shows_freshness_status(session: str) -> None:
    body = following_client.get(f"/session/{session}").text
    statuses = {"fresh", "stale", "baseline-only", "engine-unknown", "inconclusive"}
    assert any(s in body.lower() for s in statuses)


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_audit_shows_coverage(session: str) -> None:
    body = following_client.get(f"/session/{session}").text
    assert "coverage" in body.lower() or "baseline" in body.lower() or "runtime" in body.lower()


def test_session_audit_shows_matched_when_fresh(monkeypatch) -> None:
    import bluegrass.app.audit as audit_mod
    from bluegrass.research.refresh import refresh_from_result
    from bluegrass.engine.intake import normalize_result
    monkeypatch.setattr(audit_mod, "fetch_latest_results",
                        lambda: [{"date": "2026-05-10", "session": "Midday",
                                  "result": "123", "state": "GA", "game_type": "pick3"}])
    refresh_from_result(normalize_result(
        {"date": "2026-05-10", "session": "Midday", "result": "123"}
    ))
    body = following_client.get("/session/Midday").text
    assert "fresh" in body.lower() or "matched" in body.lower()


# ---------------------------------------------------------------------------
# Classification chips: combinations get digit_pattern
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_combination_cards_show_digit_pattern_chips(session: str) -> None:
    body = following_client.get(f"/session/{session}").text
    # chip classes for digit pattern must appear somewhere in the combos section
    assert ("chip-single" in body or "chip-double" in body or "chip-triple" in body)


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_combination_cards_show_play_type_chips(session: str) -> None:
    body = following_client.get(f"/session/{session}").text
    assert "chip-straight" in body or "chip-box" in body or "chip-unknown" in body


# ---------------------------------------------------------------------------
# Classification chips: pairs get position chips, not digit_pattern
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_pair_section_shows_position_chips(session: str) -> None:
    body = following_client.get(f"/session/{session}").text
    assert ("chip-front" in body or "chip-back" in body
            or "chip-split" in body or "chip-unknown" in body)


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_pair_section_shows_grouped_positions(session: str) -> None:
    body = following_client.get(f"/session/{session}").text
    # Position group labels should appear
    assert ("Front" in body or "Back" in body or "Split" in body)


# ---------------------------------------------------------------------------
# Overview consensus shortlist classification
# ---------------------------------------------------------------------------

def test_overview_shortlist_shows_classification_chips() -> None:
    body = following_client.get("/").text
    assert ("chip-single" in body or "chip-double" in body or "chip-triple" in body
            or "chip-straight" in body or "chip-box" in body
            or "chip-front" in body or "chip-back" in body)
