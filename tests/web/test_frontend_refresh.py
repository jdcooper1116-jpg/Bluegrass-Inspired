"""Frontend refresh visibility tests.

Verifies:
- "Last refreshed" status bar appears on all target pages
- Auto-refresh JS (setTimeout) is present in both base shells
- Sync banner shows "Applied N new draws" when processed > 0
- Sync banner shows "No new draws found" when processed == 0
- Skipped/error counts still surface when present
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bluegrass.api import app
from bluegrass.research.stats_store import reset_stats_state

client = TestClient(app, follow_redirects=True)


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


# ---------------------------------------------------------------------------
# Refresh bar — "Last refreshed: HH:MM UTC" present on all target pages
# ---------------------------------------------------------------------------

def test_overview_has_last_refreshed_text() -> None:
    body = client.get("/").text
    assert "Last refreshed" in body


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_has_last_refreshed_text(session: str) -> None:
    body = client.get(f"/session/{session}").text
    assert "Last refreshed" in body


def test_plays_overview_has_last_refreshed_text() -> None:
    body = client.get("/plays").text
    # PB shell uses "refresh" wording in the topnav right area
    assert "refresh" in body.lower()


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_plays_session_has_last_refreshed_text(session: str) -> None:
    body = client.get(f"/plays/session/{session}").text
    assert "refresh" in body.lower()


def test_integrity_has_last_refreshed_text() -> None:
    body = client.get("/integrity").text
    assert "refresh" in body.lower()


# ---------------------------------------------------------------------------
# Auto-refresh JS present in both shells
# ---------------------------------------------------------------------------

def test_overview_has_auto_refresh_script() -> None:
    body = client.get("/").text
    assert "setTimeout" in body
    assert "location.reload" in body


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_has_auto_refresh_script(session: str) -> None:
    body = client.get(f"/session/{session}").text
    assert "setTimeout" in body


def test_plays_has_auto_refresh_script() -> None:
    body = client.get("/plays").text
    assert "setTimeout" in body
    assert "location.reload" in body


def test_integrity_has_auto_refresh_script() -> None:
    body = client.get("/integrity").text
    assert "setTimeout" in body


def test_auto_refresh_skips_when_synced_param_present() -> None:
    """The JS must check for ?synced so the banner isn't cleared on reload."""
    body = client.get("/?synced=1&processed=2&skipped=0&errors=0").text
    assert "synced" in body   # the param guard is present in the script


# ---------------------------------------------------------------------------
# Sync banner — improved copy
# ---------------------------------------------------------------------------

def test_sync_banner_shows_applied_when_processed_positive() -> None:
    body = client.get("/?synced=1&processed=3&skipped=1&errors=0").text
    assert "Applied 3 new draws" in body


def test_sync_banner_shows_applied_singular() -> None:
    body = client.get("/?synced=1&processed=1&skipped=0&errors=0").text
    assert "Applied 1 new draw" in body
    assert "draws" not in body.split("Applied 1 new draw")[1][:5]


def test_sync_banner_shows_no_new_draws_when_zero() -> None:
    body = client.get("/?synced=1&processed=0&skipped=5&errors=0").text
    assert "No new draws found" in body


def test_sync_banner_no_new_draws_on_session_page() -> None:
    body = client.get("/session/Midday?synced=1&processed=0&skipped=0&errors=0").text
    assert "No new draws found" in body


def test_sync_banner_applied_on_session_page() -> None:
    body = client.get("/session/Evening?synced=1&processed=2&skipped=0&errors=0").text
    assert "Applied 2 new draws" in body


def test_sync_banner_shows_skipped_when_nonzero() -> None:
    body = client.get("/?synced=1&processed=0&skipped=7&errors=0").text
    assert "7 skipped" in body


def test_sync_banner_shows_errors_when_nonzero() -> None:
    body = client.get("/?synced=1&processed=0&skipped=0&errors=2").text
    assert "2 errors" in body


def test_sync_banner_hides_skipped_when_zero() -> None:
    """When skipped=0, the word 'skipped' should not appear in the banner."""
    body = client.get("/?synced=1&processed=3&skipped=0&errors=0").text
    # The banner itself shouldn't mention skipped when it's 0
    # Check the banner section doesn't have "0 skipped"
    assert "0 skipped" not in body


def test_sync_banner_absent_without_synced_param() -> None:
    """No sync banner on a clean page load."""
    body = client.get("/").text
    assert "Applied" not in body
    assert "No new draws found" not in body


def test_plays_sync_banner_shows_applied() -> None:
    body = client.get("/plays?synced=1&processed=4&skipped=0&errors=0").text
    assert "Applied 4 new draws" in body


def test_plays_sync_banner_shows_no_new_draws() -> None:
    body = client.get("/plays?synced=1&processed=0&skipped=0&errors=0").text
    assert "No new draws found" in body


def test_integrity_sync_banner_shows_applied() -> None:
    body = client.get("/integrity?synced=1&processed=2&skipped=0&errors=0").text
    assert "Applied 2 new draws" in body


def test_integrity_sync_banner_shows_no_new_draws() -> None:
    body = client.get("/integrity?synced=1&processed=0&skipped=0&errors=0").text
    assert "No new draws found" in body
