"""Multi-signal convergence scoring for Pick 3 play candidates.

Builds signal pools from the runtime stats layer (sums, root_sums, pairs,
straight_combos, box_families, patterns) and scores candidate numbers from
the baseline priority shortlist against those pools.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from bluegrass.app.playlist import _VALID_SESSIONS
from bluegrass.research.baseline import filter_priority_shortlist
from bluegrass.research.stats_store import load_stats_state
from bluegrass.research.sums import build_root_sums_board, build_sums_board

_POOL_SIZE = 10
_TIER_1_MIN = 5.0
_TIER_2_MIN = 3.0
_SCORE_FLOOR = 1.0

_SCORE_WEIGHTS = {
    "sum":      2.0,
    "root":     2.0,
    "pair":     1.0,   # per pair position hit (max 3)
    "straight": 2.0,
    "box":      1.0,
    "pattern":  1.0,
}


def _box_family(value: str) -> str:
    return "".join(sorted(value))


def _digit_sum(value: int | str) -> int:
    return sum(int(d) for d in str(value))


def _digital_root(value: int | str) -> int:
    if isinstance(value, int):
        n = value
    else:
        n = _digit_sum(value)
    while n >= 10:
        n = sum(int(d) for d in str(n))
    return n


def _pair_value(number: str, position: str) -> str:
    if position == "front":
        return number[0] + number[1]
    if position == "back":
        return number[1] + number[2]
    return number[0] + number[2]


def _normalize_pair_subtype(subtype: str | None) -> str:
    if subtype is None:
        return "other"
    mapping = {
        "front pair straight": "front_straight",
        "front pair box":      "front_box",
        "back pair straight":  "back_straight",
        "back pair box":       "back_box",
        "split pair straight": "split_straight",
        "split pair box":      "split_box",
    }
    return mapping.get(subtype.lower().strip(), "other")


def _classify_pattern(value: str) -> str:
    unique = len(set(value))
    if unique == 3:
        return "single"
    if unique == 2:
        return "double"
    return "triple"


def _pairs_pools(session_state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    pairs_state: dict[str, Any] = session_state.get("pairs", {})
    result: dict[str, list[dict[str, Any]]] = {}

    for position in ("front", "back", "split"):
        raw = pairs_state.get(position, {})
        for is_double, display_key in (
            (False, f"{position}_straight"),
            (True,  f"{position}_box"),
        ):
            filtered = {
                v: e for v, e in raw.items()
                if len(v) == 2 and (v[0] == v[1]) == is_double
            }
            ranked = sorted(
                filtered.items(),
                key=lambda x: x[1].get("draws_since", 0),
                reverse=True,
            )
            result[display_key] = [
                {"value": v, "draws_since": e.get("draws_since", 0), "rank": i + 1}
                for i, (v, e) in enumerate(ranked[:_POOL_SIZE])
            ]

    return result


def _combo_pool(family_state: dict[str, Any], *, limit: int = _POOL_SIZE) -> list[dict[str, Any]]:
    ranked = sorted(
        family_state.items(),
        key=lambda x: x[1].get("draws_since", 0),
        reverse=True,
    )
    return [
        {"value": v, "draws_since": e.get("draws_since", 0), "rank": i + 1}
        for i, (v, e) in enumerate(ranked[:limit])
    ]


def _pattern_pool(patterns_state: dict[str, Any], pt: str) -> list[dict[str, Any]]:
    entry = patterns_state.get(pt)
    if not entry:
        return []
    return [{"value": entry.get("last_value", ""), "draws_since": entry.get("draws_since", 0)}]


def _score_candidate(
    number: str,
    sums_pool: list[dict[str, Any]],
    roots_pool: list[dict[str, Any]],
    pairs_by_sub: dict[str, list[dict[str, Any]]],
    straight_pool: list[dict[str, Any]],
    box_pool: list[dict[str, Any]],
    all_pattern_pool: list[dict[str, Any]],
) -> dict[str, Any]:
    ds  = _digit_sum(number)
    rs  = _digital_root(number)
    bx  = _box_family(number)
    pat = _classify_pattern(number)

    sum_str  = str(ds)
    root_str = str(rs)

    sum_map      = {e["value"]: e["rank"] for e in sums_pool}
    root_map     = {e["value"]: e["rank"] for e in roots_pool}
    straight_map = {e["value"]: e["rank"] for e in straight_pool}
    box_map      = {e["value"]: e["rank"] for e in box_pool}
    pattern_vals = {e["value"] for e in all_pattern_pool}

    sum_match      = sum_str in sum_map
    root_match     = root_str in root_map
    straight_match = number in straight_map
    box_match      = bx in box_map
    pattern_match  = bx in pattern_vals or number in pattern_vals

    front_vals = (
        {e["value"] for e in pairs_by_sub.get("front_straight", [])} |
        {e["value"] for e in pairs_by_sub.get("front_box", [])}
    )
    back_vals = (
        {e["value"] for e in pairs_by_sub.get("back_straight", [])} |
        {e["value"] for e in pairs_by_sub.get("back_box", [])}
    )
    split_vals = (
        {e["value"] for e in pairs_by_sub.get("split_straight", [])} |
        {e["value"] for e in pairs_by_sub.get("split_box", [])}
    )

    pair_hits: list[str] = []
    if _pair_value(number, "front") in front_vals:
        pair_hits.append("front_pair")
    if _pair_value(number, "back") in back_vals:
        pair_hits.append("back_pair")
    if _pair_value(number, "split") in split_vals:
        pair_hits.append("split_pair")

    score = 0.0
    if sum_match:
        score += _SCORE_WEIGHTS["sum"]
    if root_match:
        score += _SCORE_WEIGHTS["root"]
    score += len(pair_hits) * _SCORE_WEIGHTS["pair"]
    if straight_match:
        score += _SCORE_WEIGHTS["straight"]
    if box_match:
        score += _SCORE_WEIGHTS["box"]
    if pattern_match:
        score += _SCORE_WEIGHTS["pattern"]

    signals: dict[str, Any] = {
        "sum_match":          sum_match,
        "sum_value":          sum_str if sum_match else None,
        "sum_rank":           sum_map.get(sum_str) if sum_match else None,
        "root_sum_match":     root_match,
        "root_sum_value":     root_str if root_match else None,
        "root_sum_rank":      root_map.get(root_str) if root_match else None,
        "pair_hits":          pair_hits,
        "pair_hit_count":     len(pair_hits),
        "straight_match":     straight_match,
        "straight_rank":      straight_map.get(number) if straight_match else None,
        "box_family_match":   box_match,
        "box_family":         bx,
        "box_family_rank":    box_map.get(bx) if box_match else None,
        "pattern_pool_match": pattern_match,
    }

    parts: list[str] = []
    if sum_match:
        parts.append(f"sum {sum_str} due (rank {sum_map[sum_str]})")
    if root_match:
        parts.append(f"root {root_str} due (rank {root_map[root_str]})")
    for ph in pair_hits:
        parts.append(f"{ph} hit")
    if straight_match:
        parts.append(f"straight {number} due (rank {straight_map[number]})")
    if box_match:
        parts.append(f"box {bx} due (rank {box_map[bx]})")
    if pattern_match:
        parts.append(f"pattern ({pat}) due")
    rationale = "; ".join(parts) if parts else "no active signals"

    return {
        "number":                     number,
        "digit_sum":                  ds,
        "root_sum":                   rs,
        "digit_pattern":              pat,
        "convergence_score":          round(score, 2),
        "signals":                    signals,
        "in_combo_pool":              box_match or straight_match,
        "rationale":                  rationale,
        "multi_session":              False,
        "sweet404_match":             None,
        "planetary_match":            None,
        "external_convergence_match": None,
        "pillar_support_count":       None,
    }


def _tier(score: float) -> int:
    if score >= _TIER_1_MIN:
        return 1
    if score >= _TIER_2_MIN:
        return 2
    return 3


def build_session_convergence(session: str) -> dict[str, Any]:
    if session not in _VALID_SESSIONS:
        raise ValueError(f"unrecognized session: {session!r}")

    state = load_stats_state().get("by_session", {}).get(session, {})

    sums_board = build_sums_board(session, limit=_POOL_SIZE)
    root_board = build_root_sums_board(session, limit=_POOL_SIZE)
    sums_pool = [
        {"value": r["value"], "draws_since": r["draws_since"], "rank": i + 1}
        for i, r in enumerate(sums_board)
    ]
    roots_pool = [
        {"value": r["value"], "draws_since": r["draws_since"], "rank": i + 1}
        for i, r in enumerate(root_board)
    ]

    pairs_by_sub  = _pairs_pools(state)
    straight_pool = _combo_pool(state.get("straight_combos", {}))
    box_pool      = _combo_pool(state.get("box_families", {}))
    patterns      = state.get("patterns", {})
    singles_pool  = _pattern_pool(patterns, "single")
    doubles_pool  = _pattern_pool(patterns, "double")
    triples_pool  = _pattern_pool(patterns, "triple")
    all_pat_pool  = singles_pool + doubles_pool + triples_pool

    signal_pools: dict[str, Any] = {
        "sums":             sums_pool,
        "root_sums":        roots_pool,
        "pairs_by_subtype": pairs_by_sub,
        "straight_combos":  straight_pool,
        "box_combos":       box_pool,
        "singles":          singles_pool,
        "doubles":          doubles_pool,
        "triples":          triples_pool,
    }

    shortlist_rows = filter_priority_shortlist(session=session, item_type="combination", limit=50)
    raw_candidates: list[dict[str, Any]] = []
    for row in shortlist_rows:
        num = row.get("combo_value") or row.get("value") or ""
        if not num:
            continue
        raw_candidates.append(
            _score_candidate(
                num, sums_pool, roots_pool, pairs_by_sub,
                straight_pool, box_pool, all_pat_pool,
            )
        )

    seen: dict[str, dict[str, Any]] = {}
    for c in raw_candidates:
        num = c["number"]
        if num not in seen or c["convergence_score"] > seen[num]["convergence_score"]:
            seen[num] = c

    candidates: list[dict[str, Any]] = []
    for c in sorted(seen.values(), key=lambda x: x["convergence_score"], reverse=True):
        if c["convergence_score"] < _SCORE_FLOOR:
            continue
        candidates.append({**c, "tier": _tier(c["convergence_score"])})

    tier_counts = {1: 0, 2: 0, 3: 0}
    for c in candidates:
        tier_counts[c["tier"]] += 1

    last_id   = state.get("processed_draw_ids", [])
    last_draw = last_id[-1].split(":")[0] if last_id else "—"

    return {
        "session":          session,
        "candidates":       candidates,
        "signal_pools":     signal_pools,
        "tier_1_count":     tier_counts[1],
        "tier_2_count":     tier_counts[2],
        "tier_3_count":     tier_counts[3],
        "total_candidates": len(candidates),
        "metadata": {
            "last_processed_draw": last_draw,
            "generated_at":        datetime.utcnow().isoformat(),
        },
    }


def build_convergence_overview() -> dict[str, Any]:
    session_summaries: dict[str, Any] = {}
    all_session_top: dict[str, list[str]] = {}

    for sess in sorted(_VALID_SESSIONS):
        conv = build_session_convergence(sess)
        all_session_top[sess] = [
            c["number"] for c in conv["candidates"] if c["tier"] <= 2
        ]
        session_summaries[sess] = {
            "tier_1_count":     conv["tier_1_count"],
            "tier_2_count":     conv["tier_2_count"],
            "tier_3_count":     conv["tier_3_count"],
            "total_candidates": conv["total_candidates"],
        }

    counter: Counter = Counter()
    num_sessions: dict[str, list[str]] = {}
    for sess, nums in all_session_top.items():
        for n in nums:
            counter[n] += 1
            num_sessions.setdefault(n, []).append(sess)

    multi = [
        {"number": n, "sessions": num_sessions[n]}
        for n, cnt in counter.most_common()
        if cnt >= 2
    ]
    multi_nums = {m["number"] for m in multi}

    overview_supported = [
        {"number": n}
        for n, cnt in counter.most_common()
        if cnt == 1 and n not in multi_nums
    ][:20]

    return {
        "multi_session_candidates":      multi,
        "overview_supported_candidates": overview_supported,
        "session_summaries":             session_summaries,
        "metadata": {"generated_at": datetime.utcnow().isoformat()},
    }
