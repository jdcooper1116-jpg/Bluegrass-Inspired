from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from bluegrass.app.audit import build_audit_overview, build_session_audit
from bluegrass.app.board import build_session_board
from bluegrass.app.overview import build_all_draws_overview
from bluegrass.app.dashboard import get_dashboard_payload
from bluegrass.app.homepage import build_homepage_view, build_session_homepage_view
from bluegrass.app.playlist import build_session_playlist, build_session_stats
from bluegrass.app.session_cards import build_session_cards
from bluegrass.engine.client import EngineClientError, fetch_latest_results
from bluegrass.engine.intake import normalize_result
from bluegrass.frontend import router as frontend_router
from bluegrass.research.baseline import baseline_packet_summary
from bluegrass.research.refresh import refresh_from_result

app = FastAPI(title="Bluegrass Baseline API", version="0.2.0")

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
app.include_router(frontend_router)


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
# Daily board
# ---------------------------------------------------------------------------

@app.get("/board/overview")
def board_overview() -> dict[str, object]:
    """Cross-session all-draws board: aggregated signal across Midday, Evening, Night."""
    return build_all_draws_overview()


@app.get("/board/session/{session}")
def board_session(session: str) -> dict[str, object]:
    """Compact daily narrowing board for a session: top overdue families + shortlist + rationale."""
    try:
        return build_session_board(session)
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


@app.post("/refresh/sync-latest")
def refresh_sync_latest() -> dict[str, object]:
    """Fetch latest results from the engine and apply any new draws.

    Skips draws already processed (idempotent). Returns processed/skipped/errors.
    """
    try:
        raw_rows = fetch_latest_results()
    except EngineClientError as exc:
        return {
            "processed": [],
            "skipped": [],
            "errors": [{"error": str(exc)}],
            "processed_count": 0,
            "skipped_count": 0,
            "error_count": 1,
        }

    processed: list[dict] = []
    skipped: list[dict] = []
    errors: list[dict] = []

    for raw in raw_rows:
        try:
            result = normalize_result(raw)
        except ValueError as exc:
            errors.append({"raw": raw, "error": str(exc)})
            continue

        summary = refresh_from_result(result)
        entry = {"session": result.session, "date": result.date, "result": result.result}
        if summary.get("skipped"):
            skipped.append(entry)
        else:
            processed.append(entry)

    return {
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "processed_count": len(processed),
        "skipped_count": len(skipped),
        "error_count": len(errors),
    }


# ---------------------------------------------------------------------------
# Audit — data fidelity cross-check against engine
# ---------------------------------------------------------------------------

@app.get("/audit/session/{session}")
def audit_session(session: str) -> dict[str, object]:
    """Compare Bluegrass processed state against engine freshness for one session."""
    try:
        return build_session_audit(session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/audit/overview")
def audit_overview() -> dict[str, object]:
    """Aggregate audit across all three sessions with a single engine call."""
    return build_audit_overview()
