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
