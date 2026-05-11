"""Tests for the cross-session all-draws overview board."""

import pytest

from bluegrass.app.overview import build_all_draws_overview
from bluegrass.research.stats_store import reset_stats_state

_SECTIONS = ("top_sums", "top_root_sums", "top_pairs", "top_combinations")
_CARD_REQUIRED_KEYS = {"family", "value", "draws_since", "last_seen",
                       "why_flagged", "sessions_present", "support_count"}


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


# ---------------------------------------------------------------------------
# Top-level shape
# ---------------------------------------------------------------------------

def test_overview_has_required_top_level_keys() -> None:
    ov = build_all_draws_overview()
    for key in ("top_sums", "top_root_sums", "top_pairs", "top_combinations",
                "consensus_shortlist", "session_overlap", "rationale", "metadata"):
        assert key in ov, f"missing key: {key}"


def test_overview_returns_dict() -> None:
    assert isinstance(build_all_draws_overview(), dict)


# ---------------------------------------------------------------------------
# Section cards
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("section", _SECTIONS)
def test_sections_non_empty(section: str) -> None:
    ov = build_all_draws_overview()
    assert len(ov[section]) > 0


@pytest.mark.parametrize("section", _SECTIONS)
def test_sections_capped(section: str) -> None:
    ov = build_all_draws_overview()
    assert len(ov[section]) <= 5


@pytest.mark.parametrize("section", _SECTIONS)
def test_cards_have_provenance_fields(section: str) -> None:
    ov = build_all_draws_overview()
    for card in ov[section]:
        assert "sessions_present" in card, f"{section} card missing sessions_present"
        assert "support_count" in card, f"{section} card missing support_count"
        assert isinstance(card["sessions_present"], list)
        assert isinstance(card["support_count"], int)
        assert card["support_count"] >= 1


@pytest.mark.parametrize("section", _SECTIONS)
def test_sessions_present_contains_valid_sessions(section: str) -> None:
    ov = build_all_draws_overview()
    valid = {"Midday", "Evening", "Night"}
    for card in ov[section]:
        for s in card["sessions_present"]:
            assert s in valid, f"unknown session {s!r} in {section}"


@pytest.mark.parametrize("section", _SECTIONS)
def test_support_count_matches_sessions_present(section: str) -> None:
    ov = build_all_draws_overview()
    for card in ov[section]:
        assert card["support_count"] == len(card["sessions_present"])


@pytest.mark.parametrize("section", _SECTIONS)
def test_no_internal_score_field(section: str) -> None:
    ov = build_all_draws_overview()
    for card in ov[section]:
        assert "_score" not in card


# ---------------------------------------------------------------------------
# Session overlap
# ---------------------------------------------------------------------------

def test_session_overlap_is_list() -> None:
    ov = build_all_draws_overview()
    assert isinstance(ov["session_overlap"], list)


def test_session_overlap_entries_have_support_count_at_least_2() -> None:
    ov = build_all_draws_overview()
    for item in ov["session_overlap"]:
        assert item["support_count"] >= 2, (
            f"session_overlap item {item['value']!r} has support_count={item['support_count']}"
        )


def test_session_overlap_has_provenance() -> None:
    ov = build_all_draws_overview()
    for item in ov["session_overlap"]:
        assert "sessions_present" in item
        assert "family" in item
        assert "value" in item


def test_session_overlap_no_internal_score() -> None:
    ov = build_all_draws_overview()
    for item in ov["session_overlap"]:
        assert "_score" not in item


# ---------------------------------------------------------------------------
# Consensus shortlist
# ---------------------------------------------------------------------------

def test_consensus_shortlist_non_empty() -> None:
    ov = build_all_draws_overview()
    assert len(ov["consensus_shortlist"]) > 0


def test_consensus_shortlist_capped_at_twelve() -> None:
    ov = build_all_draws_overview()
    assert len(ov["consensus_shortlist"]) <= 12


def test_consensus_shortlist_has_all_four_families() -> None:
    ov = build_all_draws_overview()
    families = {e["family"] for e in ov["consensus_shortlist"]}
    assert "sum" in families
    assert "root_sum" in families
    assert "pair" in families
    assert "combination" in families


def test_consensus_shortlist_no_family_exceeds_quota() -> None:
    from collections import Counter
    ov = build_all_draws_overview()
    counts = Counter(e["family"] for e in ov["consensus_shortlist"])
    for fam, count in counts.items():
        assert count <= 3, f"family {fam!r} has {count} entries, quota is 3"


def test_consensus_shortlist_entries_have_provenance() -> None:
    ov = build_all_draws_overview()
    for entry in ov["consensus_shortlist"]:
        assert "sessions_present" in entry
        assert "support_count" in entry
        assert "family" in entry
        assert "value" in entry
        assert "why_flagged" in entry


def test_consensus_shortlist_no_internal_score() -> None:
    ov = build_all_draws_overview()
    for entry in ov["consensus_shortlist"]:
        assert "_score" not in entry


# ---------------------------------------------------------------------------
# Subtype field — present for pairs/combos, absent for sums/root_sums
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("section", ("top_pairs", "top_combinations"))
def test_pair_combo_section_cards_have_subtype(section: str) -> None:
    ov = build_all_draws_overview()
    for card in ov[section]:
        assert "subtype" in card, f"{section} card missing subtype"


@pytest.mark.parametrize("section", ("top_sums", "top_root_sums"))
def test_sum_section_cards_omit_subtype(section: str) -> None:
    ov = build_all_draws_overview()
    for card in ov[section]:
        assert "subtype" not in card, f"{section} card should not have subtype"


def test_consensus_shortlist_pair_combo_entries_have_subtype() -> None:
    ov = build_all_draws_overview()
    for entry in ov["consensus_shortlist"]:
        if entry["family"] in ("pair", "combination"):
            assert "subtype" in entry, f"{entry['family']} shortlist entry missing subtype"


def test_consensus_shortlist_sum_entries_omit_subtype() -> None:
    ov = build_all_draws_overview()
    for entry in ov["consensus_shortlist"]:
        if entry["family"] in ("sum", "root_sum"):
            assert "subtype" not in entry, f"{entry['family']} shortlist entry should not have subtype"


# ---------------------------------------------------------------------------
# Rationale
# ---------------------------------------------------------------------------

def test_rationale_is_non_empty_string() -> None:
    ov = build_all_draws_overview()
    assert isinstance(ov["rationale"], str)
    assert len(ov["rationale"]) > 20


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def test_metadata_has_sessions_list() -> None:
    ov = build_all_draws_overview()
    meta = ov["metadata"]
    assert "sessions" in meta
    assert set(meta["sessions"]) == {"Midday", "Evening", "Night"}


def test_metadata_has_standard_fields() -> None:
    ov = build_all_draws_overview()
    meta = ov["metadata"]
    assert meta["source"] == "engine-runtime"
    assert meta["analysis_window_days"] == 250
    assert meta["sync_window_days"] == 30
    assert "generated_at" in meta
