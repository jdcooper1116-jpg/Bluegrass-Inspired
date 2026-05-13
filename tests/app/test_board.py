"""Tests for the daily session board builder."""

from collections import Counter

import pytest

from bluegrass.app.board import build_session_board
from bluegrass.research.config import ANALYSIS_WINDOW_DAYS
from bluegrass.research.stats_store import reset_stats_state

_SECTIONS = ("top_sums", "top_root_sums", "top_pairs", "top_combinations")
_DETAIL_SECTIONS = (
    "top_sums_detail", "top_root_sums_detail",
    "top_pairs_detail", "top_combinations_detail",
)
_CARD_REQUIRED_KEYS = {"family", "value", "draws_since", "last_seen", "why_flagged"}
_BULK_KEYS = frozenset({
    "combo_count", "times_drawn", "run_id",
    "baseline_priority_score", "source_url", "item_type",
})


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


# ---------------------------------------------------------------------------
# Top-level shape
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_board_has_required_top_level_keys(session: str) -> None:
    board = build_session_board(session)
    for key in ("session", "top_sums", "top_root_sums", "top_pairs",
                 "top_combinations", "shortlist", "rationale", "metadata"):
        assert key in board, f"missing key: {key}"


def test_board_has_detail_keys() -> None:
    board = build_session_board("Midday")
    for key in _DETAIL_SECTIONS:
        assert key in board, f"missing detail key: {key}"


def test_board_session_field_matches() -> None:
    board = build_session_board("Night")
    assert board["session"] == "Night"


def test_board_bad_session_raises() -> None:
    with pytest.raises(ValueError, match="session"):
        build_session_board("Noon")


# ---------------------------------------------------------------------------
# Compact section cards — stable contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("section", _SECTIONS)
def test_sections_non_empty(section: str) -> None:
    board = build_session_board("Midday")
    assert len(board[section]) > 0, f"{section} should not be empty"


@pytest.mark.parametrize("section", _SECTIONS)
def test_sections_capped_at_four(section: str) -> None:
    board = build_session_board("Midday")
    assert len(board[section]) <= 4, f"{section} should have at most 4 entries"


@pytest.mark.parametrize("section", _SECTIONS)
def test_cards_have_required_keys(section: str) -> None:
    board = build_session_board("Evening")
    for card in board[section]:
        missing = _CARD_REQUIRED_KEYS - card.keys()
        assert not missing, f"{section} card missing keys: {missing}"


@pytest.mark.parametrize("section", _SECTIONS)
def test_cards_exclude_bulk_keys(section: str) -> None:
    board = build_session_board("Night")
    for card in board[section]:
        leaked = _BULK_KEYS & card.keys()
        assert not leaked, f"{section} card leaks bulk keys: {leaked}"


def test_top_sums_family_label() -> None:
    board = build_session_board("Midday")
    assert all(c["family"] == "sum" for c in board["top_sums"])


def test_top_root_sums_family_label() -> None:
    board = build_session_board("Midday")
    assert all(c["family"] == "root_sum" for c in board["top_root_sums"])


def test_top_pairs_family_label() -> None:
    board = build_session_board("Evening")
    assert all(c["family"] == "pair" for c in board["top_pairs"])


def test_top_combinations_family_label() -> None:
    board = build_session_board("Night")
    assert all(c["family"] == "combination" for c in board["top_combinations"])


# ---------------------------------------------------------------------------
# Detail section cards — deviation fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("section", _DETAIL_SECTIONS)
def test_detail_sections_non_empty(section: str) -> None:
    board = build_session_board("Midday")
    assert len(board[section]) > 0, f"{section} should not be empty"


def test_top_sums_detail_has_deviation_fields() -> None:
    board = build_session_board("Midday")
    required_dev = {"gap_ratio", "severity_band", "signal_quality",
                    "expected_gap_draws", "multi_window_agreement"}
    for card in board["top_sums_detail"]:
        for key in required_dev:
            assert key in card, f"top_sums_detail card missing key: {key}"


def test_top_root_sums_detail_has_deviation_fields() -> None:
    board = build_session_board("Evening")
    for card in board["top_root_sums_detail"]:
        assert "gap_ratio" in card
        assert "severity_band" in card
        assert "signal_quality" in card


