"""Tests for the audit builder layer."""

import pytest

from bluegrass.app.audit import build_audit_overview, build_session_audit
from bluegrass.engine.client import EngineClientError
from bluegrass.research.stats_store import reset_stats_state

_ENGINE_ROW = lambda date, session, result: {
    "date": date, "session": session, "result": result,
    "state": "GA", "game_type": "pick3",
}

_REQUIRED_SESSION_KEYS = {
    "session", "engine_latest_draw", "engine_latest_date",
    "bluegrass_last_processed_draw", "bluegrass_last_processed_date",
    "draws_behind", "freshness_status", "coverage",
    "processed_draw_count", "comparison_status", "gap_detected",
    "gap_reason", "generated_at",
}


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------

def test_session_audit_has_required_keys(monkeypatch):
    import bluegrass.app.audit as audit_mod
    monkeypatch.setattr(audit_mod, "fetch_latest_results",
                        lambda: [_ENGINE_ROW("2026-05-10", "Midday", "123")])
    result = build_session_audit("Midday")
    assert _REQUIRED_SESSION_KEYS.issubset(result.keys())


def test_audit_overview_has_required_keys(monkeypatch):
    import bluegrass.app.audit as audit_mod
    monkeypatch.setattr(audit_mod, "fetch_latest_results", lambda: [])
    ov = build_audit_overview()
    for key in ("sessions", "overall_status", "gap_sessions",
                "inconclusive_sessions", "engine_error", "generated_at"):
        assert key in ov


# ---------------------------------------------------------------------------
# Draw ID symmetry
# ---------------------------------------------------------------------------

def test_engine_draw_id_is_full_format(monkeypatch):
    import bluegrass.app.audit as audit_mod
    monkeypatch.setattr(audit_mod, "fetch_latest_results",
                        lambda: [_ENGINE_ROW("2026-05-10", "Night", "347")])
    result = build_session_audit("Night")
    assert result["engine_latest_draw"] == "2026-05-10:Night:347"
    assert result["engine_latest_date"] == "2026-05-10"


def test_engine_and_bluegrass_draw_ids_have_same_format(monkeypatch):
    import bluegrass.app.audit as audit_mod
    import bluegrass.research.refresh as ref_mod
    monkeypatch.setattr(audit_mod, "fetch_latest_results",
                        lambda: [_ENGINE_ROW("2026-05-10", "Midday", "123")])
    from bluegrass.research.refresh import refresh_from_result
    from bluegrass.engine.intake import normalize_result
    refresh_from_result(normalize_result(
        {"date": "2026-05-10", "session": "Midday", "result": "123"}
    ))
    result = build_session_audit("Midday")
    # Both should be "date:session:result" triples
    assert result["engine_latest_draw"].count(":") == 2
    assert result["bluegrass_last_processed_draw"].count(":") == 2


# ---------------------------------------------------------------------------
# comparison_status: matched
# ---------------------------------------------------------------------------

def test_matched_when_engine_and_bluegrass_agree(monkeypatch):
    import bluegrass.app.audit as audit_mod
    from bluegrass.research.refresh import refresh_from_result
    from bluegrass.engine.intake import normalize_result
    monkeypatch.setattr(audit_mod, "fetch_latest_results",
                        lambda: [_ENGINE_ROW("2026-05-10", "Evening", "456")])
    refresh_from_result(normalize_result(
        {"date": "2026-05-10", "session": "Evening", "result": "456"}
    ))
    result = build_session_audit("Evening")
    assert result["comparison_status"] == "matched"
    assert result["gap_detected"] is False
    assert result["draws_behind"] == 0
    assert result["gap_reason"] == "up_to_date"
    assert result["freshness_status"] == "fresh"


