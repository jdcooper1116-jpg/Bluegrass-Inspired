"""Unit tests for bluegrass.app.ledger_view."""

from __future__ import annotations

import shutil

import pytest

from bluegrass.app.ledger_view import (
    build_ledger_overview,
    build_ledger_session,
    compute_reliability_metrics,
)
from bluegrass.research.ledger import LEDGER_DIR, score_forecast, take_snapshot


@pytest.fixture(autouse=True)
def clean_ledger():
    if LEDGER_DIR.exists():
        shutil.rmtree(LEDGER_DIR)
    yield
    if LEDGER_DIR.exists():
        shutil.rmtree(LEDGER_DIR)


def _vm(session: str = "Midday", tier_1: list[str] | None = None) -> dict:
    def _card(n: str) -> dict:
        return {"number": n, "score": 5.0, "signals": {}}
    return {
        "session": session,
        "plays": {
            "tier_1": [_card(n) for n in (tier_1 or ["123"])],
            "tier_2": [_card("456")],
            "tier_3": [],
        },
        "rail": {
            "due_sums": [{"value": "6", "draws_since": 10}],
            "due_root_sums": [{"value": "6", "draws_since": 8}],
        },
        "pair_families": [
            {"pair": "12", "position": "front", "draws_since": 5},
            {"pair": "23", "position": "back",  "draws_since": 4},
            {"pair": "13", "position": "split", "draws_since": 3},
        ],
    }


# ---------------------------------------------------------------------------
# compute_reliability_metrics — pure function
# ---------------------------------------------------------------------------

def test_metrics_empty_list() -> None:
    m = compute_reliability_metrics([])
    assert m["total_snapshots"]    == 0
    assert m["scored_snapshots"]   == 0
    assert m["unscored_snapshots"] == 0
    assert m["exact_rate"]         == 0.0
    assert m["any_hit_rate"]       == 0.0


def test_metrics_unscored_only() -> None:
    take_snapshot("Midday", _vm(), draw_date="2026-05-10")
    from bluegrass.research.ledger import list_forecasts
    snaps = list_forecasts()
    m = compute_reliability_metrics(snaps)
    assert m["total_snapshots"]    == 1
    assert m["scored_snapshots"]   == 0
    assert m["unscored_snapshots"] == 1
    assert m["any_hit_rate"]       == 0.0


def test_metrics_exact_hit() -> None:
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-10")
    score_forecast("2026-05-10", "Midday", "123")
    from bluegrass.research.ledger import list_forecasts
    m = compute_reliability_metrics(list_forecasts())
    assert m["scored_snapshots"] == 1
    assert m["exact_rate"]       == 1.0
    assert m["any_hit_rate"]     == 1.0


def test_metrics_mixed_hits() -> None:
    # Two scored: one exact hit, one miss
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-10")
    score_forecast("2026-05-10", "Midday", "123")   # exact hit
    take_snapshot("Midday", _vm(tier_1=["999"]), draw_date="2026-05-11")
    score_forecast("2026-05-11", "Midday", "000")   # miss
    from bluegrass.research.ledger import list_forecasts
    m = compute_reliability_metrics(list_forecasts())
    assert m["scored_snapshots"] == 2
    assert m["exact_rate"]  == 0.5
    assert m["any_hit_rate"] >= 0.5  # at least the exact hit counts


def test_metrics_rates_sum_correctly() -> None:
    """exact_rate <= box_rate <= any_hit_rate (exact ⊆ box ⊆ any)."""
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-10")
    score_forecast("2026-05-10", "Midday", "321")  # box hit, not exact
    from bluegrass.research.ledger import list_forecasts
    m = compute_reliability_metrics(list_forecasts())
    assert m["exact_rate"] == 0.0
    assert m["box_rate"]   == 1.0
    assert m["any_hit_rate"] == 1.0


# ---------------------------------------------------------------------------
# build_ledger_overview
# ---------------------------------------------------------------------------

def test_build_ledger_overview_empty_state() -> None:
    vm = build_ledger_overview()
    assert "overall"     in vm
    assert "by_session"  in vm
    assert "recent"      in vm
    assert "generated_at" in vm
    assert vm["overall"]["total_snapshots"] == 0
    assert vm["recent"] == []


def test_build_ledger_overview_has_all_sessions() -> None:
    vm = build_ledger_overview()
    for sess in ("Midday", "Evening", "Night"):
        assert sess in vm["by_session"]


def test_build_ledger_overview_pct_fields() -> None:
    vm = build_ledger_overview()
    o = vm["overall"]
    assert "any_hit_pct"  in o
    assert "exact_pct"    in o
    assert o["any_hit_pct"].endswith("%")


def test_build_ledger_overview_recent_capped() -> None:
    # Write 35 snapshots
    for i in range(35):
        date = f"2026-04-{i+1:02d}" if i < 30 else f"2026-05-{i-29:02d}"
        take_snapshot("Midday", _vm(), draw_date=date)
    vm = build_ledger_overview()
    assert len(vm["recent"]) <= 30


def test_build_ledger_overview_scored_counts() -> None:
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-10")
    score_forecast("2026-05-10", "Midday", "123")
    take_snapshot("Evening", _vm("Evening"), draw_date="2026-05-10")
    vm = build_ledger_overview()
    assert vm["overall"]["total_snapshots"]  == 2
    assert vm["overall"]["scored_snapshots"] == 1


# ---------------------------------------------------------------------------
# build_ledger_session
# ---------------------------------------------------------------------------

def test_build_ledger_session_empty_state() -> None:
    vm = build_ledger_session("Midday")
    assert vm["session"]   == "Midday"
    assert "metrics"       in vm
    assert "forecasts"     in vm
    assert "recent"        in vm
    assert vm["metrics"]["total_snapshots"] == 0
    assert vm["forecasts"] == []


def test_build_ledger_session_invalid_raises() -> None:
    with pytest.raises(ValueError, match="unrecognized session"):
        build_ledger_session("Weekend")


def test_build_ledger_session_filters_by_session() -> None:
    take_snapshot("Midday",  _vm(),           draw_date="2026-05-10")
    take_snapshot("Evening", _vm("Evening"),  draw_date="2026-05-10")
    vm = build_ledger_session("Midday")
    assert vm["metrics"]["total_snapshots"] == 1
    assert all(s["session"] == "Midday" for s in vm["forecasts"])


def test_build_ledger_session_enriched_snap_has_flags() -> None:
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-10")
    score_forecast("2026-05-10", "Midday", "123")
    vm = build_ledger_session("Midday")
    snap = vm["forecasts"][0]
    assert snap["is_scored"]     is True
    assert snap["hit_exact"]     is True
    assert snap["hit_any"]       is True
    assert "tier_1_preview"      in snap


def test_build_ledger_session_unscored_snap_flags_false() -> None:
    take_snapshot("Night", _vm("Night"), draw_date="2026-05-10")
    vm = build_ledger_session("Night")
    snap = vm["forecasts"][0]
    assert snap["is_scored"]  is False
    assert snap["hit_exact"]  is False
    assert snap["hit_any"]    is False
