"""Tests for the convergence builder."""

import pytest

from bluegrass.app.convergence import (
    _box_family,
    _digit_sum,
    _digital_root,
    _normalize_pair_subtype,
    _pair_value,
    build_convergence_overview,
    build_session_convergence,
)
from bluegrass.research.stats_store import reset_stats_state

_SESSIONS = ("Midday", "Evening", "Night")

_REQUIRED_CANDIDATE_KEYS = {
    "number", "digit_sum", "root_sum", "digit_pattern",
    "convergence_score", "tier", "rationale", "signals",
    "in_combo_pool", "multi_session",
    # future-ready pillar fields
    "sweet404_match", "planetary_match",
    "external_convergence_match", "pillar_support_count",
}

_REQUIRED_SIGNAL_KEYS = {
    "sum_match", "sum_value", "sum_rank",
    "root_sum_match", "root_sum_value", "root_sum_rank",
    "pair_hits", "pair_hit_count",
    "straight_match", "straight_rank",
    "box_family_match", "box_family", "box_family_rank",
    "pattern_pool_match",
}


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


# ---------------------------------------------------------------------------
# Pure helper unit tests
# ---------------------------------------------------------------------------

class TestBoxFamily:
    def test_sorted_digits(self):
        assert _box_family("752") == "257"

    def test_same_family_different_order(self):
        assert _box_family("752") == _box_family("257")
        assert _box_family("752") == _box_family("725")
        assert _box_family("752") == _box_family("527")

    def test_triple_family(self):
        assert _box_family("333") == "333"

    def test_double_family(self):
        assert _box_family("577") == "577"

    def test_leading_zero(self):
        assert _box_family("042") == "024"


class TestDigitSum:
    def test_basic(self):
        assert _digit_sum("752") == 14

    def test_leading_zero(self):
        assert _digit_sum("007") == 7

    def test_zeros(self):
        assert _digit_sum("000") == 0


class TestDigitalRoot:
    def test_single_digit(self):
        assert _digital_root(5) == 5

    def test_double_digit(self):
        assert _digital_root(14) == 5   # 1+4=5

    def test_zero(self):
        assert _digital_root(0) == 0

    def test_nine(self):
        assert _digital_root(9) == 9

    def test_eighteen(self):
        assert _digital_root(18) == 9  # 1+8=9


class TestPairValue:
    def test_front(self):
        assert _pair_value("752", "front") == "75"

    def test_back(self):
        assert _pair_value("752", "back") == "52"

    def test_split(self):
        assert _pair_value("752", "split") == "72"

    def test_leading_zero(self):
        assert _pair_value("042", "front") == "04"
        assert _pair_value("042", "back") == "42"
        assert _pair_value("042", "split") == "02"


class TestNormalizePairSubtype:
    def test_front_straight(self):
        assert _normalize_pair_subtype("Front Pair Straight") == "front_straight"

    def test_front_box(self):
        assert _normalize_pair_subtype("Front Pair Box") == "front_box"

    def test_back_straight(self):
        assert _normalize_pair_subtype("Back Pair Straight") == "back_straight"

    def test_back_box(self):
        assert _normalize_pair_subtype("Back Pair Box") == "back_box"

    def test_split_straight(self):
        assert _normalize_pair_subtype("Split Pair Straight") == "split_straight"

    def test_split_box(self):
        assert _normalize_pair_subtype("Split Pair Box") == "split_box"

    def test_none_returns_other(self):
        assert _normalize_pair_subtype(None) == "other"

    def test_case_insensitive(self):
        assert _normalize_pair_subtype("FRONT PAIR STRAIGHT") == "front_straight"


# ---------------------------------------------------------------------------
# build_session_convergence — shape
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", _SESSIONS)
def test_build_session_convergence_has_required_keys(session):
    result = build_session_convergence(session)
    for key in ("session", "candidates", "signal_pools", "tier_1_count",
                "tier_2_count", "tier_3_count", "total_candidates", "metadata"):
        assert key in result, f"missing key: {key}"


@pytest.mark.parametrize("session", _SESSIONS)
def test_candidates_non_empty(session):
    result = build_session_convergence(session)
    assert len(result["candidates"]) > 0


@pytest.mark.parametrize("session", _SESSIONS)
def test_candidate_has_required_fields(session):
    result = build_session_convergence(session)
    for c in result["candidates"]:
        missing = _REQUIRED_CANDIDATE_KEYS - set(c.keys())
        assert not missing, f"candidate missing fields: {missing}"


@pytest.mark.parametrize("session", _SESSIONS)
def test_candidate_signals_have_required_keys(session):
    result = build_session_convergence(session)
    for c in result["candidates"]:
        missing = _REQUIRED_SIGNAL_KEYS - set(c["signals"].keys())
        assert not missing, f"signals missing keys: {missing}"


# ---------------------------------------------------------------------------
# Future-ready pillar fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", _SESSIONS)
def test_future_fields_are_none(session):
    result = build_session_convergence(session)
    for c in result["candidates"]:
        assert c["sweet404_match"] is None
        assert c["planetary_match"] is None
        assert c["external_convergence_match"] is None
        assert c["pillar_support_count"] is None


# ---------------------------------------------------------------------------
# Scoring and tiering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", _SESSIONS)
def test_tier_1_score_at_least_threshold(session):
    result = build_session_convergence(session)
    for c in result["candidates"]:
        if c["tier"] == 1:
            assert c["convergence_score"] >= 5.0, (
                f"T1 candidate {c['number']} has score {c['convergence_score']}"
            )


@pytest.mark.parametrize("session", _SESSIONS)
def test_tier_2_score_in_range(session):
    result = build_session_convergence(session)
    for c in result["candidates"]:
        if c["tier"] == 2:
            assert 3.0 <= c["convergence_score"] < 5.0, (
                f"T2 candidate {c['number']} has score {c['convergence_score']}"
            )


