from __future__ import annotations

from fastapi import FastAPI, HTTPException

from bluegrass.app.dashboard import get_dashboard_payload
from bluegrass.app.homepage import build_homepage_view, build_session_homepage_view
from bluegrass.app.playlist import build_session_playlist, build_session_stats
from bluegrass.app.session_cards import build_session_cards
from bluegrass.engine.intake import normalize_result
from bluegrass.research.baseline import baseline_packet_summary
from bluegrass.research.refresh import refresh_from_result

app = FastAPI(title="Bluegrass Baseline API", version="0.2.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/baseline/summary")
def baseline_summary() -> dict[str, object]:
    return baseline_packet_summary()


@app.get("/dashboard/homepage")
def dashboard_homepage() -> dict[str, object]:
    return get_dashboard_payload()


@app.get("/dashboard/homepage-view")
def dashboard_homepage_view() -> dict[str, object]:
    return build_homepage_view()


@app.get("/dashboard/session/{session}")
def dashboard_session(session: str) -> dict[str, object]:
    from fastapi import HTTPException

    try:
        return build_session_homepage_view(session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/dashboard/session/{session}/cards")
def dashboard_session_cards(session: str) -> dict[str, object]:
    try:
        return build_session_cards(session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Autonomy layer – stats, playlist, refresh
# ---------------------------------------------------------------------------

@app.get("/stats/session/{session}")
def stats_session(session: str) -> dict[str, object]:
    """All overdue-family boards for a session: sums, root_sums, pairs, combinations."""
    try:
        return build_session_stats(session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/playlist/session/{session}")
def playlist_session(session: str) -> dict[str, object]:
    """Daily narrowed shortlist for a session with why_flagged rationale."""
    try:
        return build_session_playlist(session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/refresh/run")
def refresh_run(payload: dict) -> dict[str, object]:
    """Ingest a raw engine result and incrementally update session stats.

    Required payload keys: date, session (or alias), result (or winning_number).
    """
    try:
        result = normalize_result(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return refresh_from_result(result)
