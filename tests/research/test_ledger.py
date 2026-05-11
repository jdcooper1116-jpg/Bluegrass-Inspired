"""Acceptance tests for the forecast ledger (Phase 7)."""

from __future__ import annotations

import shutil

import pytest

from bluegrass.research.ledger import (
    LEDGER_DIR,
    list_forecasts,
    load_forecast,
    score_forecast,
    take_snapshot,
)


@pytest.fixture(autouse=True)
def clean_ledger():
    if LEDGER_DIR.exists():
        shutil.rmtree(LEDGER_DIR)
    yield
    if LEDGER_DIR.exists():
        shutil.rmtree(LEDGER_DIR)


def _vm(tier_1: list[str] | None = None, tier_2: list[str] | None = None) -> dict:
    """Minimal view-model for testing."""
    def _card(num: str) -> dict:
        return {"number": num, "score": 5.0, "signals": {}}

    return {
        "session": "Midday",
        "plays": {
            "tier_1": [_card(n) for n in (tier_1 or ["123"])],
            "tier_2": [_card(n) for n in (tier_2 or ["456"])],
            "tier_3": [],
        },
        "rail": {
            "due_sums": [{"value": "6", "draws_since": 10}],
            "due_root_sums": [{"value": "6", "draws_since": 8}],
        },
        "pair_families": [
            {"pair": "12", "position": "front", "draws_since": 5},
            {"pair": "23", "position": "back", "draws_since": 4},
            {"pair": "13", "position": "split", "draws_since": 3},
        ],
    }


# ---------------------------------------------------------------------------
# Snapshot write and load
# ---------------------------------------------------------------------------

def test_snapshot_written():
    result = take_snapshot("Midday", _vm(), draw_date="2026-05-11")
    assert result is True
    snap = load_forecast("2026-05-11", "Midday")
    assert snap is not None
    assert snap["session"] == "Midday"
    assert snap["date"] == "2026-05-11"
    assert snap["result"] is None
    assert snap["scored_at"] is None


def test_snapshot_contains_tier_1_numbers():
    take_snapshot("Midday", _vm(tier_1=["123", "789"]), draw_date="2026-05-11")
    snap = load_forecast("2026-05-11", "Midday")
    nums = [c["number"] for c in snap["tier_1"]]
    assert "123" in nums
    assert "789" in nums


def test_snapshot_is_write_once():
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-11")
    result2 = take_snapshot("Midday", _vm(tier_1=["999"]), draw_date="2026-05-11")
    assert result2 is False
    snap = load_forecast("2026-05-11", "Midday")
    nums = [c["number"] for c in snap["tier_1"]]
    assert "123" in nums   # original preserved
    assert "999" not in nums


def test_load_returns_none_when_missing():
    assert load_forecast("2020-01-01", "Midday") is None


def test_snapshot_stores_all_top_pairs():
    take_snapshot("Midday", _vm(), draw_date="2026-05-11")
    snap = load_forecast("2026-05-11", "Midday")
    assert snap["top_pairs"]["front"] == "12"
    assert snap["top_pairs"]["back"] == "23"
    assert snap["top_pairs"]["split"] == "13"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def test_score_exact_hit():
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "123")
    assert hits["exact"] is True
    assert hits["box"] is True
    assert hits["any_hit"] is True


def test_score_box_hit_not_exact():
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "321")
    assert hits["exact"] is False
    assert hits["box"] is True   # "123" sorted == "321" sorted


def test_score_sum_hit():
    # sum("123") = 6, top_sum from vm = "6"
    take_snapshot("Midday", _vm(), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "123")
    assert hits["sum_hit"] is True


def test_score_root_hit():
    # root_sum("123") = 6, top_root from vm = "6"
    take_snapshot("Midday", _vm(), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "123")
    assert hits["root_hit"] is True


def test_score_pair_hit_front():
    # top front pair = "12", result "129" has front pair "12"
    take_snapshot("Midday", _vm(), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "129")
    assert hits["pair_hit"] is True


def test_score_pair_hit_back():
    # top back pair = "23", result "423" has back pair "23"
    take_snapshot("Midday", _vm(), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "423")
    assert hits["pair_hit"] is True


def test_score_pair_hit_split():
    # top split pair = "13", result "143" has split pair "13"
    take_snapshot("Midday", _vm(), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "143")
    assert hits["pair_hit"] is True


def test_score_miss():
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "999")
    assert hits["exact"] is False
    assert hits["box"] is False
    # sum("999") = 27 ≠ 6
    assert hits["sum_hit"] is False
    assert hits["any_hit"] is False


def test_score_persisted_in_snapshot():
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-11")
    score_forecast("2026-05-11", "Midday", "123")
    snap = load_forecast("2026-05-11", "Midday")
    assert snap["result"] == "123"
    assert snap["scored_at"] is not None
    assert snap["hits"]["exact"] is True


def test_score_idempotent():
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-11")
    hits1 = score_forecast("2026-05-11", "Midday", "123")
    hits2 = score_forecast("2026-05-11", "Midday", "123")
    assert hits1 == hits2


def test_score_returns_empty_when_no_snapshot():
    hits = score_forecast("2020-01-01", "Midday", "123")
    assert hits == {}


# ---------------------------------------------------------------------------
# List forecasts
# ---------------------------------------------------------------------------

def test_list_forecasts_empty():
    assert list_forecasts() == []


def test_list_forecasts_returns_all():
    take_snapshot("Midday", _vm(), draw_date="2026-05-11")
    take_snapshot("Evening", _vm(), draw_date="2026-05-11")
    all_snaps = list_forecasts()
    assert len(all_snaps) == 2


def test_list_forecasts_filtered_by_session():
    take_snapshot("Midday", _vm(), draw_date="2026-05-11")
    take_snapshot("Evening", _vm(), draw_date="2026-05-11")
    mid_snaps = list_forecasts(session="Midday")
    assert len(mid_snaps) == 1
    assert mid_snaps[0]["session"] == "Midday"
