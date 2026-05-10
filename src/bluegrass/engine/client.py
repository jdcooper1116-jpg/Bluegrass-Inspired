"""Lottery engine sync client.

Reads LOTTERY_ENGINE_BASE_URL from the environment. Returns an empty list
when the variable is unset so callers are always safe. The internal
_http_get_json function is monkeypatchable in tests.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.request import urlopen


def _http_get_json(url: str) -> Any:
    with urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode())


def fetch_latest_results(session: str | None = None) -> list[dict[str, Any]]:
    """Fetch latest GA Pick 3 draw results from the engine API.

    Returns raw dicts suitable for normalize_result. Returns [] when
    LOTTERY_ENGINE_BASE_URL is not set or the request fails.
    """
    base_url = os.environ.get("LOTTERY_ENGINE_BASE_URL", "").rstrip("/")
    if not base_url:
        return []

    url = f"{base_url}/results/latest"
    try:
        data = _http_get_json(url)
    except Exception:
        return []

    rows: list[dict[str, Any]] = data if isinstance(data, list) else [data]

    if session is not None:
        rows = [r for r in rows if r.get("session") == session]

    return rows