@pytest.mark.parametrize("session", _SESSIONS)
def test_all_candidates_above_min_score(session):
    result = build_session_convergence(session)
    for c in result["candidates"]:
        assert c["convergence_score"] >= 1.0, (
            f"candidate {c['number']} below T3 floor: {c['convergence_score']}"
        )


@pytest.mark.parametrize("session", _SESSIONS)
def test_candidates_sorted_by_score_descending(session):
    result = build_session_convergence(session)
    scores = [c["convergence_score"] for c in result["candidates"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.parametrize("session", _SESSIONS)
def test_tier_counts_match_candidates(session):
    result = build_session_convergence(session)
    from collections import Counter
    actual = Counter(c["tier"] for c in result["candidates"])
    assert result["tier_1_count"] == actual.get(1, 0)
    assert result["tier_2_count"] == actual.get(2, 0)
    assert result["tier_3_count"] == actual.get(3, 0)


# ---------------------------------------------------------------------------
# Box-family matching (sorted digits, not exact equality)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", _SESSIONS)
def test_box_family_signal_is_present_on_all_candidates(session):
    result = build_session_convergence(session)
    for c in result["candidates"]:
        assert "box_family_match" in c["signals"]
        assert "box_family" in c["signals"]


@pytest.mark.parametrize("session", _SESSIONS)
def test_box_family_is_sorted_digits_of_number(session):
    result = build_session_convergence(session)
    for c in result["candidates"]:
        expected = "".join(sorted(c["number"]))
        assert c["signals"]["box_family"] == expected


# ---------------------------------------------------------------------------
# Signal pools
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", _SESSIONS)
def test_signal_pools_has_required_keys(session):
    result = build_session_convergence(session)
    pools = result["signal_pools"]
    for key in ("sums", "root_sums", "pairs_by_subtype",
                "straight_combos", "box_combos", "singles", "doubles", "triples"):
        assert key in pools, f"signal_pools missing: {key}"


@pytest.mark.parametrize("session", _SESSIONS)
def test_pairs_by_subtype_has_all_six_subtypes(session):
    result = build_session_convergence(session)
    pbs = result["signal_pools"]["pairs_by_subtype"]
    for st in ("front_straight", "front_box", "back_straight",
               "back_box", "split_straight", "split_box"):
        assert st in pbs, f"pairs_by_subtype missing: {st}"


@pytest.mark.parametrize("session", _SESSIONS)
def test_signal_pools_capped_at_top_10(session):
    result = build_session_convergence(session)
    pools = result["signal_pools"]
    assert len(pools["sums"]) <= 10
    assert len(pools["root_sums"]) <= 10
    assert len(pools["straight_combos"]) <= 10
    assert len(pools["box_combos"]) <= 10
    for st, pairs in pools["pairs_by_subtype"].items():
        assert len(pairs) <= 10, f"{st} has more than 10 entries"


# ---------------------------------------------------------------------------
# Supplementary candidates (sum × pair intersections)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", _SESSIONS)
def test_in_combo_pool_field_present(session):
    result = build_session_convergence(session)
    for c in result["candidates"]:
        assert "in_combo_pool" in c


# ---------------------------------------------------------------------------
# Candidate field correctness
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", _SESSIONS)
def test_candidate_numbers_are_three_digit_strings(session):
    result = build_session_convergence(session)
    for c in result["candidates"]:
        assert len(c["number"]) == 3
        assert c["number"].isdigit()


@pytest.mark.parametrize("session", _SESSIONS)
def test_candidate_digit_sum_is_correct(session):
    result = build_session_convergence(session)
    for c in result["candidates"][:10]:
        expected = sum(int(d) for d in c["number"])
        assert c["digit_sum"] == expected


@pytest.mark.parametrize("session", _SESSIONS)
def test_multi_session_field_defaults_false(session):
    result = build_session_convergence(session)
    for c in result["candidates"]:
        assert c["multi_session"] is False


@pytest.mark.parametrize("session", _SESSIONS)
def test_rationale_is_non_empty_string(session):
    result = build_session_convergence(session)
    for c in result["candidates"]:
        assert isinstance(c["rationale"], str)
        assert len(c["rationale"]) > 0


# ---------------------------------------------------------------------------
# Invalid session
# ---------------------------------------------------------------------------

def test_invalid_session_raises():
    with pytest.raises(ValueError):
        build_session_convergence("Weekend")


# ---------------------------------------------------------------------------
# build_convergence_overview
# ---------------------------------------------------------------------------

def test_convergence_overview_has_required_keys():
    result = build_convergence_overview()
    for key in ("multi_session_candidates", "overview_supported_candidates",
                "session_summaries", "metadata"):
        assert key in result, f"missing key: {key}"


def test_convergence_overview_buckets_are_lists():
    result = build_convergence_overview()
    assert isinstance(result["multi_session_candidates"], list)
    assert isinstance(result["overview_supported_candidates"], list)


def test_convergence_overview_no_duplicate_numbers():
    result = build_convergence_overview()
    a_nums = {c["number"] for c in result["multi_session_candidates"]}
    b_nums = {c["number"] for c in result["overview_supported_candidates"]}
    overlap = a_nums & b_nums
    assert not overlap, f"duplicate numbers in both buckets: {overlap}"


def test_convergence_overview_session_summaries_covers_all_sessions():
    result = build_convergence_overview()
    assert set(result["session_summaries"].keys()) == {"Midday", "Evening", "Night"}


def test_convergence_overview_multi_session_have_sessions_present():
    result = build_convergence_overview()
    for c in result["multi_session_candidates"]:
        assert "sessions_present" in c
        assert len(c["sessions_present"]) >= 2
