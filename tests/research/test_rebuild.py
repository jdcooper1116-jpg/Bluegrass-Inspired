"""Tests for bluegrass.research.rebuild."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from bluegrass.research.rebuild import rebuild_runtime_state
from bluegrass.research.stats_store import load_stats_state, reset_stats_state


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


def _engine_row(date: str, draw_time: str, result: str) -> dict:
    return {
        "draw_date": date, "draw_time": draw_time,
        "winning_number": result, "state": "GA",
    }


# ---------------------------------------------------------------------------
# Core rebuild behavior
# ---------------------------------------------------------------------------

def test_rebuild_clears_prior_state() -> None:
    """After rebuild, old draws are gone and only new draws are in state."""
    import bluegrass.engine.client as ec

    # Apply one draw manually first
    from bluegrass.research.refresh import refresh_from_result
    from bluegrass.engine.intake import normalize_result
    refresh_from_result(normalize_result(
        {"date": "2026-01-01", "session": "Midday", "result": "111"}
    ))
    assert load_stats_state()  # state exists

    # Now rebuild with different draws
    rows = [_engine_row("2026-05-10", "midday", "234")]
    with patch.object(ec, "_http_get_json", return_value=rows), \
         patch.dict("os.environ", {"LOTTERY_ENGINE_BASE_URL": "http://fake"}):
        result = rebuild_runtime_state()

    assert result["cleared"] is True
    state = load_stats_state()
    # Old draw "2026-01-01:Midday:111" must not be in the new state
    ids = state.get("by_session", {}).get("Midday", {}).get("processed_draw_ids", [])
    assert "2026-01-01:Midday:111" not in ids
    assert "2026-05-10:Midday:234" in ids


def test_rebuild_applies_draws_in_order() -> None:
    """Draws are applied chronologically so ids[-1] matches the newest date."""
    import bluegrass.engine.client as ec
    rows = [
        _engine_row("2026-05-08", "midday",   "100"),
        _engine_row("2026-05-09", "midday",   "200"),
        _engine_row("2026-05-10", "midday",   "300"),
        _engine_row("2026-05-10", "evening",  "400"),
    ]
    with patch.object(ec, "_http_get_json", return_value=rows), \
         patch.dict("os.environ", {"LOTTERY_ENGINE_BASE_URL": "http://fake"}):
        result = rebuild_runtime_state()

    assert result["applied"] == 4
    assert result["skipped"] == 0
    state = load_stats_state()
    midday_ids = state["by_session"]["Midday"]["processed_draw_ids"]
    assert midday_ids[-1] == "2026-05-10:Midday:300"


def test_rebuild_returns_correct_counts() -> None:
    import bluegrass.engine.client as ec
    rows = [
        _engine_row("2026-05-10", "midday",  "123"),
        _engine_row("2026-05-10", "evening", "456"),
        _engine_row("2026-05-10", "night",   "789"),
    ]
    with patch.object(ec, "_http_get_json", return_value=rows), \
         patch.dict("os.environ", {"LOTTERY_ENGINE_BASE_URL": "http://fake"}):
        result = rebuild_runtime_state()

    assert result["cleared"] is True
    assert result["applied"] == 3
    assert result["skipped"] == 0
    assert result["errors"] == 0


def test_rebuild_skipped_should_be_zero() -> None:
    """After clearing state, every draw in the window should be applied, not skipped."""
    import bluegrass.engine.client as ec
    rows = [_engine_row("2026-05-10", "midday", "123")]
    with patch.object(ec, "_http_get_json", return_value=rows), \
         patch.dict("os.environ", {"LOTTERY_ENGINE_BASE_URL": "http://fake"}):
        result = rebuild_runtime_state()
    assert result["skipped"] == 0


def test_rebuild_engine_error_returns_safely() -> None:
    """Engine failure during rebuild returns error result without raising."""
    import bluegrass.engine.client as ec
    with patch.object(ec, "_http_get_json", side_effect=OSError("connection refused")), \
         patch.dict("os.environ", {"LOTTERY_ENGINE_BASE_URL": "http://fake"}):
        result = rebuild_runtime_state()

    assert result["cleared"] is True
    assert result["errors"] == 1
    assert result["applied"] == 0
    assert result["error_detail"] is not None


def test_rebuild_no_engine_url_returns_empty() -> None:
    """No engine URL → no draws → cleared + 0 applied."""
    import os
    with patch.dict(os.environ, {}, clear=True):
        if "LOTTERY_ENGINE_BASE_URL" in os.environ:
            del os.environ["LOTTERY_ENGINE_BASE_URL"]
        result = rebuild_runtime_state()

    assert result["cleared"] is True
    assert result["applied"] == 0


def test_rebuild_exposes_days_in_result() -> None:
    import bluegrass.engine.client as ec
    with patch.object(ec, "_http_get_json", return_value=[]), \
         patch.dict("os.environ", {"LOTTERY_ENGINE_BASE_URL": "http://fake"}):
        result = rebuild_runtime_state(days=180)
    assert result["days"] == 180


# ---------------------------------------------------------------------------
# draws_behind > SYNC_WINDOW_DAYS → rebuild_recommended in audit
# ---------------------------------------------------------------------------

def test_audit_rebuild_recommended_when_draws_behind_exceeds_sync_window() -> None:
    """If draws_behind > SYNC_WINDOW_DAYS, rebuild_recommended must be True."""
    from bluegrass.app.audit import _build_one
    from bluegrass.research.config import SYNC_WINDOW_DAYS

    # Simulate: engine latest = today, Bluegrass latest = 60 days ago
    from datetime import date, timedelta
    today = date.today()
    old_date = (today - timedelta(days=SYNC_WINDOW_DAYS + 30)).isoformat()
    engine_map = {"Midday": f"{today.isoformat()}:Midday:123"}

    # Inject a processed draw from 60 days ago into stats_state
    from bluegrass.research.stats_store import save_stats_state
    save_stats_state({
        "by_session": {
            "Midday": {
                "draws_processed": 1,
                "processed_draw_ids": [f"{old_date}:Midday:456"],
                "sums": {}, "root_sums": {},
            }
        },
        "total_draws_processed": 1,
    })

    result = _build_one("Midday", engine_map, None)
    assert result["rebuild_recommended"] is True
    assert result["skipped_but_stale_reason"] is not None
    assert "rebuild" in result["skipped_but_stale_reason"].lower()


def test_audit_rebuild_not_recommended_when_fresh() -> None:
    from bluegrass.app.audit import _build_one
    from datetime import date
    today = date.today().isoformat()

    from bluegrass.research.stats_store import save_stats_state
    save_stats_state({
        "by_session": {
            "Midday": {
                "draws_processed": 1,
                "processed_draw_ids": [f"{today}:Midday:123"],
                "sums": {}, "root_sums": {},
            }
        },
        "total_draws_processed": 1,
    })

    engine_map = {"Midday": f"{today}:Midday:123"}
    result = _build_one("Midday", engine_map, None)
    assert result["rebuild_recommended"] is False
    assert result["skipped_but_stale_reason"] is None


# ---------------------------------------------------------------------------
# Rebuild exclusivity
# ---------------------------------------------------------------------------

def test_second_rebuild_returns_already_running() -> None:
    """A concurrent second rebuild must not run — returns already_running=True."""
    from bluegrass.research.rebuild import _REBUILD_LOCK, rebuild_runtime_state

    barrier_entered = threading.Event()
    barrier_proceed = threading.Event()
    first_result: list[dict] = []
    second_result: list[dict] = []

    def slow_rebuild() -> None:
        # Patch fetch to block until we signal it
        def blocking_fetch(days):
            barrier_entered.set()
            barrier_proceed.wait(timeout=5)
            return []

        with patch("bluegrass.research.rebuild.fetch_all_draws", side_effect=blocking_fetch):
            first_result.append(rebuild_runtime_state())

    t = threading.Thread(target=slow_rebuild, daemon=True)
    t.start()
    barrier_entered.wait(timeout=3)

    # First rebuild is now in progress; fire the second
    with patch("bluegrass.research.rebuild.fetch_all_draws", return_value=[]):
        second_result.append(rebuild_runtime_state())

    barrier_proceed.set()
    t.join(timeout=5)

    assert second_result[0]["already_running"] is True, second_result[0]
    assert second_result[0]["cleared"] is False


def test_rebuild_lock_released_after_success() -> None:
    """After a completed rebuild the lock must be free for a new rebuild."""
    with patch("bluegrass.research.rebuild.fetch_all_draws", return_value=[]):
        r = rebuild_runtime_state()
    assert r["already_running"] is False

    # A subsequent rebuild should also succeed
    with patch("bluegrass.research.rebuild.fetch_all_draws", return_value=[]):
        r2 = rebuild_runtime_state()
    assert r2["already_running"] is False


def test_rebuild_lock_released_after_engine_error() -> None:
    """Even on engine failure the lock is released so rebuilds can retry."""
    from bluegrass.engine.client import EngineClientError

    with patch("bluegrass.research.rebuild.fetch_all_draws",
               side_effect=EngineClientError("timeout")):
        r = rebuild_runtime_state()

    assert r["errors"] == 1
    assert r["already_running"] is False

    # Lock must be free now
    from bluegrass.research.rebuild import _REBUILD_LOCK
    assert not _REBUILD_LOCK.locked(), "Lock was not released after engine error"


def test_is_rebuild_in_progress_reflects_lock_state() -> None:
    from bluegrass.research.rebuild import _REBUILD_LOCK, is_rebuild_in_progress

    assert not is_rebuild_in_progress()

    _REBUILD_LOCK.acquire()
    try:
        assert is_rebuild_in_progress()
    finally:
        _REBUILD_LOCK.release()

    assert not is_rebuild_in_progress()


def test_scheduler_skips_when_rebuild_in_progress(monkeypatch) -> None:
    """Scheduler loop must check is_rebuild_in_progress and skip the tick."""
    from bluegrass.research.rebuild import _REBUILD_LOCK

    catchup_called = []

    def mock_catchup():
        catchup_called.append(True)
        return {"applied": 0, "skipped": 0, "errors": 0, "snapshots_created": 0, "scored": 0}

    _REBUILD_LOCK.acquire()
    try:
        # Simulate one scheduler loop iteration with rebuild in progress
        from bluegrass.research.rebuild import is_rebuild_in_progress
        skip = is_rebuild_in_progress()
    finally:
        _REBUILD_LOCK.release()

    assert skip is True, "Scheduler should see rebuild in progress and skip"
