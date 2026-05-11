"""Tests for bluegrass.app.forecast_orchestrator."""

from __future__ import annotations

import shutil
from unittest.mock import patch

import pytest

from bluegrass.app.forecast_orchestrator import (
    ensure_todays_snapshots,
    run_catchup_with_ledger,
)
from bluegrass.research.ledger import LEDGER_DIR, list_forecasts, load_forecast
from bluegrass.research.stats_store import reset_stats_state


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    if LEDGER_DIR.exists():
        shutil.rmtree(LEDGER_DIR)
    yield
    reset_stats_state()
    if LEDGER_DIR.exists():
        shutil.rmtree(LEDGER_DIR)


# ---------------------------------------------------------------------------
# ensure_todays_snapshots
# ---------------------------------------------------------------------------

def test_ensure_snapshots_creates_for_all_sessions() -> None:
    result = ensure_todays_snapshots(draw_date="2026-05-11")
    assert set(result["created"]) == {"Midday", "Evening", "Night"}
    assert result["skipped"] == []
    assert result["errors"] == []


def test_ensure_snapshots_writes_ledger_files() -> None:
    ensure_todays_snapshots(draw_date="2026-05-11")
    for session in ("Midday", "Evening", "Night"):
        snap = load_forecast("2026-05-11", session)
        assert snap is not None
        assert snap["date"] == "2026-05-11"
        assert snap["session"] == session
        assert snap["result"] is None       # unscored pre-draw


def test_ensure_snapshots_is_idempotent() -> None:
    """Calling twice on the same date creates 3 snapshots, not 6."""
    r1 = ensure_todays_snapshots(draw_date="2026-05-11")
    r2 = ensure_todays_snapshots(draw_date="2026-05-11")
    assert len(r1["created"]) == 3
    assert len(r2["created"]) == 0
    assert len(r2["skipped"]) == 3
    assert len(list_forecasts()) == 3


def test_ensure_snapshots_skips_existing_session() -> None:
    """Only the missing sessions are created; the existing one is skipped."""
    ensure_todays_snapshots(draw_date="2026-05-11", sessions=("Midday",))
    result = ensure_todays_snapshots(draw_date="2026-05-11")
    assert "Midday" in result["skipped"]
    assert "Evening" in result["created"]
    assert "Night"   in result["created"]


def test_ensure_snapshots_isolates_session_errors() -> None:
    """A failure on one session does not prevent the others from being created."""
    def _bad_session(session: str) -> dict:
        if session == "Evening":
            raise RuntimeError("engine down")
        from bluegrass.app.play_builder import build_play_builder_session
        return build_play_builder_session(session)

    with patch("bluegrass.app.forecast_orchestrator.build_play_builder_session",
               side_effect=_bad_session):
        result = ensure_todays_snapshots(draw_date="2026-05-11")

    assert "Evening" in result["errors"]
    assert "Midday"  in result["created"]
    assert "Night"   in result["created"]
    # Only 2 snapshots written
    assert len(list_forecasts()) == 2


def test_ensure_snapshots_snapshot_has_tier1() -> None:
    """Snapshot contains tier_1 list (may be empty in cold state)."""
    ensure_todays_snapshots(draw_date="2026-05-11")
    snap = load_forecast("2026-05-11", "Midday")
    assert "tier_1" in snap
    assert isinstance(snap["tier_1"], list)


# ---------------------------------------------------------------------------
# run_catchup_with_ledger — return shape
# ---------------------------------------------------------------------------

def test_run_catchup_with_ledger_returns_expected_keys() -> None:
    with patch("bluegrass.app.forecast_orchestrator.fetch_all_draws", return_value=[]):
        result = run_catchup_with_ledger()
    assert "applied"            in result
    assert "skipped"            in result
    assert "errors"             in result
    assert "snapshots_created"  in result
    assert "scored"             in result


def test_run_catchup_with_ledger_creates_snapshots_before_applying() -> None:
    """Snapshots are written during the catchup call (idempotent after first call)."""
    with patch("bluegrass.app.forecast_orchestrator.fetch_all_draws", return_value=[]):
        result = run_catchup_with_ledger(days=30)
    assert result["snapshots_created"] == 3
    assert len(list_forecasts()) == 3


def test_run_catchup_with_ledger_scores_applied_draw() -> None:
    """A draw applied in the catchup cycle is scored against its snapshot."""
    # First call: writes snapshots + applies nothing (no rows)
    with patch("bluegrass.app.forecast_orchestrator.fetch_all_draws", return_value=[]):
        run_catchup_with_ledger()

    # Snapshot for 2026-05-11 Midday now exists; supply a matching draw
    rows = [{"date": "2026-05-11", "session": "Midday", "result": "123",
             "state": "GA", "game_type": "pick3"}]
    with patch("bluegrass.app.forecast_orchestrator.fetch_all_draws", return_value=rows):
        result = run_catchup_with_ledger()

    assert result["applied"] == 1
    assert result["scored"]  == 1

    snap = load_forecast("2026-05-11", "Midday")
    assert snap["result"] == "123"
    assert snap["hits"] is not None
    assert "any_hit" in snap["hits"]


def test_run_catchup_with_ledger_no_score_without_snapshot() -> None:
    """Applied draws with no matching snapshot produce scored=0 (no crash)."""
    rows = [{"date": "2020-01-15", "session": "Midday", "result": "456",
             "state": "GA", "game_type": "pick3"}]
    with patch("bluegrass.app.forecast_orchestrator.fetch_all_draws", return_value=rows):
        result = run_catchup_with_ledger()
    # The draw is applied but not scored (no snapshot for 2020-01-15)
    assert result["applied"] == 1
    assert result["scored"]  == 0


def test_run_catchup_with_ledger_skipped_draws_not_scored() -> None:
    """Already-processed draws (skipped) do not increment scored count."""
    rows = [{"date": "2026-05-11", "session": "Midday", "result": "789",
             "state": "GA", "game_type": "pick3"}]
    with patch("bluegrass.app.forecast_orchestrator.fetch_all_draws", return_value=rows):
        run_catchup_with_ledger()   # first pass: applies + potentially scores
        result2 = run_catchup_with_ledger()  # second pass: draw already processed

    assert result2["skipped"] >= 1
    assert result2["scored"]  == 0  # idempotent — same draw skipped, no new scores


def test_run_catchup_with_ledger_engine_error_returns_safely() -> None:
    from bluegrass.engine.client import EngineClientError
    with patch("bluegrass.app.forecast_orchestrator.fetch_all_draws",
               side_effect=EngineClientError("timeout")):
        result = run_catchup_with_ledger()
    assert result["errors"] == 1
    assert result["applied"] == 0
    # snapshots_created still reflects the pre-fetch snapshot step
    assert "snapshots_created" in result
