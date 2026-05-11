"""Tests for the Play Builder view-model adapter.

Mocks bluegrass.app.convergence (from the unapplied patch) so these tests
run against the adapter logic independently.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Minimal convergence fixture data
# ---------------------------------------------------------------------------

def _make_signal_pools(**overrides: Any) -> dict[str, Any]:
    pools: dict[str, Any] = {
        "sums": [{"value": str(s), "draws_since": 10 - i, "rank": i + 1} for i, s in enumerate(range(14, 24))],
        "root_sums": [{"value": str(r), "draws_since": 8 - i, "rank": i + 1} for i, r in enumerate(range(1, 11))],
        "pairs_by_subtype": {
            "front_straight": [{"value": "12", "draws_since": 5, "rank": 1}, {"value": "34", "draws_since": 3, "rank": 2}],
            "front_box": [],
            "back_straight":  [{"value": "56", "draws_since": 4, "rank": 1}],
            "back_box": [],
            "split_straight": [{"value": "78", "draws_since": 6, "rank": 1}],
            "split_box": [],
        },
        "straight_combos": [{"value": str(100 + i), "draws_since": 20 - i, "rank": i + 1} for i in range(12)],
        "box_combos":      [{"value": str(200 + i), "draws_since": 15 - i, "rank": i + 1} for i in range(10)],
        "singles":  [{"value": "5", "draws_since": 3}],
        "doubles":  [{"value": "11", "draws_since": 2}],
        "triples":  [{"value": "222", "draws_since": 7}],
    }
    pools.update(overrides)
    return pools


def _make_candidate(number: str, tier: int, **sig_overrides: Any) -> dict[str, Any]:
    signals: dict[str, Any] = {
        "sum_match": False, "sum_value": None, "sum_rank": None,
        "root_sum_match": False, "root_sum_value": None,
        "pair_hits": [],
        "straight_match": False, "straight_rank": None,
        "box_family_match": False, "box_family": None,
    }
    signals.update(sig_overrides)
    return {"number": number, "tier": tier, "score": float(tier * 2), "signals": signals}


def _make_convergence_response(session: str = "Midday") -> dict[str, Any]:
    pools = _make_signal_pools()
    candidates = [
        _make_candidate("123", 1, sum_match=True, sum_value="6", sum_rank=1,
                        root_sum_match=True, root_sum_value="6",
                        straight_match=True, straight_rank=3,
                        box_family_match=True, box_family="123"),
        _make_candidate("456", 1, pair_hits=["front_pair", "back_pair"]),
        _make_candidate("789", 2, sum_match=True, sum_value="24", sum_rank=5),
        _make_candidate("001", 3),
    ]
    return {
        "session": session,
        "candidates": candidates,
        "tier_1_count": 2,
        "tier_2_count": 1,
        "tier_3_count": 1,
        "total_candidates": 4,
        "signal_pools": pools,
        "metadata": {"last_processed_draw": "2026-05-11", "generated_at": "2026-05-11T12:00:00"},
    }


def _make_overview_response() -> dict[str, Any]:
    return {
        "multi_session_candidates": [{"number": "123", "sessions": ["Midday", "Evening"]}],
        "overview_supported_candidates": [{"number": "456"}],
        "metadata": {"generated_at": "2026-05-11T12:00:00"},
    }


# ---------------------------------------------------------------------------
# Inject mock convergence module before importing play_builder
# ---------------------------------------------------------------------------

_mock_conv_mod = types.ModuleType("bluegrass.app.convergence")
_mock_conv_mod.build_session_convergence = MagicMock(side_effect=_make_convergence_response)
_mock_conv_mod.build_convergence_overview = MagicMock(return_value=_make_overview_response())
sys.modules.setdefault("bluegrass.app.convergence", _mock_conv_mod)

# Now safe to import
from bluegrass.app.play_builder import (  # noqa: E402
    _box_families,
    _enrich_play_card,
    _pair_families,
    build_play_builder_overview,
    build_play_builder_session,
)
from bluegrass.research.stats_store import reset_stats_state  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    _mock_conv_mod.build_session_convergence.side_effect = _make_convergence_response
    _mock_conv_mod.build_convergence_overview.return_value = _make_overview_response()
    yield
    reset_stats_state()


# ---------------------------------------------------------------------------
# _enrich_play_card
# ---------------------------------------------------------------------------

class TestEnrichPlayCard:
    def test_tier1_confidence_label(self) -> None:
        c = _make_candidate("123", 1)
        out = _enrich_play_card(c)
        assert out["confidence_label"] == "Highest Convergence"
        assert out["confidence_desc"] == "Strongest Signals"

    def test_tier2_confidence_label(self) -> None:
        c = _make_candidate("456", 2)
        out = _enrich_play_card(c)
        assert out["confidence_label"] == "Strong Signals"
        assert out["confidence_desc"] == "Multiple Matches"

    def test_tier3_confidence_label(self) -> None:
        c = _make_candidate("789", 3)
        out = _enrich_play_card(c)
        assert out["confidence_label"] == "Moderate Signals"
        assert out["confidence_desc"] == "Value Plays"

    def test_play_type_straight_only(self) -> None:
        c = _make_candidate("100", 1, straight_match=True)
        assert _enrich_play_card(c)["play_type"] == "straight"

    def test_play_type_box_only(self) -> None:
        c = _make_candidate("100", 1, box_family_match=True)
        assert _enrich_play_card(c)["play_type"] == "box"

    def test_play_type_both(self) -> None:
        c = _make_candidate("100", 1, straight_match=True, box_family_match=True)
        assert _enrich_play_card(c)["play_type"] == "both"

    def test_play_type_any_when_no_match(self) -> None:
        c = _make_candidate("100", 1)
        assert _enrich_play_card(c)["play_type"] == "any"

    def test_human_rationale_sum(self) -> None:
        c = _make_candidate("100", 1, sum_match=True, sum_value="7", sum_rank=2)
        rationale = _enrich_play_card(c)["human_rationale"]
        assert "Sum 7" in rationale
        assert "#2" in rationale

    def test_human_rationale_root_sum(self) -> None:
        c = _make_candidate("100", 1, root_sum_match=True, root_sum_value="4")
        rationale = _enrich_play_card(c)["human_rationale"]
        assert "Root 4" in rationale

    def test_human_rationale_pair_hits(self) -> None:
        c = _make_candidate("100", 1, pair_hits=["front_pair", "back_pair"])
        rationale = _enrich_play_card(c)["human_rationale"]
        assert "Front Pair" in rationale

    def test_human_rationale_straight(self) -> None:
        c = _make_candidate("100", 1, straight_match=True, straight_rank=5)
        rationale = _enrich_play_card(c)["human_rationale"]
        assert "Straight #5" in rationale

    def test_human_rationale_box(self) -> None:
        c = _make_candidate("100", 1, box_family_match=True, box_family="019")
        rationale = _enrich_play_card(c)["human_rationale"]
        assert "Box 019" in rationale

    def test_human_rationale_fallback(self) -> None:
        c = _make_candidate("100", 1)
        rationale = _enrich_play_card(c)["human_rationale"]
        assert rationale == "Signal convergence"

    def test_original_fields_preserved(self) -> None:
        c = _make_candidate("999", 2)
        out = _enrich_play_card(c)
        assert out["number"] == "999"
        assert out["tier"] == 2


# ---------------------------------------------------------------------------
# _pair_families
# ---------------------------------------------------------------------------

class TestPairFamilies:
    def test_deduplicates_by_pair_value(self) -> None:
        pools = {
            "front_pair": [{"value": "12", "draws_since": 3}],
            "back_pair":  [{"value": "12", "draws_since": 8}],  # same value, higher ds
        }
        result = _pair_families(pools)
        assert len(result) == 1
        assert result[0]["pair"] == "12"
        assert result[0]["draws_since"] == 8

    def test_keeps_highest_draws_since(self) -> None:
        pools = {
            "front_pair": [{"value": "55", "draws_since": 5}],
            "split_pair": [{"value": "55", "draws_since": 20}],
        }
        result = _pair_families(pools)
        assert result[0]["draws_since"] == 20

    def test_sorted_descending_by_draws_since(self) -> None:
        pools = {
            "front_pair": [
                {"value": "11", "draws_since": 2},
                {"value": "22", "draws_since": 9},
                {"value": "33", "draws_since": 5},
            ],
        }
        result = _pair_families(pools)
        ds_values = [r["draws_since"] for r in result]
        assert ds_values == sorted(ds_values, reverse=True)

    def test_capped_at_12(self) -> None:
        pools = {
            "front_pair": [{"value": str(i).zfill(2), "draws_since": i} for i in range(20)],
        }
        result = _pair_families(pools)
        assert len(result) <= 12

    def test_position_label_present(self) -> None:
        pools = {"front_pair": [{"value": "99", "draws_since": 1}]}
        result = _pair_families(pools)
        assert result[0]["position_label"] == "Front Pair"

    def test_empty_pools(self) -> None:
        assert _pair_families({}) == []


# ---------------------------------------------------------------------------
# _box_families
# ---------------------------------------------------------------------------

class TestBoxFamilies:
    def test_groups_by_sorted_digits(self) -> None:
        combos = [
            {"value": "123", "draws_since": 5, "rank": 1},
            {"value": "321", "draws_since": 8, "rank": 2},
            {"value": "213", "draws_since": 3, "rank": 3},
        ]
        result = _box_families(combos)
        assert len(result) == 1
        assert result[0]["family"] == "123"

    def test_keeps_highest_draws_since_per_family(self) -> None:
        combos = [
            {"value": "123", "draws_since": 5, "rank": 1},
            {"value": "321", "draws_since": 10, "rank": 2},
        ]
        result = _box_families(combos)
        assert result[0]["draws_since"] == 10

    def test_sorted_descending(self) -> None:
        combos = [
            {"value": "111", "draws_since": 1, "rank": 3},
            {"value": "222", "draws_since": 9, "rank": 1},
            {"value": "333", "draws_since": 4, "rank": 2},
        ]
        result = _box_families(combos)
        ds_values = [r["draws_since"] for r in result]
        assert ds_values == sorted(ds_values, reverse=True)

    def test_capped_at_8(self) -> None:
        combos = [{"value": str(i).zfill(3), "draws_since": i, "rank": i} for i in range(20)]
        result = _box_families(combos)
        assert len(result) <= 8

    def test_has_family_example_rank(self) -> None:
        combos = [{"value": "579", "draws_since": 3, "rank": 7}]
        result = _box_families(combos)
        assert result[0]["family"] == "579"
        assert result[0]["example"] == "579"
        assert result[0]["rank"] == 7

    def test_empty(self) -> None:
        assert _box_families([]) == []


# ---------------------------------------------------------------------------
# build_play_builder_session — shape
# ---------------------------------------------------------------------------

_TOP_LEVEL_KEYS = {
    "session", "game_label", "rail", "plays",
    "straight_plays", "box_plays", "pair_families", "box_families",
    "audit", "metadata",
}

_RAIL_KEYS = {
    "due_sums", "due_root_sums", "due_pairs",
    "due_straight_combos", "due_box_combos",
    "pattern_singles", "pattern_doubles", "pattern_triples",
}

_PLAYS_KEYS = {
    "tier_1", "tier_2", "tier_3",
    "tier_1_count", "tier_2_count", "tier_3_count", "total",
}

_ENRICHED_CARD_KEYS = {"confidence_label", "confidence_desc", "play_type", "human_rationale"}


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_has_required_top_level_keys(session: str) -> None:
    vm = build_play_builder_session(session)
    assert _TOP_LEVEL_KEYS <= vm.keys()


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_label_contains_session(session: str) -> None:
    vm = build_play_builder_session(session)
    assert session in vm["game_label"]


def test_session_rail_has_required_keys() -> None:
    vm = build_play_builder_session("Midday")
    assert _RAIL_KEYS <= vm["rail"].keys()


def test_session_plays_has_required_keys() -> None:
    vm = build_play_builder_session("Midday")
    assert _PLAYS_KEYS <= vm["plays"].keys()


def test_session_play_cards_are_enriched() -> None:
    vm = build_play_builder_session("Midday")
    all_cards = vm["plays"]["tier_1"] + vm["plays"]["tier_2"] + vm["plays"]["tier_3"]
    assert all_cards, "expected at least one play card"
    for card in all_cards:
        assert _ENRICHED_CARD_KEYS <= card.keys(), f"missing enrichment keys on {card}"


def test_session_straight_plays_capped_at_10() -> None:
    vm = build_play_builder_session("Midday")
    assert len(vm["straight_plays"]) <= 10


def test_session_box_plays_capped_at_10() -> None:
    vm = build_play_builder_session("Midday")
    assert len(vm["box_plays"]) <= 10


def test_session_pair_families_list() -> None:
    vm = build_play_builder_session("Midday")
    assert isinstance(vm["pair_families"], list)


def test_session_box_families_list() -> None:
    vm = build_play_builder_session("Midday")
    assert isinstance(vm["box_families"], list)


def test_session_tier_counts_match_lists() -> None:
    vm = build_play_builder_session("Midday")
    plays = vm["plays"]
    assert len(plays["tier_1"]) == plays["tier_1_count"]
    assert len(plays["tier_2"]) == plays["tier_2_count"]
    assert len(plays["tier_3"]) == plays["tier_3_count"]


def test_session_due_pairs_has_six_subtypes() -> None:
    vm = build_play_builder_session("Midday")
    expected = {"front_straight", "front_box", "back_straight", "back_box", "split_straight", "split_box"}
    assert expected <= vm["rail"]["due_pairs"].keys()


def test_invalid_session_raises() -> None:
    with pytest.raises(ValueError, match="unrecognized session"):
        build_play_builder_session("Noon")


# ---------------------------------------------------------------------------
# build_play_builder_overview — shape
# ---------------------------------------------------------------------------

_OVERVIEW_TOP_KEYS = {"session_cards", "multi_session", "overview_supported", "audit", "metadata"}
_CARD_REQUIRED = {
    "session", "game_label", "freshness_status", "coverage",
    "tier_1_count", "tier_2_count", "tier_3_count", "total_candidates",
    "last_processed_draw", "top_candidates",
}


def test_overview_has_required_keys() -> None:
    vm = build_play_builder_overview()
    assert _OVERVIEW_TOP_KEYS <= vm.keys()


def test_overview_session_cards_covers_all_sessions() -> None:
    vm = build_play_builder_overview()
    assert set(vm["session_cards"].keys()) == {"Midday", "Evening", "Night"}


def test_overview_session_card_has_required_fields() -> None:
    vm = build_play_builder_overview()
    for sess, card in vm["session_cards"].items():
        missing = _CARD_REQUIRED - card.keys()
        assert not missing, f"{sess} card missing: {missing}"


def test_overview_top_candidates_are_enriched() -> None:
    vm = build_play_builder_overview()
    for sess, card in vm["session_cards"].items():
        for c in card["top_candidates"]:
            assert _ENRICHED_CARD_KEYS <= c.keys(), f"{sess} candidate missing enrichment"


def test_overview_top_candidates_capped_at_4() -> None:
    vm = build_play_builder_overview()
    for card in vm["session_cards"].values():
        assert len(card["top_candidates"]) <= 4


def test_overview_multi_session_list() -> None:
    vm = build_play_builder_overview()
    assert isinstance(vm["multi_session"], list)
