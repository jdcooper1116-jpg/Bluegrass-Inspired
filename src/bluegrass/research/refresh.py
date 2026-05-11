"""Incremental stat refresh – update runtime state when a new draw result arrives.

Only the session that received the draw is touched. The baseline seed CSVs are
never mutated. All derived families (sums, root_sums, pairs, straight_combos,
box_families, patterns) age by 1 on each new draw; the hit values reset to 0.
"""

from __future__ import annotations

from typing import Any

from bluegrass.engine.intake import EngineResult
from bluegrass.research.stats_store import load_stats_state, save_stats_state
from bluegrass.research.sums import digit_sum, root_sum


def _draw_id(result: EngineResult) -> str:
    return f"{result.date}:{result.session}:{result.result}"


def _classify_pattern(value: str) -> str:
    unique = len(set(value))
    if unique == 3:
        return "single"
    if unique == 2:
        return "double"
    return "triple"


def _update_family(family: dict[str, Any], hit_value: str, date: str) -> None:
    """Age all tracked values by 1, then reset the hit value to 0."""
    for entry in family.values():
        entry["draws_since"] = entry.get("draws_since", 0) + 1
    if hit_value not in family:
        family[hit_value] = {"draws_since": 0, "last_seen": date, "times_seen_runtime": 1}
    else:
        family[hit_value]["draws_since"] = 0
        family[hit_value]["last_seen"] = date
        family[hit_value]["times_seen_runtime"] = (
            family[hit_value].get("times_seen_runtime", 0) + 1
        )


def _update_patterns(
    patterns: dict[str, Any], hit_type: str, date: str, value: str
) -> None:
    """Age non-hit pattern types; reset the matching pattern type."""
    for pt in ("single", "double", "triple"):
        entry = patterns.setdefault(
            pt, {"draws_since": 0, "last_seen": "", "last_value": ""}
        )
        if pt == hit_type:
            entry["draws_since"] = 0
            entry["last_seen"] = date
            entry["last_value"] = value
        else:
            entry["draws_since"] = entry.get("draws_since", 0) + 1


def refresh_from_result(result: EngineResult) -> dict[str, Any]:
    """Incrementally update all session-derived stats for one new draw.

    Families updated per draw:
      sums, root_sums, pairs (front/back/split),
      straight_combos, box_families, patterns (single/double/triple)

    Idempotent: duplicate draw IDs (date:session:result) are skipped.
    Returns a summary dict with a 'skipped' boolean field.
    """
    state = load_stats_state()
    by_session: dict[str, Any] = state.setdefault("by_session", {})

    session = result.session
    session_state: dict[str, Any] = by_session.setdefault(
        session,
        {"draws_processed": 0, "sums": {}, "root_sums": {}, "processed_draw_ids": []},
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

    r = result.result
    hit_sum = digit_sum(r)
    hit_rs = root_sum(r)
    front_pair = r[0] + r[1]
    back_pair = r[1] + r[2]
    split_pair = r[0] + r[2]
    box_family = "".join(sorted(r))
    pattern_type = _classify_pattern(r)

    # sums and root_sums
    for family_key, hit_value in (("sums", str(hit_sum)), ("root_sums", str(hit_rs))):
        _update_family(session_state.setdefault(family_key, {}), hit_value, result.date)

    # pairs — three subtypes, each a separate family dict
    pairs: dict[str, Any] = session_state.setdefault(
        "pairs", {"front": {}, "back": {}, "split": {}}
    )
    _update_family(pairs.setdefault("front", {}), front_pair, result.date)
    _update_family(pairs.setdefault("back", {}), back_pair, result.date)
    _update_family(pairs.setdefault("split", {}), split_pair, result.date)

    # straight combo (exact 3-digit result)
    _update_family(
        session_state.setdefault("straight_combos", {}), r, result.date
    )

    # box family (sorted digits)
    _update_family(
        session_state.setdefault("box_families", {}), box_family, result.date
    )

    # digit pattern
    _update_patterns(
        session_state.setdefault("patterns", {}), pattern_type, result.date, r
    )

    processed_ids.append(draw_id)
    session_state["draws_processed"] = session_state.get("draws_processed", 0) + 1
    state["total_draws_processed"] = state.get("total_draws_processed", 0) + 1

    save_stats_state(state)

    return {
        "session": session,
        "result": r,
        "date": result.date,
        "jurisdiction": result.jurisdiction,
        "game_family": result.game_family,
        "hit_sum": hit_sum,
        "hit_root_sum": hit_rs,
        "hit_front_pair": front_pair,
        "hit_back_pair": back_pair,
        "hit_split_pair": split_pair,
        "hit_straight_combo": r,
        "hit_box_family": box_family,
        "hit_pattern": pattern_type,
        "skipped": False,
        "session_draws_processed": session_state["draws_processed"],
        "total_draws_processed": state["total_draws_processed"],
    }
