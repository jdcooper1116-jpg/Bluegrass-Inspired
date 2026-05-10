from __future__ import annotations

from fastapi import FastAPI

from bluegrass.app.dashboard import get_dashboard_payload
from bluegrass.app.homepage import build_homepage_view, build_session_homepage_view
from bluegrass.app.session_cards import build_session_cards
from bluegrass.research.baseline import baseline_packet_summary

app = FastAPI(title="Bluegrass Baseline API", version="0.1.0")


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
    from fastapi import HTTPException

    try:
        return build_session_cards(session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
