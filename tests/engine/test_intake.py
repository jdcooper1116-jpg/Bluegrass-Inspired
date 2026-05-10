import pytest

from bluegrass.engine.intake import EngineResult, normalize_result


def test_canonical_keys() -> None:
    r = normalize_result({"date": "2026-05-10", "session": "Midday", "result": "012"})
    assert r == EngineResult(date="2026-05-10", session="Midday", result="012",
                             jurisdiction="GA", game_family="Pick 3")


def test_alias_keys() -> None:
    r = normalize_result({
        "draw_date": "2026-05-10T20:00:00Z",
        "draw_session": "evening",
        "winning_number": "789",
        "state": "GA",
    })
    assert r.session == "Evening"
    assert r.result == "789"
    assert r.date == "2026-05-10"


def test_leading_zeros_preserved() -> None:
    r = normalize_result({"date": "2026-05-10", "session": "Night", "result": "007"})
    assert r.result == "007"
    assert len(r.result) == 3


def test_single_digit_padded() -> None:
    r = normalize_result({"date": "2026-05-10", "session": "Midday", "result": "5"})
    assert r.result == "005"


def test_session_alias_mid() -> None:
    r = normalize_result({"date": "2026-05-10", "session": "mid", "result": "123"})
    assert r.session == "Midday"


def test_session_alias_ngt() -> None:
    r = normalize_result({"date": "2026-05-10", "session": "ngt", "result": "456"})
    assert r.session == "Night"


def test_session_alias_eve() -> None:
    r = normalize_result({"date": "2026-05-10", "session": "eve", "result": "789"})
    assert r.session == "Evening"


def test_missing_date_raises() -> None:
    with pytest.raises(ValueError, match="date"):
        normalize_result({"session": "Midday", "result": "123"})


def test_bad_session_raises() -> None:
    with pytest.raises(ValueError, match="session"):
        normalize_result({"date": "2026-05-10", "session": "Noon", "result": "123"})


def test_missing_result_raises() -> None:
    with pytest.raises(ValueError, match="result"):
        normalize_result({"date": "2026-05-10", "session": "Midday", "result": ""})


def test_jurisdiction_override() -> None:
    r = normalize_result({"date": "2026-05-10", "session": "Night", "result": "111",
                          "jurisdiction": "FL"})
    assert r.jurisdiction == "FL"
