"""Tests for the daily session board builder."""

import pytest

from bluegrass.app.board import build_session_board
from bluegrass.research.stats_store import reset_stats_state

_SECTIONS = ("top_sums", "top_root_sums", "top_pairs", "top_combinations")
_CARD_REQUIRED_KEYS = {"family", "value", "draws_since", "last_seen", "why_flagged"}
_BULK_KEYS = {"combo_count", "times_drawn", "run_id", "baseline_priority_score",
              "source_url", "item_type"}


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


def test_board_session_field_matches(session: str = "Midday") -> None:
    board = build_session_board("Night")
    assert board["session"] == "Night"


def test_board_bad_session_raises() -> None:
    with pytest.raises(ValueError, match="session"):
        build_session_board("Noon")


# ---------------------------------------------------------------------------
# Section cards
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
        assert "sum" in families, f"{session}: sum missing"
        assert "root_sum" in families, f"{session}: root_sum missing"
        assert "pair" in families, f"{session}: pair missing"
        assert "combination" in families, f"{session}: combination missing"


def test_shortlist_no_family_exceeds_quota() -> None:
    from collections import Counter
    for session in ["Midday", "Evening", "Night"]:
        board = build_session_board(session)
        counts = Counter(e["family"] for e in board["shortlist"])
        for fam, count in counts.items():
            assert count <= 3, f"{session}: family {fam!r} has {count} entries, quota is 3"


def test_combinations_do_not_open_shortlist() -> None:
    """Shortlist must not start with 5 ancient combinations."""
    for session in ["Midday", "Evening", "Night"]:
        board = build_session_board(session)
        first_five = board["shortlist"][:5]
        combo_count = sum(1 for e in first_five if e["family"] == "combination")
        assert combo_count <= 2, (
            f"{session}: {combo_count} combinations in top 5 (max 2 allowed)"
        )


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
    assert meta["analysis_window_days"] == 250
    assert meta["sync_window_days"] == 30
    assert "last_processed_draw" in meta
    assert "generated_at" in meta


def test_metadata_generated_at_is_iso_string() -> None:
    board = build_session_board("Evening")
    ts = board["metadata"]["generated_at"]
    assert "T" in ts or len(ts) == 10  # ISO datetime or date


def test_board_reflects_last_processed_draw_after_refresh() -> None:
    from bluegrass.engine.intake import EngineResult
    from bluegrass.research.refresh import refresh_from_result
    r = EngineResult(date="2026-05-10", session="Midday", result="123",
                     jurisdiction="GA", game_family="Pick 3")
    refresh_from_result(r)
    board = build_session_board("Midday")
    assert board["metadata"]["last_processed_draw"] == "2026-05-10:Midday:123"