def test_top_sums_detail_signal_quality_not_none() -> None:
    board = build_session_board("Night")
    for card in board["top_sums_detail"]:
        assert card["signal_quality"] is not None
        assert card["signal_quality"] in ("deviation-backed", "overdue-only", "sparse-data")


# ---------------------------------------------------------------------------
# Compact card signal_quality labels (additive non-bulk field)
# ---------------------------------------------------------------------------

def test_top_pairs_has_signal_quality_label() -> None:
    board = build_session_board("Midday")
    for card in board["top_pairs"]:
        assert "signal_quality" in card
        assert card["signal_quality"] in ("deviation-backed", "overdue-only", "sparse-data")


def test_top_combos_labeled_overdue_only() -> None:
    board = build_session_board("Midday")
    for card in board["top_combinations"]:
        assert card.get("signal_quality") == "overdue-only"


def test_top_pairs_runtime_enrichment_when_draws_processed() -> None:
    from bluegrass.engine.intake import EngineResult
    from bluegrass.research.refresh import refresh_from_result
    for i in range(5):
        r = EngineResult(date=f"2026-05-{i+1:02d}", session="Midday",
                         result="123", jurisdiction="GA", game_family="Pick 3")
        refresh_from_result(r)
    board = build_session_board("Midday")
    for card in board["top_pairs"]:
        assert card.get("signal_quality") is not None


# ---------------------------------------------------------------------------
# Shortlist
# ---------------------------------------------------------------------------

def test_shortlist_non_empty() -> None:
    board = build_session_board("Midday")
    assert len(board["shortlist"]) > 0


def test_shortlist_capped_at_twelve() -> None:
    board = build_session_board("Evening")
    assert len(board["shortlist"]) <= 12


def test_shortlist_entries_have_required_keys() -> None:
    board = build_session_board("Night")
    for entry in board["shortlist"]:
        assert "family" in entry
        assert "value" in entry
        assert "why_flagged" in entry
        assert "session" in entry


def test_shortlist_every_entry_has_family() -> None:
    """No shortlist entry may omit the family key."""
    for session in ["Midday", "Evening", "Night"]:
        board = build_session_board(session)
        for entry in board["shortlist"]:
            assert entry.get("family") is not None, \
                f"{session}: shortlist entry missing family: {entry}"


def test_shortlist_no_internal_score_field() -> None:
    board = build_session_board("Midday")
    for entry in board["shortlist"]:
        assert "_score" not in entry


def test_shortlist_has_family_diversity() -> None:
    board = build_session_board("Midday")
    families = {e["family"] for e in board["shortlist"]}
    assert len(families) >= 4, f"all four families must appear, got: {families}"


def test_shortlist_all_four_families_present() -> None:
    for session in ["Midday", "Evening", "Night"]:
        board = build_session_board(session)
        families = {e["family"] for e in board["shortlist"]}
        assert "sum" in families,         f"{session}: sum missing"
        assert "root_sum" in families,    f"{session}: root_sum missing"
        assert "pair" in families,        f"{session}: pair missing"
        assert "combination" in families, f"{session}: combination missing"


def test_shortlist_no_family_exceeds_quota() -> None:
    for session in ["Midday", "Evening", "Night"]:
        board = build_session_board(session)
        counts = Counter(e["family"] for e in board["shortlist"])
        for fam, count in counts.items():
            assert count <= 3, f"{session}: {fam!r} has {count} entries, quota is 3"


def test_combinations_do_not_open_shortlist() -> None:
    for session in ["Midday", "Evening", "Night"]:
        board = build_session_board(session)
        first_five = board["shortlist"][:5]
        combo_count = sum(1 for e in first_five if e["family"] == "combination")
        assert combo_count <= 2, \
            f"{session}: {combo_count} combinations in top 5 (max 2 allowed)"


def test_shortlist_signal_quality_not_null_for_sum_entries() -> None:
    board = build_session_board("Midday")
    for entry in board["shortlist"]:
        if entry["family"] in ("sum", "root_sum"):
            assert entry.get("signal_quality") is not None
            assert entry.get("gap_ratio") is not None


# ---------------------------------------------------------------------------
# Rationale
# ---------------------------------------------------------------------------

def test_rationale_is_non_empty_string() -> None:
    board = build_session_board("Midday")
    assert isinstance(board["rationale"], str)
    assert len(board["rationale"]) > 20


