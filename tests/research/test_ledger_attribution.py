"""Tests for the richer attribution fields added to ledger.score_forecast.

Covers:
- _find_tier, _find_box_tier, _compute_verdict (pure helpers)
- result_in_tier, result_box_in_tier, support_channels, verdict in scored hits
- freshness_meta stored in snapshots
- backward compatibility with old snapshots missing new fields
"""

from __future__ import annotations

import shutil

import pytest

from bluegrass.research.ledger import (
    LEDGER_DIR,
    _compute_verdict,
    _find_box_tier,
    _find_tier,
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


def _vm(tier_1=None, tier_2=None, tier_3=None, top_sum="6", top_root="6"):
    def _card(n):
        return {"number": n, "score": 5.0, "signals": {}}
    return {
        "session": "Midday",
        "plays": {
            "tier_1": [_card(n) for n in (tier_1 or ["123"])],
            "tier_2": [_card(n) for n in (tier_2 or ["456"])],
            "tier_3": [_card(n) for n in (tier_3 or [])],
        },
        "rail": {
            "due_sums": [{"value": top_sum, "draws_since": 10}],
            "due_root_sums": [{"value": top_root, "draws_since": 8}],
        },
        "pair_families": [
            {"pair": "12", "position": "front", "draws_since": 5},
            {"pair": "23", "position": "back",  "draws_since": 4},
            {"pair": "13", "position": "split", "draws_since": 3},
        ],
    }


def _snap_with_tiers(t1=None, t2=None, t3=None):
    """Build a minimal snap dict for pure-helper tests."""
    def _make(nums):
        return [{"number": n, "score": 1.0, "signals": {}} for n in (nums or [])]
    return {
        "date": "2026-05-11", "session": "Midday",
        "tier_1": _make(t1), "tier_2": _make(t2), "tier_3": _make(t3),
    }


# ---------------------------------------------------------------------------
# _find_tier — pure helper
# ---------------------------------------------------------------------------

def test_find_tier_exact_in_tier1() -> None:
    snap = _snap_with_tiers(t1=["123", "456"])
    assert _find_tier("123", snap) == 1


def test_find_tier_exact_in_tier2() -> None:
    snap = _snap_with_tiers(t1=["789"], t2=["123"])
    assert _find_tier("123", snap) == 2


def test_find_tier_exact_in_tier3() -> None:
    snap = _snap_with_tiers(t1=["789"], t2=["456"], t3=["123"])
    assert _find_tier("123", snap) == 3


def test_find_tier_not_in_any_tier() -> None:
    snap = _snap_with_tiers(t1=["789"], t2=["456"])
    assert _find_tier("000", snap) is None


def test_find_tier_prefers_lowest_tier() -> None:
    """If result appears in tier 1 and tier 2, tier 1 is returned."""
    snap = _snap_with_tiers(t1=["123"], t2=["123"])
    assert _find_tier("123", snap) == 1


def test_find_tier_empty_tiers() -> None:
    snap = _snap_with_tiers()
    assert _find_tier("123", snap) is None


# ---------------------------------------------------------------------------
# _find_box_tier — pure helper
# ---------------------------------------------------------------------------

def test_find_box_tier_exact_in_tier1() -> None:
    snap = _snap_with_tiers(t1=["123"])
    assert _find_box_tier("321", snap) == 1  # "123" sorted == "321" sorted == "123"


def test_find_box_tier_box_only_in_tier2() -> None:
    snap = _snap_with_tiers(t1=["789"], t2=["123"])
    assert _find_box_tier("321", snap) == 2


def test_find_box_tier_not_present() -> None:
    snap = _snap_with_tiers(t1=["789"])
    assert _find_box_tier("000", snap) is None


def test_find_box_tier_triple_digit() -> None:
    """Triple digits (e.g. 111) — box form is same string."""
    snap = _snap_with_tiers(t1=["111"])
    assert _find_box_tier("111", snap) == 1


# ---------------------------------------------------------------------------
# _compute_verdict — pure helper
# ---------------------------------------------------------------------------

def test_compute_verdict_exact_tier1() -> None:
    assert _compute_verdict(1, None, []) == "Exact hit — Tier 1"


def test_compute_verdict_exact_tier2() -> None:
    assert _compute_verdict(2, 1, []) == "Exact hit — Tier 2"


def test_compute_verdict_box_tier1() -> None:
    assert _compute_verdict(None, 1, []) == "Box hit — Tier 1"


def test_compute_verdict_support_pair_sum() -> None:
    assert _compute_verdict(None, None, ["pair", "sum"]) == "Support hit — pair + sum"


def test_compute_verdict_support_root_only() -> None:
    assert _compute_verdict(None, None, ["root"]) == "Support hit — root"


def test_compute_verdict_miss() -> None:
    assert _compute_verdict(None, None, []) == "Miss"


# ---------------------------------------------------------------------------
# score_forecast — attribution fields in hits dict
# ---------------------------------------------------------------------------

def test_score_stores_result_in_tier_tier1() -> None:
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "123")
    assert hits["result_in_tier"] == 1
    assert hits["verdict"] == "Exact hit — Tier 1"


