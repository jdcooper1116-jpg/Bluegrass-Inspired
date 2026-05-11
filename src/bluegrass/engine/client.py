"""Lottery engine sync client.

Calls GET /draws on the engine API with a rolling date window.
Reads LOTTERY_ENGINE_BASE_URL from the environment.

Returns [] when the env var is absent (no engine configured).
Raises EngineClientError on network failures or unexpected response shapes.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

_DRAW_TIME_TO_SESSION: dict[str, str] = {
    "midday": "Midday",
    "evening": "Evening",
    "night": "Night",
}
_ALL_SESSIONS = frozenset(_DRAW_TIME_TO_SESSION.values())
_WINDOWS = (7, 14, 30)
_SESSION_ORDER: dict[str, int] = {"Midday": 0, "Evening": 1, "Night": 2}


class EngineClientError(Exception):
    """Raised when the engine API call fails or returns an unexpected shape."""


def _http_get_json(url: str) -> Any:
    with urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _build_url(base_url: str, start: date, end: date) -> str:
    # draw_times must use raw commas — urlencode would produce %2C which the engine rejects
    base_params = urlencode({
        "state": "GA",
        "game_type": "pick3",
        "start": start.isoformat(),
        "end": end.isoformat(),
    })
    return f"{base_url}/draws?{base_params}&draw_times=midday,evening,night"


def _parse_rows(data: Any) -> list[dict[str, Any]]:
    """Extract and normalize rows from an engine /draws response.

    Accepts either a bare list or the engine envelope {"draws": [...], ...}.
    Raises EngineClientError on unrecognized shapes.
    Rows missing draw_time or winning_number are silently skipped.
    """
    if isinstance(data, dict):
        if "draws" not in data:
            raise EngineClientError(
                f"expected list from engine /draws, got dict without 'draws' key"
            )
        data = data["draws"]
    if not isinstance(data, list):
        raise EngineClientError(
            f"expected list from engine /draws, got {type(data).__name__}"
        )

    out: list[dict[str, Any]] = []
    for row in data:
        draw_time = str(row.get("draw_time") or "").lower()
        session = _DRAW_TIME_TO_SESSION.get(draw_time)
        if session is None:
            continue

        draw_date = str(row.get("draw_date") or row.get("date") or "")
        if not draw_date:
            continue

        raw_num = str(row.get("winning_number") or row.get("result") or "")
        digits = "".join(c for c in raw_num if c.isdigit())
        if not digits:
            continue
        result = digits.zfill(3)[:3]

        out.append({
            "date": draw_date[:10],
            "session": session,
            "result": result,
            "state": str(row.get("state") or "GA"),
            "game_type": str(row.get("game_type") or "pick3"),
        })

    return out


def _latest_per_session(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the most-recent row for each session (by draw date)."""
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        sess = row["session"]
        if sess not in best or row["date"] > best[sess]["date"]:
            best[sess] = row
    return list(best.values())


def _fetch_window(base_url: str, days: int) -> list[dict[str, Any]]:
    today = date.today()
    url = _build_url(base_url, today - timedelta(days=days), today)
    try:
        data = _http_get_json(url)
    except Exception as exc:
        raise EngineClientError(str(exc)) from exc
    return _parse_rows(data)


def fetch_all_draws(days: int = 30) -> list[dict[str, Any]]:
    """Return every draw in the rolling window, all sessions, sorted chronologically.

    Same-day draws are ordered Midday → Evening → Night (draw time order),
    not alphabetically by session name.
    Returns [] when LOTTERY_ENGINE_BASE_URL is not set.
    """
    base_url = os.environ.get("LOTTERY_ENGINE_BASE_URL", "").rstrip("/")
    if not base_url:
        return []
    rows = _fetch_window(base_url, days)
    return sorted(rows, key=lambda r: (r["date"], _SESSION_ORDER.get(r["session"], 99)))


def fetch_latest_results(session: str | None = None) -> list[dict[str, Any]]:
    """Return the latest draw result per session from the engine API.

    Uses a rolling window starting at 7 days. Widens to 14 then 30 days if
    any session is missing from the response.

    Returns [] when LOTTERY_ENGINE_BASE_URL is not set.
    Raises EngineClientError on network failures or bad response shapes.
    """
    base_url = os.environ.get("LOTTERY_ENGINE_BASE_URL", "").rstrip("/")
    if not base_url:
        return []

    rows: list[dict[str, Any]] = []
    for days in _WINDOWS:
        rows = _fetch_window(base_url, days)
        latest = _latest_per_session(rows)
        if {r["session"] for r in latest} >= _ALL_SESSIONS:
            break
        rows = latest  # carry forward what we have before widening

    latest = _latest_per_session(rows)

    if session is not None:
        latest = [r for r in latest if r["session"] == session]

    return latest