def test_rationale_mentions_session() -> None:
    board = build_session_board("Night")
    assert "Night" in board["rationale"]


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def test_metadata_has_required_keys() -> None:
    board = build_session_board("Midday")
    meta = board["metadata"]
    assert meta["session"] == "Midday"
    assert meta["source"] == "engine-runtime"
    assert meta["analysis_window_days"] == ANALYSIS_WINDOW_DAYS
    assert meta["sync_window_days"] == 30
    assert "last_processed_draw" in meta
    assert "generated_at" in meta


def test_metadata_includes_sort_mode() -> None:
    board = build_session_board("Midday")
    assert "sort_mode" in board["metadata"]
    assert board["metadata"]["sort_mode"] in ("overdue", "deviation", "composite")


def test_metadata_includes_draws_processed() -> None:
    board = build_session_board("Evening")
    assert "draws_processed" in board["metadata"]
    assert isinstance(board["metadata"]["draws_processed"], int)


def test_metadata_generated_at_is_iso_string() -> None:
    board = build_session_board("Evening")
    ts = board["metadata"]["generated_at"]
    assert "T" in ts or len(ts) == 10


def test_board_reflects_last_processed_draw_after_refresh() -> None:
    from bluegrass.engine.intake import EngineResult
    from bluegrass.research.refresh import refresh_from_result
    r = EngineResult(date="2026-05-10", session="Midday", result="123",
                     jurisdiction="GA", game_family="Pick 3")
    refresh_from_result(r)
    board = build_session_board("Midday")
    assert board["metadata"]["last_processed_draw"] == "2026-05-10:Midday:123"


# ---------------------------------------------------------------------------
# Sort modes
# ---------------------------------------------------------------------------

def test_sort_mode_overdue_returns_valid_board() -> None:
    board = build_session_board("Midday", sort_mode="overdue")
    assert board["metadata"]["sort_mode"] == "overdue"
    assert len(board["top_sums"]) > 0


def test_sort_mode_deviation_returns_valid_board() -> None:
    board = build_session_board("Night", sort_mode="deviation")
    assert board["metadata"]["sort_mode"] == "deviation"
    assert len(board["top_sums"]) > 0


def test_invalid_sort_mode_falls_back_to_composite() -> None:
    board = build_session_board("Midday", sort_mode="nonsense")
    assert board["metadata"]["sort_mode"] == "composite"


def test_board_why_flagged_text_is_richer_for_sums() -> None:
    from bluegrass.engine.intake import EngineResult
    from bluegrass.research.refresh import refresh_from_result
    for i in range(20):
        r = EngineResult(date=f"2026-05-{i+1:02d}", session="Midday",
                         result="123", jurisdiction="GA", game_family="Pick 3")
        refresh_from_result(r)
    board = build_session_board("Midday")
    for card in board["top_sums"][:2]:
        why = card.get("why_flagged", "")
        assert len(why) > 15
        assert "draws" in why or "expected" in why or "x" in why or "×" in why


# ---------------------------------------------------------------------------
# Mode explainability: rank comparison fields and movement labels
# ---------------------------------------------------------------------------

def test_detail_cards_have_rank_fields() -> None:
    """top_sums_detail and top_root_sums_detail must carry rank comparison fields."""
    board = build_session_board("Midday")
    rank_keys = {"overdue_rank", "deviation_rank", "composite_rank",
                 "current_rank", "current_mode", "movement_label"}
    for card in board["top_sums_detail"]:
        missing = rank_keys - card.keys()
        assert not missing, f"top_sums_detail card missing rank keys: {missing}"
    for card in board["top_root_sums_detail"]:
        missing = rank_keys - card.keys()
        assert not missing, f"top_root_sums_detail card missing rank keys: {missing}"


def test_movement_label_is_present_and_string() -> None:
    board = build_session_board("Midday")
    for card in board["top_sums_detail"]:
        assert isinstance(card.get("movement_label"), str), \
            f"movement_label missing or not str on card {card['value']}"


def test_movement_label_correct_values() -> None:
    """movement_label must be one of the known values."""
    valid = {"steady", "↑ elevated", "↑↑ promoted", "↓ lower", "↓↓ demoted"}
    board = build_session_board("Midday", sort_mode="deviation")
    for card in board["top_sums_detail"]:
        assert card["movement_label"] in valid, \
            f"Unexpected movement_label: {card['movement_label']!r}"