def test_matched_draws_behind_is_zero(monkeypatch):
    import bluegrass.app.audit as audit_mod
    from bluegrass.research.refresh import refresh_from_result
    from bluegrass.engine.intake import normalize_result
    monkeypatch.setattr(audit_mod, "fetch_latest_results",
                        lambda: [_ENGINE_ROW("2026-05-10", "Night", "789")])
    refresh_from_result(normalize_result(
        {"date": "2026-05-10", "session": "Night", "result": "789"}
    ))
    result = build_session_audit("Night")
    assert result["draws_behind"] == 0


# ---------------------------------------------------------------------------
# comparison_status: gap
# ---------------------------------------------------------------------------

def test_gap_when_engine_is_ahead(monkeypatch):
    import bluegrass.app.audit as audit_mod
    from bluegrass.research.refresh import refresh_from_result
    from bluegrass.engine.intake import normalize_result
    monkeypatch.setattr(audit_mod, "fetch_latest_results",
                        lambda: [_ENGINE_ROW("2026-05-10", "Night", "789")])
    refresh_from_result(normalize_result(
        {"date": "2026-05-09", "session": "Night", "result": "111"}
    ))
    result = build_session_audit("Night")
    assert result["comparison_status"] == "gap"
    assert result["gap_detected"] is True
    assert result["draws_behind"] == 1
    assert result["freshness_status"] == "stale"


def test_draws_behind_reflects_day_difference(monkeypatch):
    import bluegrass.app.audit as audit_mod
    from bluegrass.research.refresh import refresh_from_result
    from bluegrass.engine.intake import normalize_result
    monkeypatch.setattr(audit_mod, "fetch_latest_results",
                        lambda: [_ENGINE_ROW("2026-05-10", "Midday", "123")])
    refresh_from_result(normalize_result(
        {"date": "2026-05-07", "session": "Midday", "result": "555"}
    ))
    result = build_session_audit("Midday")
    assert result["draws_behind"] == 3


def test_gap_when_baseline_only(monkeypatch):
    import bluegrass.app.audit as audit_mod
    monkeypatch.setattr(audit_mod, "fetch_latest_results",
                        lambda: [_ENGINE_ROW("2026-05-10", "Night", "789")])
    result = build_session_audit("Night")
    assert result["comparison_status"] == "gap"
    assert result["gap_detected"] is True
    assert result["coverage"] == "baseline-only"
    assert result["gap_reason"] == "no_bluegrass_coverage"
    assert result["freshness_status"] == "baseline-only"


def test_gap_reason_includes_count(monkeypatch):
    import bluegrass.app.audit as audit_mod
    from bluegrass.research.refresh import refresh_from_result
    from bluegrass.engine.intake import normalize_result
    monkeypatch.setattr(audit_mod, "fetch_latest_results",
                        lambda: [_ENGINE_ROW("2026-05-10", "Evening", "456")])
    refresh_from_result(normalize_result(
        {"date": "2026-05-08", "session": "Evening", "result": "222"}
    ))
    result = build_session_audit("Evening")
    assert "2" in result["gap_reason"]


# ---------------------------------------------------------------------------
# comparison_status: inconclusive
# ---------------------------------------------------------------------------

def test_engine_unavailable_is_inconclusive(monkeypatch):
    import bluegrass.app.audit as audit_mod
    from bluegrass.research.refresh import refresh_from_result
    from bluegrass.engine.intake import normalize_result
    monkeypatch.setattr(audit_mod, "fetch_latest_results",
                        lambda: (_ for _ in ()).throw(EngineClientError("timeout")))
    refresh_from_result(normalize_result(
        {"date": "2026-05-10", "session": "Midday", "result": "123"}
    ))
    result = build_session_audit("Midday")
    assert result["comparison_status"] == "inconclusive"
    assert result["gap_detected"] is None
    assert result["freshness_status"] == "engine-unknown"


