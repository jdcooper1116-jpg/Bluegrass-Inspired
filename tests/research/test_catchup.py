"""Acceptance tests for catch-up sync (Phase 4).

Tests the catchup.run_catchup() function using a mocked engine client.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from bluegrass.research.stats_store import load_stats_state, reset_stats_state


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


def _make_rows(*draws: tuple[str, str, str]) -> list[dict]:
    """Build raw engine rows: (date, session, result)."""
    return [
        {"date": d, "session": s, "result": r,
         "state": "GA", "game_type": "pick3"}
        for d, s, r in draws
    ]


# ---------------------------------------------------------------------------
# Catch-up applies draws in order
# ---------------------------------------------------------------------------

def test_catchup_applies_draws(monkeypatch):
    rows = _make_rows(
        ("2026-05-09", "Midday", "123"),
        ("2026-05-10", "Midday", "456"),
        ("2026-05-11", "Evening", "789"),
    )
    with patch("bluegrass.research.catchup.fetch_all_draws", return_value=rows):
        from bluegrass.research.catchup import run_catchup
        result = run_catchup()

    assert result["applied"] == 3
    assert result["skipped"] == 0
    assert result["errors"] == 0


def test_catchup_result_reflected_in_state(monkeypatch):
    rows = _make_rows(("2026-05-11", "Midday", "347"))
    with patch("bluegrass.research.catchup.fetch_all_draws", return_value=rows):
        from bluegrass.research.catchup import run_catchup
        run_catchup()

    state = load_stats_state()["by_session"]["Midday"]
    assert state["sums"]["14"]["draws_since"] == 0
    assert state["pairs"]["front"]["34"]["draws_since"] == 0
    assert state["box_families"]["347"]["draws_since"] == 0


# ---------------------------------------------------------------------------
# Idempotency: same draw twice does not corrupt counts
# ---------------------------------------------------------------------------

def test_catchup_idempotent(monkeypatch):
    rows = _make_rows(
        ("2026-05-11", "Midday", "123"),
        ("2026-05-12", "Evening", "456"),
    )
    with patch("bluegrass.research.catchup.fetch_all_draws", return_value=rows):
        from bluegrass.research.catchup import run_catchup
        run_catchup()
        result2 = run_catchup()

    assert result2["applied"] == 0
    assert result2["skipped"] == 2

    state = load_stats_state()
    assert state["by_session"]["Midday"]["draws_processed"] == 1
    assert state["by_session"]["Evening"]["draws_processed"] == 1


def test_catchup_does_not_double_count_sums(monkeypatch):
    rows = _make_rows(("2026-05-11", "Midday", "123"))
    with patch("bluegrass.research.catchup.fetch_all_draws", return_value=rows):
        from bluegrass.research.catchup import run_catchup
        run_catchup()
        run_catchup()

    sums = load_stats_state()["by_session"]["Midday"]["sums"]
    assert sums["6"]["times_seen_runtime"] == 1


# ---------------------------------------------------------------------------
# Partial overlap: already-applied draws are skipped, new ones applied
# ---------------------------------------------------------------------------

def test_catchup_partial_overlap(monkeypatch):
    from bluegrass.engine.intake import EngineResult
    from bluegrass.research.refresh import refresh_from_result

    # Pre-apply first draw manually
    refresh_from_result(EngineResult(
        date="2026-05-10", session="Midday", result="111",
        jurisdiction="GA", game_family="Pick 3",
    ))

    rows = _make_rows(
        ("2026-05-10", "Midday", "111"),   # already applied
        ("2026-05-11", "Midday", "222"),   # new
        ("2026-05-12", "Midday", "333"),   # new
    )
    with patch("bluegrass.research.catchup.fetch_all_draws", return_value=rows):
        from bluegrass.research.catchup import run_catchup
        result = run_catchup()

    assert result["applied"] == 2
    assert result["skipped"] == 1
    state = load_stats_state()["by_session"]["Midday"]
    assert state["draws_processed"] == 3


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_catchup_handles_engine_error(monkeypatch):
    from bluegrass.engine.client import EngineClientError
    with patch("bluegrass.research.catchup.fetch_all_draws",
               side_effect=EngineClientError("timeout")):
        from bluegrass.research.catchup import run_catchup
        result = run_catchup()

    assert result["applied"] == 0
    assert result["errors"] == 1
    assert "timeout" in result.get("error_detail", "")


def test_catchup_skips_invalid_rows(monkeypatch):
    rows = [
        {"date": "2026-05-11", "session": "Midday", "result": "123",
         "state": "GA", "game_type": "pick3"},
        {"date": "", "session": "badval", "result": ""},  # invalid
    ]
    with patch("bluegrass.research.catchup.fetch_all_draws", return_value=rows):
        from bluegrass.research.catchup import run_catchup
        result = run_catchup()

    assert result["applied"] == 1
    assert result["errors"] == 1


def test_catchup_returns_zero_when_no_engine(monkeypatch):
    with patch("bluegrass.research.catchup.fetch_all_draws", return_value=[]):
        from bluegrass.research.catchup import run_catchup
        result = run_catchup()

    assert result["applied"] == 0
    assert result["skipped"] == 0
    assert result["errors"] == 0


# ---------------------------------------------------------------------------
# Window separation — sync vs analysis bootstrap
# ---------------------------------------------------------------------------

def test_run_catchup_default_uses_sync_window():
    """run_catchup() with no args must fetch SYNC_WINDOW_DAYS (30) days."""
    from bluegrass.research.config import SYNC_WINDOW_DAYS
    captured = []
    with patch("bluegrass.research.catchup.fetch_all_draws",
               side_effect=lambda days: captured.append(days) or []):
        from bluegrass.research.catchup import run_catchup
        run_catchup()
    assert captured == [SYNC_WINDOW_DAYS]


def test_run_analysis_bootstrap_uses_analysis_window():
    """run_analysis_bootstrap() with no args must fetch ANALYSIS_WINDOW_DAYS (250) days."""
    from bluegrass.research.config import ANALYSIS_WINDOW_DAYS
    captured = []
    with patch("bluegrass.research.catchup.fetch_all_draws",
               side_effect=lambda days: captured.append(days) or []):
        from bluegrass.research.catchup import run_analysis_bootstrap
        run_analysis_bootstrap()
    assert captured == [ANALYSIS_WINDOW_DAYS]


def test_run_analysis_bootstrap_is_idempotent():
    """Running analysis bootstrap twice applies draws once, skips on second call."""
    rows = [{"date": "2026-05-11", "session": "Midday", "result": "123",
             "state": "GA", "game_type": "pick3"}]
    with patch("bluegrass.research.catchup.fetch_all_draws", return_value=rows):
        from bluegrass.research.catchup import run_analysis_bootstrap
        r1 = run_analysis_bootstrap()
        r2 = run_analysis_bootstrap()
    assert r1["applied"] == 1
    assert r2["applied"] == 0
    assert r2["skipped"] == 1


def test_run_analysis_bootstrap_accepts_custom_days():
    """run_analysis_bootstrap(days=180) must fetch exactly 180 days."""
    captured = []
    with patch("bluegrass.research.catchup.fetch_all_draws",
               side_effect=lambda days: captured.append(days) or []):
        from bluegrass.research.catchup import run_analysis_bootstrap
        run_analysis_bootstrap(days=180)
    assert captured == [180]
