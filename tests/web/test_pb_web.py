"""Smoke tests for the Play Builder frontend routes (/plays, /plays/session/{session}).

Mocks bluegrass.app.convergence before importing the app so these run
even before the convergence patch is applied to the repo.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Inject convergence mock before anything imports it
# ---------------------------------------------------------------------------

def _make_signal_pools() -> dict:
    return {
        "sums":             [{"value": str(s), "draws_since": 10, "rank": i + 1} for i, s in enumerate(range(14, 24))],
        "root_sums":        [{"value": str(r), "draws_since": 8, "rank": i + 1}  for i, r in enumerate(range(1, 11))],
        "pairs_by_subtype": {
            "front_pair":   [{"value": "12", "draws_since": 5, "rank": 1}],
            "back_pair":    [{"value": "56", "draws_since": 4, "rank": 1}],
            "split_pair":   [{"value": "78", "draws_since": 6, "rank": 1}],
            "front_double": [],
            "back_double":  [],
            "split_double": [],
        },
        "straight_combos":  [{"value": str(100 + i), "draws_since": 20 - i, "rank": i + 1} for i in range(12)],
        "box_combos":       [{"value": str(200 + i), "draws_since": 15 - i, "rank": i + 1} for i in range(10)],
        "singles":          [{"value": "5", "draws_since": 3}],
        "doubles":          [{"value": "11", "draws_since": 2}],
        "triples":          [],
    }


def _make_conv(session: str = "Midday") -> dict:
    pools = _make_signal_pools()
    signals = {
        "sum_match": True, "sum_value": "15", "sum_rank": 1,
        "root_sum_match": True, "root_sum_value": "6",
        "pair_hits": ["front_pair"],
        "straight_match": True, "straight_rank": 2,
        "box_family_match": True, "box_family": "123",
    }
    return {
        "session": session,
        "candidates": [
            {"number": "123", "tier": 1, "score": 8.0, "signals": signals},
            {"number": "456", "tier": 2, "score": 4.0, "signals": {
                "sum_match": False, "sum_value": None, "sum_rank": None,
                "root_sum_match": False, "root_sum_value": None,
                "pair_hits": [], "straight_match": False, "straight_rank": None,
                "box_family_match": False, "box_family": None,
            }},
        ],
        "tier_1_count": 1,
        "tier_2_count": 1,
        "tier_3_count": 0,
        "total_candidates": 2,
        "signal_pools": pools,
        "metadata": {"last_processed_draw": "2026-05-11", "generated_at": "2026-05-11T12:00:00"},
    }


def _make_overview() -> dict:
    return {
        "multi_session_candidates": [{"number": "123", "sessions": ["Midday", "Evening"]}],
        "overview_supported_candidates": [{"number": "456"}],
        "metadata": {"generated_at": "2026-05-11T12:00:00"},
    }


_mock_conv = types.ModuleType("bluegrass.app.convergence")
_mock_conv.build_session_convergence = MagicMock(side_effect=_make_conv)
_mock_conv.build_convergence_overview = MagicMock(return_value=_make_overview())
sys.modules.setdefault("bluegrass.app.convergence", _mock_conv)

# Now safe to import the app
from fastapi.testclient import TestClient  # noqa: E402

from bluegrass.api import app  # noqa: E402
from bluegrass.research.stats_store import reset_stats_state  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    # Patch the names as bound inside play_builder — works regardless of sys.modules ordering
    with patch("bluegrass.app.play_builder.build_session_convergence", side_effect=_make_conv),          patch("bluegrass.app.play_builder.build_convergence_overview", return_value=_make_overview()):
        yield
    reset_stats_state()


# ---------------------------------------------------------------------------
# /plays overview
# ---------------------------------------------------------------------------

def test_pb_overview_returns_200() -> None:
    assert client.get("/plays").status_code == 200


def test_pb_overview_is_html() -> None:
    assert "text/html" in client.get("/plays").headers["content-type"]


def test_pb_overview_has_session_links() -> None:
    body = client.get("/plays").text
    assert "Midday" in body
    assert "Evening" in body
    assert "Night" in body


def test_pb_overview_has_dashboard_heading() -> None:
    body = client.get("/plays").text
    assert "Dashboard" in body or "Play Builder" in body


def test_pb_overview_shows_tier_counts() -> None:
    body = client.get("/plays").text
    assert "T1" in body or "Tier 1" in body


def test_pb_overview_shows_candidate_numbers() -> None:
    body = client.get("/plays").text
    assert "123" in body


def test_pb_overview_multi_session_section() -> None:
    body = client.get("/plays").text
    assert "Multi-Session" in body or "multi" in body.lower()


# ---------------------------------------------------------------------------
# /plays/session/{session}
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_pb_session_returns_200(session: str) -> None:
    assert client.get(f"/plays/session/{session}").status_code == 200


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_pb_session_is_html(session: str) -> None:
    assert "text/html" in client.get(f"/plays/session/{session}").headers["content-type"]


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_pb_session_shows_session_name(session: str) -> None:
    assert session in client.get(f"/plays/session/{session}").text


def test_pb_session_shows_suggested_plays() -> None:
    body = client.get("/plays/session/Midday").text
    assert "Suggested Plays" in body


def test_pb_session_shows_candidate_number() -> None:
    body = client.get("/plays/session/Midday").text
    assert "123" in body


def test_pb_session_rail_has_due_sums() -> None:
    body = client.get("/plays/session/Midday").text
    assert "Due Sums" in body


def test_pb_session_rail_has_due_pairs() -> None:
    body = client.get("/plays/session/Midday").text
    assert "Due Pairs" in body


def test_pb_session_has_straight_plays() -> None:
    body = client.get("/plays/session/Midday").text
    assert "Straight Plays" in body


def test_pb_session_has_box_plays() -> None:
    body = client.get("/plays/session/Midday").text
    assert "Box Plays" in body


def test_pb_session_has_pair_families() -> None:
    body = client.get("/plays/session/Midday").text
    assert "Pair Families" in body


def test_pb_session_has_box_families() -> None:
    body = client.get("/plays/session/Midday").text
    assert "Box Families" in body


def test_pb_session_has_trust_strip() -> None:
    body = client.get("/plays/session/Midday").text
    assert "Freshness" in body or "freshness" in body


# ---------------------------------------------------------------------------
# Invalid session → 404
# ---------------------------------------------------------------------------

def test_pb_invalid_session_returns_404() -> None:
    assert client.get("/plays/session/Weekend").status_code == 404


def test_pb_invalid_session_404_is_html() -> None:
    assert "text/html" in client.get("/plays/session/Weekend").headers["content-type"]