def test_no_engine_url_is_inconclusive(monkeypatch):
    import bluegrass.app.audit as audit_mod
    from bluegrass.research.refresh import refresh_from_result
    from bluegrass.engine.intake import normalize_result
    monkeypatch.delenv("LOTTERY_ENGINE_BASE_URL", raising=False)
    monkeypatch.setattr(audit_mod, "fetch_latest_results", lambda: [])
    refresh_from_result(normalize_result(
        {"date": "2026-05-10", "session": "Night", "result": "789"}
    ))
    result = build_session_audit("Night")
    assert result["comparison_status"] == "inconclusive"
    assert result["gap_detected"] is None


def test_session_not_in_engine_result_is_inconclusive(monkeypatch):
    import bluegrass.app.audit as audit_mod
    from bluegrass.research.refresh import refresh_from_result
    from bluegrass.engine.intake import normalize_result
    # Engine returns Midday only; we audit Night
    monkeypatch.setattr(audit_mod, "fetch_latest_results",
                        lambda: [_ENGINE_ROW("2026-05-10", "Midday", "123")])
    refresh_from_result(normalize_result(
        {"date": "2026-05-10", "session": "Night", "result": "789"}
    ))
    result = build_session_audit("Night")
    assert result["comparison_status"] == "inconclusive"
    assert result["gap_detected"] is None


# ---------------------------------------------------------------------------
# Invalid session
# ---------------------------------------------------------------------------

def test_invalid_session_raises(monkeypatch):
    import bluegrass.app.audit as audit_mod
    monkeypatch.setattr(audit_mod, "fetch_latest_results", lambda: [])
    with pytest.raises(ValueError):
        build_session_audit("Weekend")


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

def test_audit_overview_sessions_covers_all_three(monkeypatch):
    import bluegrass.app.audit as audit_mod
    monkeypatch.setattr(audit_mod, "fetch_latest_results", lambda: [])
    ov = build_audit_overview()
    assert set(ov["sessions"].keys()) == {"Midday", "Evening", "Night"}


def test_audit_overview_engine_called_once(monkeypatch):
    import bluegrass.app.audit as audit_mod
    calls = []
    def fake_fetch():
        calls.append(1)
        return []
    monkeypatch.setattr(audit_mod, "fetch_latest_results", fake_fetch)
    build_audit_overview()
    assert len(calls) == 1


def test_audit_overview_all_fresh_when_all_matched(monkeypatch):
    import bluegrass.app.audit as audit_mod
    from bluegrass.research.refresh import refresh_from_result
    from bluegrass.engine.intake import normalize_result
    rows = [
        _ENGINE_ROW("2026-05-10", "Midday", "123"),
        _ENGINE_ROW("2026-05-10", "Evening", "456"),
        _ENGINE_ROW("2026-05-10", "Night", "789"),
    ]
    monkeypatch.setattr(audit_mod, "fetch_latest_results", lambda: rows)
    for raw in rows:
        refresh_from_result(normalize_result(raw))
    ov = build_audit_overview()
    assert ov["overall_status"] == "fresh"
    assert ov["gap_sessions"] == []


def test_audit_overview_degraded_when_any_gap(monkeypatch):
    import bluegrass.app.audit as audit_mod
    from bluegrass.research.refresh import refresh_from_result
    from bluegrass.engine.intake import normalize_result
    rows = [_ENGINE_ROW("2026-05-10", "Midday", "123")]
    monkeypatch.setattr(audit_mod, "fetch_latest_results", lambda: rows)
    # Only Midday processed; Night and Evening are gaps
    refresh_from_result(normalize_result(
        {"date": "2026-05-10", "session": "Midday", "result": "123"}
    ))
    ov = build_audit_overview()
    assert ov["overall_status"] == "degraded"
    assert len(ov["gap_sessions"]) >= 1


def test_audit_overview_session_entries_have_full_shape(monkeypatch):
    import bluegrass.app.audit as audit_mod
    monkeypatch.setattr(audit_mod, "fetch_latest_results", lambda: [])
    ov = build_audit_overview()
    for session_audit in ov["sessions"].values():
        assert _REQUIRED_SESSION_KEYS.issubset(session_audit.keys())
