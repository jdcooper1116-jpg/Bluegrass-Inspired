"""Incremental stat refresh – update runtime state when a new draw result arrives.

Only the session that received the draw is touched. The baseline seed CSVs are
never mutated. Sums and root-sums draws_since counters age by 1 on each new
draw; the hit value resets to 0.
"""

from __future__ import annotations

from typing import Any

from bluegrass.engine.intake import EngineResult
from bluegrass.research.stats_store import load_stats_state, save_stats_state
from bluegrass.research.sums import digit_sum, root_sum


def _draw_id(result: EngineResult) -> str:
    return f"{result.date}:{result.session}:{result.result}"


def refresh_from_result(result: EngineResult) -> dict[str, Any]:
    """Incrementally update session stats for one new draw.

    Per family (sums, root_sums):
      1. Increment draws_since by 1 for every already-tracked value.
      2. Reset draws_since to 0 for the value that just hit.
      3. Update last_seen and times_seen_runtime for the hit.

    Idempotent: duplicate draw IDs (date:session:result) are skipped.
    Returns a summary with a 'skipped' boolean field.
    """
    state = load_stats_state()
    by_session: dict[str, Any] = state.setdefault("by_session", {})

    session = result.session
    session_state: dict[str, Any] = by_session.setdefault(
        session, {"draws_processed": 0, "sums": {}, "root_sums": {}, "processed_draw_ids": []}
    )

    draw_id = _draw_id(result)
    processed_ids: list[str] = session_state.setdefault("processed_draw_ids", [])

    if draw_id in processed_ids:
        return {
            "session": session,
            "result": result.result,
            "date": result.date,
            "jurisdiction": result.jurisdiction,
            "game_family": result.game_family,
            "skipped": True,
            "session_draws_processed": session_state.get("draws_processed", 0),
            "total_draws_processed": state.get("total_draws_processed", 0),
        }

    hit_sum = digit_sum(result.result)
    hit_rs = root_sum(result.result)

    for family_key, hit_value in (("sums", str(hit_sum)), ("root_sums", str(hit_rs))):
        family: dict[str, Any] = session_state.setdefault(family_key, {})

        for entry in family.values():
            entry["draws_since"] = entry.get("draws_since", 0) + 1

        if hit_value not in family:
            family[hit_value] = {
                "draws_since": 0,
                "last_seen": result.date,
                "times_seen_runtime": 1,
            }
        else:
            family[hit_value]["draws_since"] = 0
            family[hit_value]["last_seen"] = result.date
            family[hit_value]["times_seen_runtime"] = (
                family[hit_value].get("times_seen_runtime", 0) + 1
            )

    processed_ids.append(draw_id)
    session_state["draws_processed"] = session_state.get("draws_processed", 0) + 1
    state["total_draws_processed"] = state.get("total_draws_processed", 0) + 1

    save_stats_state(state)

    return {
        "session": session,
        "result": result.result,
        "date": result.date,
        "jurisdiction": result.jurisdiction,
        "game_family": result.game_family,
        "hit_sum": hit_sum,
        "hit_root_sum": hit_rs,
        "skipped": False,
        "session_draws_processed": session_state["draws_processed"],
        "total_draws_processed": state["total_draws_processed"],
    }
