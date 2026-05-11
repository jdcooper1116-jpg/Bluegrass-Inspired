from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

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
from bluegrass.research.config import ANALYSIS_WINDOW_DAYS, SYNC_WINDOW_DAYS
from bluegrass.research.refresh import refresh_from_result

_log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """On startup: run the 250-day analysis bootstrap, ensure today's forecast
    snapshots exist, then start the background scheduler.

    The analysis bootstrap (ANALYSIS_WINDOW_DAYS) ensures overdue boards have
    enough verified draw history for meaningful draws_since values.

    ensure_todays_snapshots() writes the current Play Builder state for each
    session to the ledger so results can be scored when they arrive.

    Both operations are idempotent — safe to run on every startup.
    The scheduler uses SYNC_WINDOW_DAYS (30) for ongoing catch-up.
    """
    try:
        from bluegrass.research.catchup import run_analysis_bootstrap
        result = run_analysis_bootstrap()
        _log.info(
            "startup analysis bootstrap (%dd): applied=%d skipped=%d errors=%d",
            ANALYSIS_WINDOW_DAYS,
            result["applied"], result["skipped"], result["errors"],
        )
    except Exception:
        _log.exception("startup analysis bootstrap failed")

    try:
        from bluegrass.app.forecast_orchestrator import ensure_todays_snapshots
        snap = ensure_todays_snapshots()
        _log.info(
            "startup snapshots: created=%s skipped=%s errors=%s",
            snap["created"], snap["skipped"], snap["errors"],
        )
    except Exception:
        _log.exception("startup snapshot creation failed")

    try:
        from bluegrass.research.scheduler import start_scheduler
        start_scheduler()
    except Exception:
        _log.exception("scheduler start failed")

    yield  # app runs


app = FastAPI(title="Bluegrass Baseline API", version="0.3.0", lifespan=_lifespan)

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
    """Fetch the rolling {sync_window}-day window, apply new draws, and score forecasts.

    Operational sync — uses SYNC_WINDOW_DAYS ({sync_window}).
    Also ensures today's forecast snapshots exist and scores any applied results.
    For a full analysis re-bootstrap use /refresh/analysis-bootstrap instead.
    Skips draws already processed (idempotent).
    """.format(sync_window=SYNC_WINDOW_DAYS)
    from bluegrass.app.forecast_orchestrator import run_catchup_with_ledger
    result = run_catchup_with_ledger()
    return {
        "processed_count": result["applied"],
        "skipped_count": result["skipped"],
        "error_count": result["errors"],
        "sync_window_days": SYNC_WINDOW_DAYS,
        "snapshots_created": result.get("snapshots_created", 0),
        "scored": result.get("scored", 0),
    }


@app.post("/refresh/analysis-bootstrap")
def refresh_analysis_bootstrap() -> dict[str, object]:
    """Re-run the {window}-day deep analysis bootstrap. Idempotent.

    Use this after a long outage, fresh install, or any time overdue boards
    look stale. Fetches {window} days of draw history from the engine and
    applies any draws not yet in stats_state.json.

    The scheduler's {sync}-day rolling sync continues as normal after this.
    """.format(window=ANALYSIS_WINDOW_DAYS, sync=SYNC_WINDOW_DAYS)
    from bluegrass.research.catchup import run_analysis_bootstrap
    result = run_analysis_bootstrap()
    return {
        "processed_count": result["applied"],
        "skipped_count": result["skipped"],
        "error_count": result["errors"],
        "analysis_window_days": ANALYSIS_WINDOW_DAYS,
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
