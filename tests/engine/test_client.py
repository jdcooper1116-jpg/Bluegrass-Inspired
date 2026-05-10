"""Tests for the lottery engine sync client."""

import pytest

from bluegrass.engine.client import EngineClientError, fetch_latest_results


# ---------------------------------------------------------------------------
# Helpers – build engine-shaped response rows
# ---------------------------------------------------------------------------

def _engine_row(date: str, draw_time: str, winning_number: str, state: str = "GA") -> dict:
    """Mimics a real engine /draws response row."""
    return {
        "draw_date": date,
        "draw_time": draw_time,
        "winning_number": winning_number,
        "state": state,
        "game_type": "pick3",
    }


def _three_sessions(date: str = "2026-05-10") -> list[dict]:
    return [
        _engine_row(date, "midday", "123"),
        _engine_row(date, "evening", "456"),
        _engine_row(date, "night", "789"),
    ]


# ---------------------------------------------------------------------------
# URL shape
# ---------------------------------------------------------------------------

def test_uses_draws_route(monkeypatch):
    """Client must call /draws, not /results/latest."""
    seen_urls: list[str] = []

    def capture(url: str):
        seen_urls.append(url)
        return _three_sessions()

    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", capture)
    fetch_latest_results()
    assert seen_urls, "no URL was called"
    assert "/draws" in seen_urls[0], f"unexpected route: {seen_urls[0]}"
    assert "/results/latest" not in seen_urls[0]


def test_query_params_present(monkeypatch):
    seen_urls: list[str] = []

    def capture(url: str):
        seen_urls.append(url)
        return _three_sessions()

    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", capture)
    fetch_latest_results()
    url = seen_urls[0]
    assert "state=GA" in url
    assert "game_type=pick3" in url
    assert "draw_times=" in url
    assert "midday" in url
    assert "start=" in url
    assert "end=" in url


def test_draw_times_commas_not_percent_encoded(monkeypatch):
    """Engine requires raw commas; %2C causes 403."""
    seen_urls: list[str] = []

    def capture(url: str):
        seen_urls.append(url)
        return _three_sessions()

    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", capture)
    fetch_latest_results()
    assert "%2C" not in seen_urls[0], "commas must not be percent-encoded in draw_times"
    assert "midday,evening,night" in seen_urls[0]


# ---------------------------------------------------------------------------
# draw_time → session mapping
# ---------------------------------------------------------------------------

def test_draw_time_mapped_to_session(monkeypatch):
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: _three_sessions())
    results = fetch_latest_results()
    sessions = {r["session"] for r in results}
    assert sessions == {"Midday", "Evening", "Night"}


def test_draw_time_values_not_leaked(monkeypatch):
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: _three_sessions())
    results = fetch_latest_results()
    for r in results:
        assert "draw_time" not in r
        assert r["session"] in {"Midday", "Evening", "Night"}


# ---------------------------------------------------------------------------
# Latest-row-per-session selection
# ---------------------------------------------------------------------------

def test_returns_latest_row_per_session(monkeypatch):
    rows = [
        _engine_row("2026-05-08", "midday", "111"),
        _engine_row("2026-05-10", "midday", "999"),  # latest – should win
        _engine_row("2026-05-09", "midday", "555"),
    ]
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: rows)
    results = fetch_latest_results(session="Midday")
    assert len(results) == 1
    assert results[0]["result"] == "999"


def test_one_result_per_session_returned(monkeypatch):
    rows = _three_sessions("2026-05-09") + _three_sessions("2026-05-10")
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: rows)
    results = fetch_latest_results()
    assert len(results) == 3


# ---------------------------------------------------------------------------
# Leading zeros
# ---------------------------------------------------------------------------

def test_leading_zeros_preserved(monkeypatch):
    rows = [_engine_row("2026-05-10", "night", "007")]
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: rows)
    results = fetch_latest_results(session="Night")
    assert results[0]["result"] == "007"


def test_single_digit_padded(monkeypatch):
    rows = [_engine_row("2026-05-10", "midday", "5")]
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: rows)
    results = fetch_latest_results(session="Midday")
    assert results[0]["result"] == "005"


# ---------------------------------------------------------------------------
# Window retry
# ---------------------------------------------------------------------------

def test_widens_window_when_sessions_missing(monkeypatch):
    call_count = [0]

    def fake(url: str):
        call_count[0] += 1
        if call_count[0] == 1:
            # 7-day window: only midday
            return [_engine_row("2026-05-10", "midday", "123")]
        # 14-day window: all three
        return _three_sessions()

    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", fake)
    results = fetch_latest_results()
    assert call_count[0] == 2
    assert len(results) == 3


def test_stops_widening_once_all_sessions_found(monkeypatch):
    call_count = [0]

    def fake(url: str):
        call_count[0] += 1
        return _three_sessions()

    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", fake)
    fetch_latest_results()
    assert call_count[0] == 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_no_base_url_returns_empty(monkeypatch):
    monkeypatch.delenv("LOTTERY_ENGINE_BASE_URL", raising=False)
    results = fetch_latest_results()
    assert results == []


def test_http_error_raises_engine_client_error(monkeypatch):
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json",
                        lambda url: (_ for _ in ()).throw(OSError("refused")))
    with pytest.raises(EngineClientError, match="refused"):
        fetch_latest_results()


def test_envelope_response_unwrapped(monkeypatch):
    """Real engine wraps rows in {"draws": [...], "total_count": N, ...}."""
    envelope = {
        "state": "GA",
        "game_type": "pick3",
        "start_date": "2026-05-03",
        "end_date": "2026-05-10",
        "total_count": 3,
        "draws": _three_sessions("2026-05-10"),
    }
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: envelope)
    results = fetch_latest_results()
    assert len(results) == 3
    sessions = {r["session"] for r in results}
    assert sessions == {"Midday", "Evening", "Night"}


def test_non_list_response_raises_engine_client_error(monkeypatch):
    """A dict without a 'draws' key is unrecognized — raise clearly."""
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: {"error": "bad"})
    with pytest.raises(EngineClientError, match="expected list"):
        fetch_latest_results()


def test_missing_draw_time_row_skipped(monkeypatch):
    rows = [
        _engine_row("2026-05-10", "midday", "123"),
        {"draw_date": "2026-05-10", "winning_number": "456"},  # no draw_time
        _engine_row("2026-05-10", "night", "789"),
    ]
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: rows)
    results = fetch_latest_results()
    sessions = {r["session"] for r in results}
    assert "Midday" in sessions
    assert "Night" in sessions
    assert len(results) == 2


def test_session_filter_respected(monkeypatch):
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: _three_sessions())
    results = fetch_latest_results(session="Evening")
    assert len(results) == 1
    assert results[0]["session"] == "Evening"
