"""Smoke tests for convergence frontend routes."""

import pytest
from fastapi.testclient import TestClient

from bluegrass.api import app
from bluegrass.research.stats_store import reset_stats_state

client = TestClient(app)

_SESSIONS = ("Midday", "Evening", "Night")


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


# ---------------------------------------------------------------------------
# /convergence/overview
# ---------------------------------------------------------------------------

def test_convergence_overview_returns_200():
    assert client.get("/convergence/overview").status_code == 200


def test_convergence_overview_is_html():
    assert "text/html" in client.get("/convergence/overview").headers["content-type"]


def test_convergence_overview_has_bucket_headers():
    body = client.get("/convergence/overview").text
    assert "Multi-Session" in body
    assert "Overview Supported" in body


def test_convergence_overview_has_session_summaries():
    body = client.get("/convergence/overview").text
    for sess in _SESSIONS:
        assert sess in body


def test_convergence_overview_nav_links_present():
    body = client.get("/convergence/overview").text
    assert "Convergence" in body
    assert "Conv" in body


# ---------------------------------------------------------------------------
# /convergence/session/{session}
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", _SESSIONS)
def test_convergence_session_returns_200(session):
    assert client.get(f"/convergence/session/{session}").status_code == 200


@pytest.mark.parametrize("session", _SESSIONS)
def test_convergence_session_is_html(session):
    assert "text/html" in client.get(f"/convergence/session/{session}").headers["content-type"]


@pytest.mark.parametrize("session", _SESSIONS)
def test_convergence_session_shows_session_name(session):
    assert session in client.get(f"/convergence/session/{session}").text


@pytest.mark.parametrize("session", _SESSIONS)
def test_convergence_session_has_tier_labels(session):
    body = client.get(f"/convergence/session/{session}").text
    assert "T1" in body
    assert "T2" in body
    assert "T3" in body


@pytest.mark.parametrize("session", _SESSIONS)
def test_convergence_session_has_signal_pools(session):
    assert "Signal Pools" in client.get(f"/convergence/session/{session}").text


@pytest.mark.parametrize("session", _SESSIONS)
def test_convergence_session_has_trust_banner(session):
    body = client.get(f"/convergence/session/{session}").text
    assert "Engine:" in body
    assert "Processed:" in body


def test_convergence_invalid_session_returns_404():
    assert client.get("/convergence/session/Weekend").status_code == 404
