"""Operator-facing HTML frontend shell.

Serves Jinja2 templates that consume board payloads directly (no HTTP hop).
Routes are mounted into the main FastAPI app in api.py.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from starlette.responses import Response

from bluegrass.app.board import build_session_board
from bluegrass.app.overview import build_all_draws_overview
from bluegrass.app.playlist import _VALID_SESSIONS

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def ui_overview(request: Request) -> Response:
    board = build_all_draws_overview()
    return templates.TemplateResponse(
        request, "overview.html", {"board": board, "active": "overview"},
    )


@router.get("/session/{session}", response_class=HTMLResponse, include_in_schema=False)
def ui_session(session: str, request: Request) -> Response:
    if session not in _VALID_SESSIONS:
        return templates.TemplateResponse(
            request,
            "404.html",
            {
                "active": None,
                "detail": f"Session {session!r} not found. Valid sessions: Midday, Evening, Night.",
            },
            status_code=404,
        )
    board = build_session_board(session)
    return templates.TemplateResponse(
        request, "session.html", {"board": board, "session": session, "active": session},
    )
