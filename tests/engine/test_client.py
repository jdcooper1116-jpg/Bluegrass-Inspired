"""Tests for the lottery engine sync client."""

import pytest

from bluegrass.engine.client import fetch_latest_results


def _make_raw(date: str, session: str, result: str) -> dict:
    return {"date": date, "session": session, "result": result, "state": "GA"}


def test_fetch_returns_list_from_mock(monkeypatch):
    raw = [_make_raw("2026-05-10", "Midday", "123")]
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://fake-engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: raw)
    results = fetch_latest_results()
    assert isinstance(results, list)
    assert len(results) == 1


def test_fetch_filters_by_session(monkeypatch):
    raw = [
        _make_raw("2026-05-10", "Midday", "123"),
        _make_raw("2026-05-10", "Evening", "456"),
    ]
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://fake-engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: raw)
    results = fetch_latest_results(session="Midday")
    assert all(r.get("session") == "Midday" for r in results)
    assert len(results) == 1


def test_fetch_returns_empty_when_no_base_url(monkeypatch):
    monkeypatch.delenv("LOTTERY_ENGINE_BASE_URL", raising=False)
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: (_ for _ in ()).throw(RuntimeError("should not call")))
    results = fetch_latest_results()
    assert results == []


def test_fetch_returns_empty_on_http_error(monkeypatch, capsys):
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://fake-engine")

    def boom(url):
        raise OSError("connection refused")

    monkeypatch.setattr("bluegrass.engine.client._http_get_json", boom)
    results = fetch_latest_results()
    assert results == []


def test_fetch_handles_list_response(monkeypatch):
    raw = [
        _make_raw("2026-05-10", "Night", "007"),
        _make_raw("2026-05-10", "Night", "999"),
    ]
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://fake-engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: raw)
    results = fetch_latest_results(session="Night")
    assert len(results) == 2
    assert results[0]["result"] == "007"


def test_fetch_wraps_single_dict_in_list(monkeypatch):
    raw = _make_raw("2026-05-10", "Midday", "321")
    monkeypatch.setenv("LOTTERY_ENGINE_BASE_URL", "http://fake-engine")
    monkeypatch.setattr("bluegrass.engine.client._http_get_json", lambda url: raw)
    results = fetch_latest_results()
    assert isinstance(results, list)
    assert results[0]["result"] == "321"
