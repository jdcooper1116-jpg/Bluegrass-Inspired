"""Smoke tests for the operator frontend shell."""

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


# ---------------------------------------------------------------------------
# Overview page
# ---------------------------------------------------------------------------

def test_overview_page_returns_200() -> None:
    response = client.get("/")
    assert response.status_code == 200


def test_overview_page_is_html() -> None:
    response = client.get("/")
    assert "text/html" in response.headers["content-type"]


def test_overview_page_has_nav_links() -> None:
    body = client.get("/").text
    assert "Midday" in body
    assert "Evening" in body
    assert "Night" in body
    assert "Overview" in body


def test_overview_page_shows_generated_at() -> None:
    body = client.get("/").text
    assert "generated" in body.lower() or "Generated" in body


def test_overview_page_has_section_headings() -> None:
    body = client.get("/").text
    assert "Sums" in body
    assert "Pairs" in body
    assert "Combinations" in body


def test_overview_page_has_shortlist() -> None:
    body = client.get("/").text
    assert "shortlist" in body.lower() or "Shortlist" in body


def test_overview_page_has_rationale() -> None:
    body = client.get("/").text
    assert "All draws" in body or "rationale" in body.lower()


# ---------------------------------------------------------------------------
# Session pages
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_page_returns_200(session: str) -> None:
    response = client.get(f"/session/{session}")
    assert response.status_code == 200


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_page_is_html(session: str) -> None:
    response = client.get(f"/session/{session}")
    assert "text/html" in response.headers["content-type"]


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_page_shows_session_name(session: str) -> None:
    body = client.get(f"/session/{session}").text
    assert session in body


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_page_shows_last_processed_draw(session: str) -> None:
    body = client.get(f"/session/{session}").text
    assert "last" in body.lower() or "processed" in body.lower()


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_page_has_section_headings(session: str) -> None:
    body = client.get(f"/session/{session}").text
    assert "Sums" in body
    assert "Pairs" in body


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_page_has_shortlist(session: str) -> None:
    body = client.get(f"/session/{session}").text
    assert "shortlist" in body.lower() or "Shortlist" in body


# ---------------------------------------------------------------------------
# Invalid session → clean 404
# ---------------------------------------------------------------------------

def test_invalid_session_returns_404() -> None:
    response = client.get("/session/Weekend")
    assert response.status_code == 404


def test_invalid_session_404_is_html() -> None:
    response = client.get("/session/Weekend")
    assert "text/html" in response.headers["content-type"]


def test_invalid_session_404_has_message() -> None:
    body = client.get("/session/Weekend").text
    assert "404" in body or "not found" in body.lower() or "invalid" in body.lower()


# ---------------------------------------------------------------------------
# Homepage CTA strip
# ---------------------------------------------------------------------------

def test_homepage_has_play_builder_cta() -> None:
    body = client.get("/").text
    assert "Play Builder" in body


def test_homepage_has_integrity_cta() -> None:
    body = client.get("/").text
    assert "Integrity" in body


def test_homepage_links_to_plays() -> None:
    body = client.get("/").text
    assert "/plays" in body


def test_homepage_links_to_integrity() -> None:
    body = client.get("/").text
    assert "/integrity" in body


def test_homepage_has_session_quick_link_midday() -> None:
    body = client.get("/").text
    assert "/plays/session/Midday" in body


def test_homepage_has_session_quick_link_evening() -> None:
    body = client.get("/").text
    assert "/plays/session/Evening" in body


def test_homepage_has_session_quick_link_night() -> None:
    body = client.get("/").text
    assert "/plays/session/Night" in body
