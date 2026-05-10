"""Unit tests for the classification utilities."""

import pytest

from bluegrass.app.classify import classify_digit_pattern, classify_pair, classify_play_type


# ---------------------------------------------------------------------------
# classify_digit_pattern
# ---------------------------------------------------------------------------

class TestDigitPattern:
    def test_single_all_unique(self):
        assert classify_digit_pattern("752") == "single"

    def test_single_leading_zero(self):
        assert classify_digit_pattern("013") == "single"

    def test_double_repeated_digit(self):
        assert classify_digit_pattern("577") == "double"

    def test_double_first_two_same(self):
        assert classify_digit_pattern("334") == "double"

    def test_double_outer_same(self):
        assert classify_digit_pattern("505") == "double"

    def test_double_leading_zero_pair(self):
        assert classify_digit_pattern("001") == "double"

    def test_triple_all_same(self):
        assert classify_digit_pattern("333") == "triple"

    def test_triple_zeros(self):
        assert classify_digit_pattern("000") == "triple"

    def test_triple_nines(self):
        assert classify_digit_pattern("999") == "triple"

    def test_empty_string_is_unknown(self):
        assert classify_digit_pattern("") == "unknown"

    def test_two_digit_is_unknown(self):
        assert classify_digit_pattern("52") == "unknown"

    def test_four_digit_is_unknown(self):
        assert classify_digit_pattern("1234") == "unknown"

    def test_non_numeric_is_unknown(self):
        assert classify_digit_pattern("abc") == "unknown"

    def test_whitespace_is_unknown(self):
        assert classify_digit_pattern("   ") == "unknown"


# ---------------------------------------------------------------------------
# classify_play_type
# ---------------------------------------------------------------------------

class TestPlayType:
    def test_straight_combination(self):
        assert classify_play_type("Straight Combination") == "straight"

    def test_box_combination(self):
        assert classify_play_type("Box Combination") == "box"

    def test_case_insensitive_straight(self):
        assert classify_play_type("STRAIGHT") == "straight"

    def test_case_insensitive_box(self):
        assert classify_play_type("BOX") == "box"

    def test_none_is_unknown(self):
        assert classify_play_type(None) == "unknown"

    def test_empty_string_is_unknown(self):
        assert classify_play_type("") == "unknown"

    def test_unrecognized_subtype_is_unknown(self):
        assert classify_play_type("Any Order") == "unknown"

    def test_straight_pair(self):
        assert classify_play_type("Front Pair Straight") == "straight"

    def test_box_pair(self):
        assert classify_play_type("Back Pair Box") == "box"


# ---------------------------------------------------------------------------
# classify_pair
# ---------------------------------------------------------------------------

class TestClassifyPair:
    def test_front_straight(self):
        result = classify_pair("Front Pair Straight")
        assert result["position"] == "front"
        assert result["play_type"] == "straight"

    def test_front_box(self):
        result = classify_pair("Front Pair Box")
        assert result["position"] == "front"
        assert result["play_type"] == "box"

    def test_back_straight(self):
        result = classify_pair("Back Pair Straight")
        assert result["position"] == "back"
        assert result["play_type"] == "straight"

    def test_back_box(self):
        result = classify_pair("Back Pair Box")
        assert result["position"] == "back"
        assert result["play_type"] == "box"

    def test_split_straight(self):
        result = classify_pair("Split Pair Straight")
        assert result["position"] == "split"
        assert result["play_type"] == "straight"

    def test_split_box(self):
        result = classify_pair("Split Pair Box")
        assert result["position"] == "split"
        assert result["play_type"] == "box"

    def test_none_is_unknown(self):
        result = classify_pair(None)
        assert result["position"] == "unknown"
        assert result["play_type"] == "unknown"

    def test_empty_string_is_unknown(self):
        result = classify_pair("")
        assert result["position"] == "unknown"
        assert result["play_type"] == "unknown"

    def test_case_insensitive(self):
        result = classify_pair("BACK PAIR STRAIGHT")
        assert result["position"] == "back"
        assert result["play_type"] == "straight"

    def test_returns_dict_with_expected_keys(self):
        result = classify_pair("Front Pair Box")
        assert set(result.keys()) == {"position", "play_type"}
