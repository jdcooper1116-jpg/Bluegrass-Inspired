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
from bluegrass.research.refresh import refresh_from_result

_log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """On startup: apply any missing draws, then start the background scheduler."""
    try:
        from bluegrass.research.catchup import run_catchup
        result = run_catchup()
        _log.info(
            "startup catch-up: applied=%d skipped=%d errors=%d",
            result["applied"], result["skipped"], result["errors"],
        )
    except Exception:
        _log.exception("startup catch-up failed")

    try:
        from bluegrass.research.scheduler import start_scheduler
        start_scheduler()
    except Exception:
        _log.exception("scheduler start failed")

    yield  # app runs


app = FastAPI(title="Bluegrass Baseline API", version="0.2.0", lifespan=_lifespan)

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
    """Fetch all draws from the rolling 30-day window and apply any new ones.

    Uses the full catch-up path (not just latest per session) so gaps during
    downtime are filled. Skips draws already processed (idempotent).
    """
    from bluegrass.research.catchup import run_catchup
    result = run_catchup()
    return {
        "processed_count": result["applied"],
        "skipped_count": result["skipped"],
        "error_count": result["errors"],
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
