"""Integration tests — sync window vs analysis window separation.

Verifies that:
- The two constants are distinct and correctly ordered
- Startup uses the analysis window (250d), scheduler uses the sync window (30d)
- Board / stats / overview metadata surfaces both window values
- The analysis bootstrap is idempotent and independent of the sync catchup
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bluegrass.research.config import ANALYSIS_WINDOW_DAYS, SYNC_WINDOW_DAYS
from bluegrass.research.stats_store import reset_stats_state


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_windows_are_distinct() -> None:
    assert SYNC_WINDOW_DAYS != ANALYSIS_WINDOW_DAYS


def test_analysis_window_larger_than_sync() -> None:
    assert ANALYSIS_WINDOW_DAYS > SYNC_WINDOW_DAYS


# ---------------------------------------------------------------------------
# Bootstrap vs sync fetch sizes
# ---------------------------------------------------------------------------

def test_catchup_fetches_sync_window() -> None:
    captured: list[int] = []
    with patch("bluegrass.research.catchup.fetch_all_draws",
               side_effect=lambda d: captured.append(d) or []):
        from bluegrass.research.catchup import run_catchup
        run_catchup()
    assert captured == [SYNC_WINDOW_DAYS]


def test_bootstrap_fetches_analysis_window() -> None:
    captured: list[int] = []
    with patch("bluegrass.research.catchup.fetch_all_draws",
               side_effect=lambda d: captured.append(d) or []):
        from bluegrass.research.catchup import run_analysis_bootstrap
        run_analysis_bootstrap()
    assert captured == [ANALYSIS_WINDOW_DAYS]


def test_bootstrap_does_not_double_count_with_prior_catchup() -> None:
    """Draws applied via run_catchup are skipped cleanly by run_analysis_bootstrap."""
    rows = [{"date": "2026-05-11", "session": "Midday", "result": "456",
             "state": "GA", "game_type": "pick3"}]
    with patch("bluegrass.research.catchup.fetch_all_draws", return_value=rows):
        from bluegrass.research.catchup import run_analysis_bootstrap, run_catchup
        catchup_result = run_catchup()
        bootstrap_result = run_analysis_bootstrap()

    assert catchup_result["applied"] == 1
    assert bootstrap_result["applied"] == 0
    assert bootstrap_result["skipped"] == 1


# ---------------------------------------------------------------------------
# Metadata surfaces both windows
# ---------------------------------------------------------------------------

def test_board_metadata_has_analysis_window() -> None:
    from bluegrass.app.board import build_session_board
    meta = build_session_board("Midday")["metadata"]
    assert meta["analysis_window_days"] == ANALYSIS_WINDOW_DAYS


def test_board_metadata_has_sync_window() -> None:
    from bluegrass.app.board import build_session_board
    meta = build_session_board("Midday")["metadata"]
    assert meta["sync_window_days"] == SYNC_WINDOW_DAYS


def test_stats_metadata_has_analysis_window() -> None:
    from bluegrass.app.playlist import build_session_stats
    meta = build_session_stats("Evening")["metadata"]
    assert meta["analysis_window_days"] == ANALYSIS_WINDOW_DAYS


def test_stats_metadata_has_sync_window() -> None:
    from bluegrass.app.playlist import build_session_stats
    meta = build_session_stats("Evening")["metadata"]
    assert meta["sync_window_days"] == SYNC_WINDOW_DAYS


def test_overview_metadata_has_analysis_window() -> None:
    from bluegrass.app.overview import build_all_draws_overview
    meta = build_all_draws_overview()["metadata"]
    assert meta["analysis_window_days"] == ANALYSIS_WINDOW_DAYS


def test_overview_metadata_has_sync_window() -> None:
    from bluegrass.app.overview import build_all_draws_overview
    meta = build_all_draws_overview()["metadata"]
    assert meta["sync_window_days"] == SYNC_WINDOW_DAYS


def test_board_source_is_engine_runtime() -> None:
    from bluegrass.app.board import build_session_board
    meta = build_session_board("Night")["metadata"]
    assert meta["source"] == "engine-runtime"


def test_overview_source_is_engine_runtime() -> None:
    from bluegrass.app.overview import build_all_draws_overview
    meta = build_all_draws_overview()["metadata"]
    assert meta["source"] == "engine-runtime"
