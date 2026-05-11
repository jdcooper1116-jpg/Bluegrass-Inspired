"""Acceptance tests for full derived-stat tracking in refresh_from_result.

Verifies Phase 1 + Phase 3 requirements:
- All stat families reset correctly for a known draw result
- Cross-session isolation is maintained
- Aging (draws_since increment) works across all families
- Idempotency is preserved for all new families
- Double/triple/single pattern classification
"""

from __future__ import annotations

import pytest

from bluegrass.engine.intake import EngineResult
from bluegrass.research.refresh import refresh_from_result
from bluegrass.research.stats_store import load_stats_state, reset_stats_state


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


def _r(value: str, session: str = "Midday", date: str = "2026-05-11") -> EngineResult:
    return EngineResult(date=date, session=session, result=value,
                        jurisdiction="GA", game_family="Pick 3")


# ---------------------------------------------------------------------------
# Acceptance test: 347 Midday
# ---------------------------------------------------------------------------

def test_347_midday_sum_resets():
    refresh_from_result(_r("347"))
    state = load_stats_state()["by_session"]["Midday"]
    # 3+4+7 = 14
    assert state["sums"]["14"]["draws_since"] == 0
    assert state["sums"]["14"]["last_seen"] == "2026-05-11"


def test_347_midday_root_resets():
    refresh_from_result(_r("347"))
    state = load_stats_state()["by_session"]["Midday"]
    # root(14) = 14 % 9 = 5
    assert state["root_sums"]["5"]["draws_since"] == 0


def test_347_midday_front_pair_resets():
    refresh_from_result(_r("347"))
    state = load_stats_state()["by_session"]["Midday"]
    assert state["pairs"]["front"]["34"]["draws_since"] == 0


def test_347_midday_back_pair_resets():
    refresh_from_result(_r("347"))
    state = load_stats_state()["by_session"]["Midday"]
    assert state["pairs"]["back"]["47"]["draws_since"] == 0


def test_347_midday_split_pair_resets():
    refresh_from_result(_r("347"))
    state = load_stats_state()["by_session"]["Midday"]
    assert state["pairs"]["split"]["37"]["draws_since"] == 0


def test_347_midday_straight_combo_resets():
    refresh_from_result(_r("347"))
    state = load_stats_state()["by_session"]["Midday"]
    assert state["straight_combos"]["347"]["draws_since"] == 0


def test_347_midday_box_family_resets():
    refresh_from_result(_r("347"))
    state = load_stats_state()["by_session"]["Midday"]
    # sorted("347") = "347"
    assert state["box_families"]["347"]["draws_since"] == 0


def test_347_midday_single_pattern_resets():
    refresh_from_result(_r("347"))
    state = load_stats_state()["by_session"]["Midday"]
    # 3, 4, 7 are all unique → single
    assert state["patterns"]["single"]["draws_since"] == 0
    assert state["patterns"]["single"]["last_value"] == "347"


# ---------------------------------------------------------------------------
# Acceptance test: 830 Evening
# ---------------------------------------------------------------------------

def test_830_evening_sum_resets():
    refresh_from_result(_r("830", session="Evening"))
    state = load_stats_state()["by_session"]["Evening"]
    # 8+3+0 = 11
    assert state["sums"]["11"]["draws_since"] == 0


def test_830_evening_root_resets():
    refresh_from_result(_r("830", session="Evening"))
    state = load_stats_state()["by_session"]["Evening"]
    # root(11) = 11 % 9 = 2
    assert state["root_sums"]["2"]["draws_since"] == 0


def test_830_evening_front_pair_resets():
    refresh_from_result(_r("830", session="Evening"))
    state = load_stats_state()["by_session"]["Evening"]
    assert state["pairs"]["front"]["83"]["draws_since"] == 0


def test_830_evening_back_pair_resets():
    refresh_from_result(_r("830", session="Evening"))
    state = load_stats_state()["by_session"]["Evening"]
    assert state["pairs"]["back"]["30"]["draws_since"] == 0


def test_830_evening_split_pair_resets():
    refresh_from_result(_r("830", session="Evening"))
    state = load_stats_state()["by_session"]["Evening"]
    assert state["pairs"]["split"]["80"]["draws_since"] == 0


def test_830_evening_straight_combo_resets():
    refresh_from_result(_r("830", session="Evening"))
    state = load_stats_state()["by_session"]["Evening"]
    assert state["straight_combos"]["830"]["draws_since"] == 0


def test_830_evening_box_family_resets():
    refresh_from_result(_r("830", session="Evening"))
    state = load_stats_state()["by_session"]["Evening"]
    # sorted("830") = "038"
    assert state["box_families"]["038"]["draws_since"] == 0


def test_830_evening_single_pattern_resets():
    refresh_from_result(_r("830", session="Evening"))
    state = load_stats_state()["by_session"]["Evening"]
    # 8, 3, 0 are all unique → single
    assert state["patterns"]["single"]["draws_since"] == 0


# ---------------------------------------------------------------------------
# Session isolation: Midday draw does not affect Evening
# ---------------------------------------------------------------------------

def test_midday_draw_does_not_touch_evening():
    refresh_from_result(_r("347", session="Midday"))
    state = load_stats_state()
    assert "Evening" not in state.get("by_session", {})