def test_score_stores_result_in_tier_tier2() -> None:
    take_snapshot("Midday", _vm(tier_1=["789"], tier_2=["123"]), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "123")
    # exact=False (not in tier_1) but result_in_tier=2
    assert hits["exact"] is False
    assert hits["result_in_tier"] == 2
    assert hits["verdict"] == "Exact hit — Tier 2"


def test_score_stores_result_in_tier_none_when_absent() -> None:
    take_snapshot("Midday", _vm(tier_1=["789"]), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "000")
    assert hits["result_in_tier"] is None


def test_score_stores_result_box_in_tier_tier1() -> None:
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "321")
    assert hits["result_box_in_tier"] == 1
    assert hits["verdict"] == "Box hit — Tier 1"


def test_score_stores_result_box_in_tier_tier2() -> None:
    take_snapshot("Midday", _vm(tier_1=["789"], tier_2=["123"]), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "321")
    assert hits["result_box_in_tier"] == 2
    assert hits["verdict"] == "Box hit — Tier 2"


def test_score_stores_support_channels_pair_sum() -> None:
    # sum("129") = 12, not 6 (top_sum). sum("123") = 6, root("123") = 6.
    # front pair of "123" = "12" which matches top front pair
    take_snapshot("Midday", _vm(tier_1=["999"]), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "123")
    # pair_hit: front "12" == top_pairs.front "12" ✓
    # sum_hit: sum("123")=6 == top_sum "6" ✓
    # root_hit: root("123")=6 == top_root "6" ✓
    assert "pair" in hits["support_channels"]
    assert "sum"  in hits["support_channels"]
    assert "root" in hits["support_channels"]
    assert hits["verdict"].startswith("Support hit")


def test_score_verdict_miss_on_complete_miss() -> None:
    take_snapshot("Midday", _vm(tier_1=["789"], top_sum="27", top_root="9"), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "000")
    # 0+0+0=0 ≠ 27, root(000)=0 ≠ 9, front "00" ≠ "12"
    assert hits["verdict"] == "Miss"
    assert hits["support_channels"] == []
    assert hits["result_in_tier"] is None
    assert hits["result_box_in_tier"] is None


def test_score_preserves_original_boolean_flags() -> None:
    """New attribution fields must not remove existing boolean keys."""
    take_snapshot("Midday", _vm(tier_1=["123"]), draw_date="2026-05-11")
    hits = score_forecast("2026-05-11", "Midday", "123")
    for key in ("exact", "box", "pair_hit", "sum_hit", "root_hit", "near_miss", "any_hit"):
        assert key in hits, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# freshness_meta stored in take_snapshot
# ---------------------------------------------------------------------------

def test_freshness_meta_stored_in_snapshot() -> None:
    fm = {
        "snapshot_freshness_status": "fresh",
        "snapshot_source_state_date": "2026-05-10",
        "snapshot_draws_behind": 0,
    }
    take_snapshot("Midday", _vm(), draw_date="2026-05-11", freshness_meta=fm)
    snap = load_forecast("2026-05-11", "Midday")
    assert snap["snapshot_freshness_status"]   == "fresh"
    assert snap["snapshot_source_state_date"]  == "2026-05-10"
    assert snap["snapshot_draws_behind"]       == 0


def test_freshness_meta_defaults_when_absent() -> None:
    take_snapshot("Midday", _vm(), draw_date="2026-05-11")
    snap = load_forecast("2026-05-11", "Midday")
    assert snap["snapshot_freshness_status"] == "unknown"
    assert snap["snapshot_source_state_date"] is None
    assert snap["snapshot_draws_behind"] is None


# ---------------------------------------------------------------------------
# Backward compatibility — old snapshots without new fields
# ---------------------------------------------------------------------------

def test_old_snapshot_no_attribution_scores_gracefully() -> None:
    """A snapshot built by an older version of take_snapshot (no freshness_meta)
    can still be scored without raising KeyError."""
    import json
    # Manually write a minimal old-style snapshot file
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    old_snap = {
        "date": "2026-01-01", "session": "Midday",
        "snapshot_at": "2026-01-01T10:00:00+00:00",
        "tier_1": [{"number": "123", "score": 5.0, "signals": {}}],
        "tier_2": [], "tier_3": [],
        "top_sum": "6", "top_root": "6",
        "top_pairs": {"front": "12", "back": "23", "split": "13"},
        "result": None, "scored_at": None, "hits": None,
    }
    path = LEDGER_DIR / "2026-01-01_Midday.json"
    path.write_text(json.dumps(old_snap))

    hits = score_forecast("2026-01-01", "Midday", "123")
    assert hits["exact"] is True
    assert hits["verdict"] == "Exact hit — Tier 1"
    assert "result_in_tier" in hits
