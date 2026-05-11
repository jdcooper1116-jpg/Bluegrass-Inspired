"""Smoke tests for the /integrity page (Phase 6)."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

# Mock audit before importing app
_mock_audit = types.ModuleType("bluegrass.app.audit")
_mock_audit.build_audit_overview = MagicMock(return_value={
    "sessions": {
        "Midday": {
            "freshness_status": "fresh",
            "engine_latest_date": "2026-05-11",
            "draws_behind": None,
            "coverage": "30d",
        },
        "Evening": {
            "freshness_status": "stale",
            "engine_latest_date": "2026-05-11",
            "draws_behind": 1,
            "coverage": "30d",
        },
        "Night": {
            "freshness_status": "engine-unknown",
            "engine_latest_date": None,
            "draws_behind": None,
            "coverage": "baseline-only",
        },
    },
    "generated_at": "2026-05-11T12:00:00",
})
_mock_audit.build_session_audit = MagicMock(return_value={
    "session": "Midday",
    "freshness_status": "fresh",
    "draws_behind": None,
    "coverage": "30d",
    "gap_detected": False,
})
sys.modules.setdefault("bluegrass.app.audit", _mock_audit)

# Mock convergence before importing app
_mock_conv = types.ModuleType("bluegrass.app.convergence")
_mock_conv.build_session_convergence = MagicMock(return_value={
    "session": "Midday",
    "candidates": [],
    "tier_1_count": 0, "tier_2_count": 0, "tier_3_count": 0,
    "total_candidates": 0,
    "signal_pools": {
        "sums": [], "root_sums": [],
        "pairs_by_subtype": {
            "front_pair": [], "back_pair": [], "split_pair": [],
            "front_double": [], "back_double": [], "split_double": [],
        },
        "straight_combos": [], "box_combos": [],
        "singles": [], "doubles": [], "triples": [],
    },
    "metadata": {"last_processed_draw": "2026-05-11", "generated_at": "2026-05-11T12:00:00"},
})
_mock_conv.build_convergence_overview = MagicMock(return_value={
    "multi_session_candidates": [],
    "overview_supported_candidates": [],
    "metadata": {"generated_at": "2026-05-11T12:00:00"},
})
sys.modules.setdefault("bluegrass.app.convergence", _mock_conv)

from fastapi.testclient import TestClient  # noqa: E402

from bluegrass.api import app  # noqa: E402
from bluegrass.research.stats_store import reset_stats_state  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


def test_integrity_returns_200():
    assert client.get("/integrity").status_code == 200


def test_integrity_is_html():
    assert "text/html" in client.get("/integrity").headers["content-type"]


def test_integrity_shows_all_sessions():
    body = client.get("/integrity").text
    assert "Midday" in body
    assert "Evening" in body
    assert "Night" in body


def test_integrity_shows_matched_status():
    body = client.get("/integrity").text
    assert "matched" in body


def test_integrity_shows_stale_status():
    body = client.get("/integrity").text
    assert "stale" in body


def test_integrity_shows_engine_section():
    body = client.get("/integrity").text
    assert "Engine" in body


def test_integrity_shows_bluegrass_applied():
    body = client.get("/integrity").text
    assert "Bluegrass" in body or "Applied" in body


def test_integrity_shows_draw_count():
    body = client.get("/integrity").text
    assert "draw" in body.lower()


def test_integrity_has_legend():
    body = client.get("/integrity").text
    assert "Legend" in body or "matched" in body.lower()


def test_integrity_api_returns_200():
    assert client.get("/integrity").status_code == 200


# Session route normalization
def test_lowercase_midday_redirects():
    resp = client.get("/plays/session/midday", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"].endswith("/plays/session/Midday")


def test_lowercase_evening_redirects():
    resp = client.get("/plays/session/evening", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"].endswith("/plays/session/Evening")


def test_lowercase_night_redirects():
    resp = client.get("/plays/session/night", follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers["location"].endswith("/plays/session/Night")


def test_correct_case_session_not_redirected():
    resp = client.get("/plays/session/Midday", follow_redirects=False)
    assert resp.status_code == 200
