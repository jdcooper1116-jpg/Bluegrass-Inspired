import pytest

from bluegrass.engine.intake import EngineResult
from bluegrass.research.refresh import refresh_from_result
from bluegrass.research.stats_store import load_stats_state, reset_stats_state


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


def _result(value: str, session: str = "Midday", date: str = "2026-05-10") -> EngineResult:
    return EngineResult(date=date, session=session, result=value,
                        jurisdiction="GA", game_family="Pick 3")


def test_returns_summary() -> None:
    s = refresh_from_result(_result("123"))
    assert s["session"] == "Midday"
    assert s["result"] == "123"
    assert s["hit_sum"] == 6
    assert s["hit_root_sum"] == 6
    assert s["session_draws_processed"] == 1
    assert s["total_draws_processed"] == 1


def test_persists_state() -> None:
    refresh_from_result(_result("007"))
    state = load_stats_state()
    assert "Midday" in state["by_session"]
    session = state["by_session"]["Midday"]
    assert "sums" in session
    assert "root_sums" in session


def test_hit_sum_resets_to_zero() -> None:
    refresh_from_result(_result("123"))  # sum=6
    state = load_stats_state()
    assert state["by_session"]["Midday"]["sums"]["6"]["draws_since"] == 0
    assert state["by_session"]["Midday"]["sums"]["6"]["last_seen"] == "2026-05-10"
    assert state["by_session"]["Midday"]["sums"]["6"]["times_seen_runtime"] == 1


def test_non_hit_sums_increment() -> None:
    refresh_from_result(_result("123"))          # sum=6 hits
    refresh_from_result(_result("456", date="2026-05-11"))  # sum=15 hits
    sums = load_stats_state()["by_session"]["Midday"]["sums"]
    assert sums["6"]["draws_since"] == 1
    assert sums["15"]["draws_since"] == 0


def test_draw_counters() -> None:
    refresh_from_result(_result("100"))
    refresh_from_result(_result("200"))
    state = load_stats_state()
    assert state["by_session"]["Midday"]["draws_processed"] == 2
    assert state["total_draws_processed"] == 2


def test_sessions_are_isolated() -> None:
    refresh_from_result(_result("111", session="Midday"))
    refresh_from_result(_result("222", session="Evening"))
    state = load_stats_state()
    assert state["by_session"]["Midday"]["draws_processed"] == 1
    assert state["by_session"]["Evening"]["draws_processed"] == 1


def test_repeated_hit_increments_times_seen() -> None:
    refresh_from_result(_result("123"))
    refresh_from_result(_result("123", date="2026-05-12"))
    sums = load_stats_state()["by_session"]["Midday"]["sums"]
    assert sums["6"]["times_seen_runtime"] == 2
    assert sums["6"]["draws_since"] == 0


def test_leading_zero_result() -> None:
    s = refresh_from_result(_result("007"))
    assert s["result"] == "007"
    assert s["hit_sum"] == 7
    assert s["hit_root_sum"] == 7


# --- idempotency ---

def test_duplicate_draw_is_skipped() -> None:
    r = _result("123")
    refresh_from_result(r)
    s = refresh_from_result(r)
    assert s["skipped"] is True
    state = load_stats_state()
    assert state["by_session"]["Midday"]["draws_processed"] == 1
    assert state["total_draws_processed"] == 1


def test_duplicate_does_not_double_count_sums() -> None:
    r = _result("123")
    refresh_from_result(r)
    refresh_from_result(r)
    sums = load_stats_state()["by_session"]["Midday"]["sums"]
    assert sums["6"]["times_seen_runtime"] == 1
    assert sums["6"]["draws_since"] == 0


def test_different_date_same_number_not_skipped() -> None:
    refresh_from_result(_result("123", date="2026-05-10"))
    s = refresh_from_result(_result("123", date="2026-05-11"))
    assert s.get("skipped") is not True
    assert s["total_draws_processed"] == 2


def test_leading_zero_draw_id_preserved() -> None:
    r = _result("007")
    refresh_from_result(r)
    s = refresh_from_result(r)
    assert s["skipped"] is True


def test_non_skipped_result_has_skipped_false() -> None:
    s = refresh_from_result(_result("456"))
    assert s["skipped"] is False
