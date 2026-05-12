import pytest

from bluegrass.app.playlist import build_session_playlist, build_session_stats
from bluegrass.research.stats_store import reset_stats_state


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


# --- build_session_stats ---

@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_stats_shape(session: str) -> None:
    stats = build_session_stats(session)
    assert stats["session"] == session
    assert "sums" in stats
    assert "root_sums" in stats
    assert "pairs" in stats
    assert "combinations" in stats


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_session_stats_boards_non_empty(session: str) -> None:
    stats = build_session_stats(session)
    assert len(stats["sums"]) > 0
    assert len(stats["root_sums"]) > 0


def test_session_stats_bad_session() -> None:
    with pytest.raises(ValueError, match="session"):
        build_session_stats("Noon")


# --- build_session_playlist ---

@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_playlist_all_families_present(session: str) -> None:
    pl = build_session_playlist(session)
    assert "sums" in pl
    assert "root_sums" in pl
    assert "pairs" in pl
    assert "combinations" in pl
    assert "shortlist" in pl


@pytest.mark.parametrize("session", ["Midday", "Evening", "Night"])
def test_shortlist_non_empty(session: str) -> None:
    pl = build_session_playlist(session)
    assert len(pl["shortlist"]) > 0


def test_shortlist_count_field_matches() -> None:
    pl = build_session_playlist("Midday")
    assert pl["shortlist_count"] == len(pl["shortlist"])


def test_shortlist_respects_limit() -> None:
    pl = build_session_playlist("Evening", limit=5)
    assert len(pl["shortlist"]) <= 5


def test_shortlist_entries_have_required_keys() -> None:
    pl = build_session_playlist("Night")
    for entry in pl["shortlist"]:
        assert "family" in entry
        assert "value" in entry
        assert "why_flagged" in entry
        assert "session" in entry


def test_shortlist_includes_sum_and_root_sum_families() -> None:
    pl = build_session_playlist("Midday")
    families = {e["family"] for e in pl["shortlist"]}
    assert "sum" in families
    assert "root_sum" in families


def test_sum_entries_have_why_flagged() -> None:
    pl = build_session_playlist("Midday")
    for e in pl["shortlist"]:
        if e["family"] in ("sum", "root_sum"):
            assert e["why_flagged"]


def test_playlist_bad_session() -> None:
    with pytest.raises(ValueError, match="session"):
        build_session_playlist("Noon")


# --- build_session_stats new fields ---

def test_session_stats_includes_metadata() -> None:
    stats = build_session_stats("Night")
    assert "metadata" in stats
    assert stats["metadata"]["session"] == "Night"
    assert stats["metadata"]["source"] == "engine-runtime"
    assert stats["metadata"]["analysis_window_days"] == 540
    assert stats["metadata"]["sync_window_days"] == 30
    assert "last_processed_draw" in stats["metadata"]


def test_session_stats_includes_playlist_preview() -> None:
    stats = build_session_stats("Midday")
    assert "playlist_preview" in stats
    assert len(stats["playlist_preview"]) > 0


def test_playlist_preview_has_required_keys() -> None:
    stats = build_session_stats("Evening")
    for entry in stats["playlist_preview"]:
        assert "family" in entry
        assert "value" in entry
        assert "why_flagged" in entry
        assert "session" in entry


# --- ranking / diversity ---

def test_shortlist_family_diversity() -> None:
    pl = build_session_playlist("Midday", limit=20)
    families = {e["family"] for e in pl["shortlist"]}
    assert len(families) >= 2


def test_shortlist_no_family_exceeds_cap() -> None:
    pl = build_session_playlist("Night", limit=20)
    from collections import Counter
    counts = Counter(e["family"] for e in pl["shortlist"])
    for fam, count in counts.items():
        assert count <= 5, f"family {fam!r} has {count} entries, exceeds cap of 5"


def test_shortlist_no_internal_score_field_exposed() -> None:
    pl = build_session_playlist("Evening")
    for entry in pl["shortlist"]:
        assert "_score" not in entry


def test_metadata_last_processed_draw_updates_after_refresh() -> None:
    from bluegrass.engine.intake import EngineResult
    from bluegrass.research.refresh import refresh_from_result
    r = EngineResult(date="2026-05-10", session="Midday", result="123",
                     jurisdiction="GA", game_family="Pick 3")
    refresh_from_result(r)
    stats = build_session_stats("Midday")
    assert stats["metadata"]["last_processed_draw"] == "2026-05-10:Midday:123"