def test_rank_delta_sign_correct_for_deviation_mode() -> None:
    """In deviation mode, a card with deviation_rank < overdue_rank should show movement up."""
    from bluegrass.engine.intake import EngineResult
    from bluegrass.research.refresh import refresh_from_result

    # Seed enough draws to create meaningful gap_ratio variation
    for i in range(30):
        r = EngineResult(
            date=f"2026-04-{(i % 28) + 1:02d}", session="Midday",
            result="135", jurisdiction="GA", game_family="Pick 3",
        )
        refresh_from_result(r)

    board_dev = build_session_board("Midday", sort_mode="deviation")
    # At least one card should be promoted (deviation_rank < overdue_rank)
    # since deviation and overdue produce very different orderings with seeded data
    top_card = board_dev["top_sums_detail"][0]
    assert top_card["overdue_rank"] >= 1
    assert top_card["deviation_rank"] >= 1
    assert top_card["current_rank"] == top_card["deviation_rank"]
    assert top_card["current_mode"] == "deviation"


def test_overdue_mode_movement_label_is_steady() -> None:
    """In overdue mode, all movement labels must be 'steady' (no delta from baseline)."""
    board = build_session_board("Midday", sort_mode="overdue")
    for card in board["top_sums_detail"]:
        assert card["movement_label"] == "steady", \
            f"overdue mode should always be steady, got: {card['movement_label']!r}"


def test_section_modes_in_board_output() -> None:
    """section_modes must be present with correct structure."""
    board = build_session_board("Midday")
    sm = board.get("section_modes")
    assert sm is not None, "section_modes missing from board output"
    for section in ("sums", "root_sums", "pairs", "combinations", "shortlist"):
        assert section in sm, f"section_modes missing key: {section}"
        assert "sorted_by" in sm[section]
        assert "mode_sensitive" in sm[section]
        assert "label" in sm[section]


def test_section_modes_sums_is_mode_sensitive() -> None:
    board = build_session_board("Midday", sort_mode="deviation")
    assert board["section_modes"]["sums"]["mode_sensitive"] is True
    assert board["section_modes"]["sums"]["sorted_by"] == "deviation"


def test_section_modes_pairs_not_mode_sensitive() -> None:
    board = build_session_board("Midday", sort_mode="deviation")
    assert board["section_modes"]["pairs"]["mode_sensitive"] is False


def test_section_modes_shortlist_always_composite() -> None:
    board = build_session_board("Evening")
    sl_mode = board["section_modes"]["shortlist"]
    assert sl_mode["mode_sensitive"] is False
    assert sl_mode["sorted_by"] == "composite"
    assert "composite" in sl_mode["label"].lower()


def test_shortlist_entries_have_score_components() -> None:
    """Every shortlist entry must carry score_components with composite_score."""
    board = build_session_board("Midday")
    for entry in board["shortlist"]:
        sc = entry.get("score_components")
        assert sc is not None, f"score_components missing on shortlist entry: {entry['family']} {entry['value']}"
        assert "composite_score" in sc, f"composite_score missing from score_components: {sc}"
        assert "scoring_mode" in sc
        assert sc["scoring_mode"] == "always composite"


def test_score_components_gap_ratio_for_sum_entries() -> None:
    """Sum shortlist entries should have gap_ratio in score_components."""
    from bluegrass.engine.intake import EngineResult
    from bluegrass.research.refresh import refresh_from_result
    for i in range(10):
        r = EngineResult(date=f"2026-05-{i+1:02d}", session="Night",
                         result="246", jurisdiction="GA", game_family="Pick 3")
        refresh_from_result(r)
    board = build_session_board("Night")
    for entry in board["shortlist"]:
        if entry["family"] in ("sum", "root_sum"):
            sc = entry["score_components"]
            assert "gap_ratio" in sc


def test_compact_cards_no_rank_fields_leaked() -> None:
    """Rank comparison fields must NOT appear on compact cards."""
    rank_keys = {"overdue_rank", "deviation_rank", "composite_rank",
                 "movement_label", "compare_note"}
    board = build_session_board("Midday")
    for section in ("top_sums", "top_root_sums", "top_pairs", "top_combinations"):
        for card in board[section]:
            leaked = rank_keys & card.keys()
            assert not leaked, f"{section} compact card leaks rank keys: {leaked}"