def test_evening_draw_does_not_touch_midday_pairs():
    refresh_from_result(_r("347", session="Midday"))
    refresh_from_result(_r("830", session="Evening"))
    mid = load_stats_state()["by_session"]["Midday"]
    eve = load_stats_state()["by_session"]["Evening"]
    # Midday front pair 34 should still be 0 (not affected by Evening draw)
    assert mid["pairs"]["front"]["34"]["draws_since"] == 0
    # Evening front pair 83 is 0
    assert eve["pairs"]["front"]["83"]["draws_since"] == 0
    # Evening front does not have 34
    assert "34" not in eve["pairs"]["front"]


# ---------------------------------------------------------------------------
# Aging: non-hit values increment across all families
# ---------------------------------------------------------------------------

def test_aging_increments_pairs():
    refresh_from_result(_r("123"))                            # front=12, back=23, split=13
    refresh_from_result(_r("456", date="2026-05-12"))         # front=45, back=56, split=46
    mid = load_stats_state()["by_session"]["Midday"]
    assert mid["pairs"]["front"]["12"]["draws_since"] == 1   # aged by second draw
    assert mid["pairs"]["front"]["45"]["draws_since"] == 0   # just hit
    assert mid["pairs"]["back"]["23"]["draws_since"] == 1
    assert mid["pairs"]["back"]["56"]["draws_since"] == 0


def test_aging_increments_straight_combos():
    refresh_from_result(_r("123"))
    refresh_from_result(_r("456", date="2026-05-12"))
    mid = load_stats_state()["by_session"]["Midday"]
    assert mid["straight_combos"]["123"]["draws_since"] == 1
    assert mid["straight_combos"]["456"]["draws_since"] == 0


def test_aging_increments_box_families():
    refresh_from_result(_r("123"))  # box = "123"
    refresh_from_result(_r("321", date="2026-05-12"))  # same box family "123"
    mid = load_stats_state()["by_session"]["Midday"]
    assert mid["box_families"]["123"]["draws_since"] == 0    # reset by 321


def test_aging_different_box_family():
    refresh_from_result(_r("123"))
    refresh_from_result(_r("456", date="2026-05-12"))
    mid = load_stats_state()["by_session"]["Midday"]
    assert mid["box_families"]["123"]["draws_since"] == 1
    assert mid["box_families"]["456"]["draws_since"] == 0


def test_pattern_aging_across_types():
    refresh_from_result(_r("123"))   # single
    refresh_from_result(_r("112", date="2026-05-12"))   # double
    mid = load_stats_state()["by_session"]["Midday"]
    assert mid["patterns"]["single"]["draws_since"] == 1     # aged
    assert mid["patterns"]["double"]["draws_since"] == 0     # just hit
    assert mid["patterns"]["triple"]["draws_since"] == 2     # aged both draws (init + second)


# ---------------------------------------------------------------------------
# Pattern classification
# ---------------------------------------------------------------------------

def test_double_pattern_detected():
    refresh_from_result(_r("334"))   # 3,3,4 → double
    mid = load_stats_state()["by_session"]["Midday"]
    assert mid["patterns"]["double"]["draws_since"] == 0
    assert mid["patterns"]["single"]["draws_since"] == 1


def test_triple_pattern_detected():
    refresh_from_result(_r("777"))   # all same → triple
    mid = load_stats_state()["by_session"]["Midday"]
    assert mid["patterns"]["triple"]["draws_since"] == 0
    assert mid["patterns"]["single"]["draws_since"] == 1
    assert mid["patterns"]["double"]["draws_since"] == 1


def test_single_pattern_detected():
    refresh_from_result(_r("123"))   # all unique → single
    mid = load_stats_state()["by_session"]["Midday"]
    assert mid["patterns"]["single"]["draws_since"] == 0


# ---------------------------------------------------------------------------
# Idempotency: duplicate draw does not corrupt any family
# ---------------------------------------------------------------------------

def test_idempotent_pairs():
    r = _r("347")
    refresh_from_result(r)
    refresh_from_result(r)
    mid = load_stats_state()["by_session"]["Midday"]
    assert mid["pairs"]["front"]["34"]["draws_since"] == 0
    assert mid["pairs"]["front"]["34"]["times_seen_runtime"] == 1


def test_idempotent_straight_combo():
    r = _r("347")
    refresh_from_result(r)
    refresh_from_result(r)
    mid = load_stats_state()["by_session"]["Midday"]
    assert mid["straight_combos"]["347"]["draws_since"] == 0
    assert mid["straight_combos"]["347"]["times_seen_runtime"] == 1


def test_idempotent_box_family():
    r = _r("347")
    refresh_from_result(r)
    refresh_from_result(r)
    mid = load_stats_state()["by_session"]["Midday"]
    assert mid["box_families"]["347"]["draws_since"] == 0
    assert mid["box_families"]["347"]["times_seen_runtime"] == 1


# ---------------------------------------------------------------------------
# Return value includes new hit fields
# ---------------------------------------------------------------------------

def test_summary_includes_all_hit_fields():
    s = refresh_from_result(_r("347"))
    assert s["hit_front_pair"] == "34"
    assert s["hit_back_pair"] == "47"
    assert s["hit_split_pair"] == "37"
    assert s["hit_straight_combo"] == "347"
    assert s["hit_box_family"] == "347"
    assert s["hit_pattern"] == "single"
    assert s["hit_sum"] == 14
    assert s["hit_root_sum"] == 5


def test_summary_830_evening():
    s = refresh_from_result(_r("830", session="Evening"))
    assert s["hit_front_pair"] == "83"
    assert s["hit_back_pair"] == "30"
    assert s["hit_split_pair"] == "80"
    assert s["hit_box_family"] == "038"
    assert s["hit_sum"] == 11
    assert s["hit_root_sum"] == 2
