"""Catch-up sync — apply all unprocessed draws from the engine in chronological order.

Fetches the full rolling window (default 30 days), normalizes each row, and
applies it via refresh_from_result. The idempotency guard in refresh_from_result
skips draws already in processed_draw_ids, so this is safe to run repeatedly.
"""

from __future__ import annotations

from typing import Any

from bluegrass.engine.client import EngineClientError, fetch_all_draws
from bluegrass.engine.intake import normalize_result


def run_catchup(days: int = 30) -> dict[str, Any]:
    """Fetch up to `days` of draw history and apply any unprocessed draws.

    Returns {applied, skipped, errors} counts.
    """
    # Import here to avoid circular import at module level
    from bluegrass.research.refresh import refresh_from_result

    try:
        rows = fetch_all_draws(days)
    except EngineClientError as exc:
        return {"applied": 0, "skipped": 0, "errors": 1, "error_detail": str(exc)}

    applied = skipped = errors = 0
    for raw in rows:
        try:
            result = normalize_result(raw)
        except ValueError:
            errors += 1
            continue
        summary = refresh_from_result(result)
        if summary.get("skipped"):
            skipped += 1
        else:
            applied += 1

    return {"applied": applied, "skipped": skipped, "errors": errors}
