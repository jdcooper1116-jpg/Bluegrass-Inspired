"""Operator-facing HTML frontend shell.

Serves Jinja2 templates that consume board payloads directly (no HTTP hop).
Routes are mounted into the main FastAPI app in api.py.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from starlette.responses import Response

from bluegrass.app.audit import build_audit_overview, build_session_audit
from bluegrass.app.board import build_session_board
from bluegrass.app.classify import classify_digit_pattern, classify_pair, classify_play_type
from bluegrass.app.convergence import build_convergence_overview, build_session_convergence
from bluegrass.app.integrity import build_integrity_view
from bluegrass.app.ledger_view import build_ledger_overview, build_ledger_session
from bluegrass.app.overview import build_all_draws_overview
from bluegrass.app.play_builder import build_play_builder_overview, build_play_builder_session
from bluegrass.app.playlist import _VALID_SESSIONS
from bluegrass.engine.client import EngineClientError, fetch_latest_results
from bluegrass.engine.intake import normalize_result
from bluegrass.research.refresh import refresh_from_result

_SESSION_NORMALIZE: dict[str, str] = {s.lower(): s for s in _VALID_SESSIONS}

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()

AUTO_REFRESH_SECONDS: int = 60


def _page_context() -> dict[str, Any]:
    """Common template context injected into every page render.

    refresh_ts  — server-rendered HH:MM UTC timestamp shown in the refresh bar.
    auto_refresh_seconds — interval passed to the JS timer in both base templates.
    """
    now = datetime.now(timezone.utc)
    return {
        "refresh_ts": now.strftime("%H:%M UTC"),
        "auto_refresh_seconds": AUTO_REFRESH_SECONDS,
    }


def _enrich_pair_card(card: dict[str, Any]) -> dict[str, Any]:
    c = dict(card)
    pair_cls = classify_pair(card.get("subtype"))
    c["pair_position"] = pair_cls["position"]
    c["play_type_label"] = pair_cls["play_type"]
    return c


def _enrich_combo_card(card: dict[str, Any]) -> dict[str, Any]:
    c = dict(card)
    c["digit_pattern"] = classify_digit_pattern(str(card.get("value", "")))
    c["play_type_label"] = classify_play_type(card.get("subtype"))
    return c


def _enrich_shortlist_entry(entry: dict[str, Any]) -> dict[str, Any]:
    c = dict(entry)
    family = entry.get("family", "")
    if family == "combination":
        c["digit_pattern"] = classify_digit_pattern(str(entry.get("value", "")))
        c["play_type_label"] = classify_play_type(entry.get("subtype"))
    elif family == "pair":
        pair_cls = classify_pair(entry.get("subtype"))
        c["pair_position"] = pair_cls["position"]
        c["play_type_label"] = pair_cls["play_type"]
    return c


def _group_pairs_by_position(
    pairs: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in pairs:
        groups[card.get("pair_position", "unknown")].append(card)
    order = ["front", "back", "split", "unknown"]
    return [(pos, groups[pos]) for pos in order if pos in groups]


def _run_sync() -> dict[str, int]:
    processed = skipped = errors = 0
    try:
        raw_rows = fetch_latest_results()
    except EngineClientError:
        return {"processed": 0, "skipped": 0, "errors": 1}
    for raw in raw_rows:
        try:
            result = normalize_result(raw)
        except ValueError:
            errors += 1
            continue
        summary = refresh_from_result(result)
        if summary.get("skipped"):
            skipped += 1
        else:
            processed += 1
    return {"processed": processed, "skipped": skipped, "errors": errors}


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def ui_overview(
    request: Request,
    synced: int = 0,
    processed: int = 0,
    skipped: int = 0,
    errors: int = 0,
) -> Response:
    board = build_all_draws_overview()
    audit = build_audit_overview()
    enriched_shortlist = [_enrich_shortlist_entry(e) for e in board.get("consensus_shortlist", [])]
    sync_result = {"processed": processed, "skipped": skipped, "errors": errors} if synced else None
    return templates.TemplateResponse(request, "overview.html", {
        **_page_context(),
        "board": board,
        "audit": audit,
        "enriched_shortlist": enriched_shortlist,
        "sync_result": sync_result,
        "active": "overview",
    })


@router.get("/session/{session}", response_class=HTMLResponse, include_in_schema=False)
def ui_session(
    session: str,
    request: Request,
    synced: int = 0,
    processed: int = 0,
    skipped: int = 0,
    errors: int = 0,
) -> Response:
    normalized = _SESSION_NORMALIZE.get(session.lower())
    if normalized and normalized != session:
        return RedirectResponse(url=f"/session/{normalized}", status_code=301)
    if session not in _VALID_SESSIONS:
        return templates.TemplateResponse(
            request, "404.html",
            {"active": None,
             "detail": f"Session {session!r} not found. Valid: Midday, Evening, Night."},
            status_code=404,
        )
    board = build_session_board(session)
    audit = build_session_audit(session)
    enriched_pairs    = [_enrich_pair_card(c) for c in board.get("top_pairs", [])]
    enriched_combos   = [_enrich_combo_card(c) for c in board.get("top_combinations", [])]
    pairs_by_position = _group_pairs_by_position(enriched_pairs)
    enriched_shortlist = [_enrich_shortlist_entry(e) for e in board.get("shortlist", [])]
    sync_result = {"processed": processed, "skipped": skipped, "errors": errors} if synced else None
    return templates.TemplateResponse(request, "session.html", {
        **_page_context(),
        "board": board,
        "audit": audit,
        "enriched_pairs": enriched_pairs,
        "enriched_combos": enriched_combos,
        "pairs_by_position": pairs_by_position,
        "enriched_shortlist": enriched_shortlist,
        "sync_result": sync_result,
        "session": session,
        "active": session,
    })


@router.get("/plays", response_class=HTMLResponse, include_in_schema=False)
def pb_overview(
    request: Request,
    synced: int = 0,
    processed: int = 0,
    skipped: int = 0,
    errors: int = 0,
) -> Response:
    vm = build_play_builder_overview()
    audit = build_audit_overview()
    sync_result = {"processed": processed, "skipped": skipped, "errors": errors} if synced else None
    return templates.TemplateResponse(request, "pb_overview.html", {
        **_page_context(),
        "vm": vm,
        "audit": audit,
        "sync_result": sync_result,
        "active": "overview",
    })


@router.get("/plays/session/{session}", response_class=HTMLResponse, include_in_schema=False)
def pb_session(
    session: str,
    request: Request,
    synced: int = 0,
    processed: int = 0,
    skipped: int = 0,
    errors: int = 0,
) -> Response:
    normalized = _SESSION_NORMALIZE.get(session.lower())
    if normalized and normalized != session:
        return RedirectResponse(url=f"/plays/session/{normalized}", status_code=301)
    if session not in _VALID_SESSIONS:
        return templates.TemplateResponse(
            request, "404.html",
            {"active": None,
             "detail": f"Session {session!r} not found. Valid: Midday, Evening, Night."},
            status_code=404,
        )
    vm = build_play_builder_session(session)
    sync_result = {"processed": processed, "skipped": skipped, "errors": errors} if synced else None
    return templates.TemplateResponse(request, "pb_session.html", {
        **_page_context(),
        "vm": vm,
        "sync_result": sync_result,
        "active": session,
    })


@router.get("/convergence/overview", response_class=HTMLResponse, include_in_schema=False)
def convergence_overview(
    request: Request,
    synced: int = 0,
    processed: int = 0,
    skipped: int = 0,
    errors: int = 0,
) -> Response:
    vm = build_convergence_overview()
    sync_result = {"processed": processed, "skipped": skipped, "errors": errors} if synced else None
    return templates.TemplateResponse(request, "convergence_overview.html", {
        **_page_context(),
        "vm": vm,
        "sync_result": sync_result,
        "active": "convergence",
    })


@router.get("/convergence/session/{session}", response_class=HTMLResponse, include_in_schema=False)
def convergence_session(
    session: str,
    request: Request,
    synced: int = 0,
    processed: int = 0,
    skipped: int = 0,
    errors: int = 0,
) -> Response:
    normalized = _SESSION_NORMALIZE.get(session.lower())
    if normalized and normalized != session:
        return RedirectResponse(url=f"/convergence/session/{normalized}", status_code=301)
    if session not in _VALID_SESSIONS:
        return templates.TemplateResponse(
            request, "404.html",
            {"active": None,
             "detail": f"Session {session!r} not found. Valid: Midday, Evening, Night."},
            status_code=404,
        )
    vm = build_session_convergence(session)
    sync_result = {"processed": processed, "skipped": skipped, "errors": errors} if synced else None
    return templates.TemplateResponse(request, "convergence_session.html", {
        **_page_context(),
        "vm": vm,
        "sync_result": sync_result,
        "session": session,
        "active": session,
    })


@router.get("/integrity", response_class=HTMLResponse, include_in_schema=False)
def ui_integrity(
    request: Request,
    synced: int = 0,
    processed: int = 0,
    skipped: int = 0,
    errors: int = 0,
) -> Response:
    vm = build_integrity_view()
    sync_result = {"processed": processed, "skipped": skipped, "errors": errors} if synced else None
    return templates.TemplateResponse(request, "integrity.html", {
        **_page_context(),
        "vm": vm,
        "sync_result": sync_result,
        "active": "integrity",
    })


@router.get("/ledger", response_class=HTMLResponse, include_in_schema=False)
def ui_ledger_overview(request: Request) -> Response:
    """Forecast ledger overview: reliability metrics across all sessions."""
    vm = build_ledger_overview()
    return templates.TemplateResponse(request, "ledger_overview.html", {
        **_page_context(),
        "vm": vm,
        "active": "ledger",
    })


@router.get("/ledger/session/{session}", response_class=HTMLResponse, include_in_schema=False)
def ui_ledger_session(session: str, request: Request) -> Response:
    """Forecast ledger for a single session."""
    normalized = _SESSION_NORMALIZE.get(session.lower())
    if normalized and normalized != session:
        return RedirectResponse(url=f"/ledger/session/{normalized}", status_code=301)
    if session not in _VALID_SESSIONS:
        return templates.TemplateResponse(
            request, "404.html",
            {"active": None,
             "detail": f"Session {session!r} not found. Valid: Midday, Evening, Night."},
            status_code=404,
        )
    vm = build_ledger_session(session)
    return templates.TemplateResponse(request, "ledger_session.html", {
        **_page_context(),
        "vm": vm,
        "active": "ledger",
    })


@router.post("/refresh", include_in_schema=False)
def ui_refresh(next: str = Query(default="/")) -> Response:
    if not next.startswith("/"):
        next = "/"
    from bluegrass.app.forecast_orchestrator import run_catchup_with_ledger
    counts = run_catchup_with_ledger()
    p, s, e = counts["applied"], counts["skipped"], counts["errors"]
    return RedirectResponse(
        url=f"{next}?synced=1&processed={p}&skipped={s}&errors={e}",
        status_code=303,
    )

