"""Convergence layer: multi-signal candidate scoring for GA Pick 3."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from bluegrass.app.playlist import _VALID_SESSIONS, _last_processed_draw
from bluegrass.app.watchlist import get_watchlist
from bluegrass.research.sums import build_root_sums_board, build_sums_board

_POOL_PULL = 50
_POOL_TOP  = 10

_PAIR_SUBTYPES = (
    "front_straight", "front_box",
    "back_straight",  "back_box",
    "split_straight", "split_box",
)

# Additive score weights
_W_SUM       = 2.0
_W_SUM_BONUS = 0.5   # rank ≤ 3
_W_ROOT      = 1.0
_W_ROOT_BONUS= 0.25  # rank ≤ 3
_W_PAIR      = 0.75  # per pair subtype hit
_W_STRAIGHT  = 2.0
_W_STR_BONUS = 0.5   # rank ≤ 5
_W_BOX       = 1.0
_W_BOX_BONUS = 0.5   # rank ≤ 5
_W_PATTERN   = 0.5

_T1    = 5.0
_T2    = 3.0
_FLOOR = 1.0


# ---------------------------------------------------------------------------
# Pure helpers (exported for tests)
# ---------------------------------------------------------------------------

def _box_family(number: str) -> str:
    return "".join(sorted(number))


def _digit_sum(number: str) -> int:
    return sum(int(d) for d in number)


def _digital_root(n: int) -> int:
    if n == 0:
        return 0
    r = n % 9
    return r if r != 0 else 9


def _normalize_pair_subtype(subtype: str | None) -> str:
    if not subtype:
        return "other"
    low = subtype.lower()
    for pos in ("front", "back", "split"):
        if pos in low:
            for pt in ("straight", "box"):
                if pt in low:
                    return f"{pos}_{pt}"
    return "other"


def _pair_value(number: str, position: str) -> str:
    if position == "front":
        return number[:2]
    if position == "back":
        return number[1:]
    if position == "split":
        return number[0] + number[2]
    return ""


def _digit_pattern(number: str) -> str:
    u = len(set(number))
    if u == 3:
        return "single"
    if u == 2:
        return "double"
    return "triple"


# ---------------------------------------------------------------------------
# Signal pool builder
# ---------------------------------------------------------------------------

def _build_signal_pools(session: str) -> dict[str, Any]:
    # Sums
    sums_pool = [
        {"value": r["value"], "rank": i + 1, "draws_since": r["draws_since"]}
        for i, r in enumerate(build_sums_board(session, limit=_POOL_PULL)[:_POOL_TOP])
    ]

    # Root sums
    root_sums_pool = [
        {"value": r["value"], "rank": i + 1, "draws_since": r["draws_since"]}
        for i, r in enumerate(build_root_sums_board(session, limit=_POOL_PULL)[:_POOL_TOP])
    ]

    # Pairs by subtype (all six slots always present)
    pairs_raw = get_watchlist(session=session, item_type="pair", limit=_POOL_PULL)
    by_subtype: dict[str, list[dict[str, Any]]] = {st: [] for st in _PAIR_SUBTYPES}
    for row in pairs_raw:
        key = _normalize_pair_subtype(row.get("subtype"))
        if key in by_subtype and len(by_subtype[key]) < _POOL_TOP:
            by_subtype[key].append({
                "value": str(row.get("value", "")),
                "rank": len(by_subtype[key]) + 1,
                "draws_since": row.get("draws_since", 0),
            })

    # Combos split by play type and digit pattern
    combos_raw = get_watchlist(session=session, item_type="combination", limit=_POOL_PULL)
    straight_combos: list[dict[str, Any]] = []
    box_combos:      list[dict[str, Any]] = []
    singles:         list[dict[str, Any]] = []
    doubles:         list[dict[str, Any]] = []
    triples:         list[dict[str, Any]] = []

    for row in combos_raw:
        val = str(row.get("value", ""))
        if len(val) != 3 or not val.isdigit():
            continue
        entry = {"value": val, "draws_since": row.get("draws_since", 0)}
        sub = str(row.get("subtype", "")).lower()
        if "straight" in sub and len(straight_combos) < _POOL_TOP:
            straight_combos.append({**entry, "rank": len(straight_combos) + 1})
        elif "box" in sub and len(box_combos) < _POOL_TOP:
            box_combos.append({**entry, "rank": len(box_combos) + 1})
        pat = _digit_pattern(val)
        if pat == "single":
            singles.append({**entry, "rank": len(singles) + 1})
        elif pat == "double":
            doubles.append({**entry, "rank": len(doubles) + 1})
        else:
            triples.append({**entry, "rank": len(triples) + 1})

    return {
        "sums": sums_pool,
        "root_sums": root_sums_pool,
        "pairs_by_subtype": by_subtype,
        "straight_combos": straight_combos,
        "box_combos": box_combos,
        "singles": singles,
        "doubles": doubles,
        "triples": triples,
    }


def _build_lookups(pools: dict[str, Any]) -> dict[str, Any]:
    sum_rank:  dict[str, int] = {e["value"]: e["rank"] for e in pools["sums"]}
    root_rank: dict[str, int] = {e["value"]: e["rank"] for e in pools["root_sums"]}
    pair_rank: dict[str, dict[str, int]] = {
        st: {e["value"]: e["rank"] for e in entries}
        for st, entries in pools["pairs_by_subtype"].items()
    }
    straight_rank: dict[str, int] = {e["value"]: e["rank"] for e in pools["straight_combos"]}
    box_family_rank: dict[str, int] = {}
    for e in pools["box_combos"]:
        fam = _box_family(e["value"])
        if fam not in box_family_rank:
            box_family_rank[fam] = e["rank"]
    pattern_pool: set[str] = set()
    for lst in (pools["straight_combos"], pools["box_combos"],
                pools["singles"], pools["doubles"], pools["triples"]):
        pattern_pool.update(e["value"] for e in lst)
    return {
        "sum_rank": sum_rank,
        "root_rank": root_rank,
        "pair_rank": pair_rank,
        "straight_rank": straight_rank,
        "box_family_rank": box_family_rank,
        "pattern_pool": pattern_pool,
    }


# ---------------------------------------------------------------------------
# Supplementary candidate generation (sum × pair, pair × pair)
# ---------------------------------------------------------------------------

def _supplementary_candidates(pools: dict[str, Any], exclude: set[str]) -> set[str]:
    out: set[str] = set()

    sums       = [e["value"] for e in pools["sums"]]
    front_vals = ([e["value"] for e in pools["pairs_by_subtype"]["front_straight"]]
                + [e["value"] for e in pools["pairs_by_subtype"]["front_box"]])
    back_vals  = ([e["value"] for e in pools["pairs_by_subtype"]["back_straight"]]
                + [e["value"] for e in pools["pairs_by_subtype"]["back_box"]])
    split_vals = ([e["value"] for e in pools["pairs_by_subtype"]["split_straight"]]
                + [e["value"] for e in pools["pairs_by_subtype"]["split_box"]])

    for sv in sums:
        try:
            s = int(sv)
        except ValueError:
            continue
        for fp in front_vals:   # ABx → x = s - A - B
            if len(fp) == 2:
                r = s - int(fp[0]) - int(fp[1])
                if 0 <= r <= 9:
                    out.add(fp + str(r))
        for bp in back_vals:    # xAB → x = s - A - B
            if len(bp) == 2:
                r = s - int(bp[0]) - int(bp[1])
                if 0 <= r <= 9:
                    out.add(str(r) + bp)
        for sp in split_vals:   # AxB → x = s - A - B
            if len(sp) == 2:
                r = s - int(sp[0]) - int(sp[1])
                if 0 <= r <= 9:
                    out.add(sp[0] + str(r) + sp[1])

    # front × back: fp[1] == bp[0] → fp[0] fp[1] bp[1]
    for fp in front_vals:
        for bp in back_vals:
            if len(fp) == 2 and len(bp) == 2 and fp[1] == bp[0]:
                out.add(fp[0] + fp[1] + bp[1])

    # front × split: fp[0] == sp[0] → fp[0] fp[1] sp[1]
    for fp in front_vals:
        for sp in split_vals:
            if len(fp) == 2 and len(sp) == 2 and fp[0] == sp[0]:
                out.add(fp[0] + fp[1] + sp[1])

    # back × split: bp[1] == sp[1] → sp[0] bp[0] bp[1]
    for bp in back_vals:
        for sp in split_vals:
            if len(bp) == 2 and len(sp) == 2 and bp[1] == sp[1]:
                out.add(sp[0] + bp[0] + bp[1])

    return out - exclude


# ---------------------------------------------------------------------------
# Candidate scorer
# ---------------------------------------------------------------------------

def _score_candidate(number: str, lookups: dict[str, Any], in_combo_pool: bool) -> dict[str, Any]:
    ds    = _digit_sum(number)
    rs    = _digital_root(ds)
    ds_s  = str(ds)
    rs_s  = str(rs)
    bf    = _box_family(number)
    pat   = _digit_pattern(number)
    score = 0.0
    sig: dict[str, Any] = {}

    # Sum
    sr = lookups["sum_rank"].get(ds_s)
    sm = sr is not None
    if sm:
        score += _W_SUM + (_W_SUM_BONUS if sr <= 3 else 0)
    sig["sum_match"] = sm; sig["sum_value"] = ds_s; sig["sum_rank"] = sr

    # Root sum
    rr = lookups["root_rank"].get(rs_s)
    rm = rr is not None
    if rm:
        score += _W_ROOT + (_W_ROOT_BONUS if rr <= 3 else 0)
    sig["root_sum_match"] = rm; sig["root_sum_value"] = rs_s; sig["root_sum_rank"] = rr

    # Pair hits — all six subtypes
    pair_hits: list[str] = []
    for pos in ("front", "back", "split"):
        pv = _pair_value(number, pos)
        for pt in ("straight", "box"):
            st = f"{pos}_{pt}"
            r  = lookups["pair_rank"].get(st, {}).get(pv)
            if r is not None:
                pair_hits.append(st)
                score += _W_PAIR
    sig["pair_hits"] = pair_hits; sig["pair_hit_count"] = len(pair_hits)

    # Straight match
    str_r = lookups["straight_rank"].get(number)
    str_m = str_r is not None
    if str_m:
        score += _W_STRAIGHT + (_W_STR_BONUS if str_r <= 5 else 0)
    sig["straight_match"] = str_m; sig["straight_rank"] = str_r

    # Box-family match (not exact value — sorted digits)
    bfr = lookups["box_family_rank"].get(bf)
    bfm = bfr is not None
    if bfm:
        score += _W_BOX + (_W_BOX_BONUS if bfr <= 5 else 0)
    sig["box_family_match"] = bfm; sig["box_family"] = bf; sig["box_family_rank"] = bfr

    # Pattern pool
    ppm = number in lookups["pattern_pool"]
    if ppm:
        score += _W_PATTERN
    sig["pattern_pool_match"] = ppm

    score = round(score, 4)
    tier  = 1 if score >= _T1 else (2 if score >= _T2 else 3)

    # Evidence row / rationale
    parts: list[str] = []
    if sm:
        parts.append(f"sum={ds_s}(#{sr})")
    if rm:
        parts.append(f"root={rs_s}(#{rr})")
    if pair_hits:
        parts.append(f"pairs:[{','.join(pair_hits)}]")
    if str_m:
        parts.append(f"straight(#{str_r})")
    if bfm:
        parts.append(f"box={bf}(#{bfr})")
    if ppm:
        parts.append("pattern-pool")
    rationale = " | ".join(parts) if parts else "no signals"

    return {
        "number":           number,
        "digit_sum":        ds,
        "root_sum":         rs,
        "digit_pattern":    pat,
        "convergence_score": score,
        "tier":             tier,
        "rationale":        rationale,
        "signals":          sig,
        "in_combo_pool":    in_combo_pool,
        "multi_session":    False,
        # future-ready pillar fields
        "sweet404_match":             None,
        "planetary_match":            None,
        "external_convergence_match": None,
        "pillar_support_count":       None,
    }


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------

def build_session_convergence(session: str) -> dict[str, Any]:
    """Full convergence payload for one session."""
    if session not in _VALID_SESSIONS:
        raise ValueError(f"unrecognized session: {session!r}")

    pools   = _build_signal_pools(session)
    lookups = _build_lookups(pools)

    # Primary: combo watchlist
    combos_raw   = get_watchlist(session=session, item_type="combination", limit=_POOL_PULL)
    combo_values = {str(r.get("value", "")) for r in combos_raw
                    if len(str(r.get("value", ""))) == 3 and str(r.get("value", "")).isdigit()}

    candidates: list[dict[str, Any]] = []
    for num in combo_values:
        c = _score_candidate(num, lookups, in_combo_pool=True)
        if c["convergence_score"] >= _FLOOR:
            candidates.append(c)

    # Supplementary: signal intersections
    for num in _supplementary_candidates(pools, combo_values):
        c = _score_candidate(num, lookups, in_combo_pool=False)
        if c["convergence_score"] >= _FLOOR:
            candidates.append(c)

    candidates.sort(key=lambda c: (-c["convergence_score"], c["number"]))
    counts = Counter(c["tier"] for c in candidates)

    return {
        "session":          session,
        "candidates":       candidates,
        "signal_pools":     pools,
        "tier_1_count":     counts.get(1, 0),
        "tier_2_count":     counts.get(2, 0),
        "tier_3_count":     counts.get(3, 0),
        "total_candidates": len(candidates),
        "metadata": {
            "session":             session,
            "source":              "baseline+runtime",
            "last_processed_draw": _last_processed_draw(session),
            "generated_at":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }


def build_convergence_overview() -> dict[str, Any]:
    """Cross-session convergence overview.

    Bucket A: numbers appearing in 2+ sessions (multi_session_candidates).
    Bucket B: single-session numbers whose sum, root, or box family also
              appears in another session's signal pools (overview_supported_candidates).
    No number is in both buckets.
    """
    sessions = list(_VALID_SESSIONS)
    by_session: dict[str, dict[str, Any]] = {s: build_session_convergence(s) for s in sessions}

    # Collect per-number appearances and best score
    num_sessions: dict[str, list[str]] = {}
    num_best:     dict[str, dict[str, Any]] = {}
    for sess, res in by_session.items():
        for c in res["candidates"]:
            n = c["number"]
            num_sessions.setdefault(n, []).append(sess)
            if n not in num_best or c["convergence_score"] > num_best[n]["convergence_score"]:
                num_best[n] = {**c}

    # Cross-session pool sets (for Bucket B support check)
    other_sums:  dict[str, set[str]] = {s: set() for s in sessions}
    other_roots: dict[str, set[str]] = {s: set() for s in sessions}
    other_boxes: dict[str, set[str]] = {s: set() for s in sessions}
    for sess, res in by_session.items():
        p = res["signal_pools"]
        for other in sessions:
            if other == sess:
                continue
            other_sums[other].update(e["value"] for e in p["sums"])
            other_roots[other].update(e["value"] for e in p["root_sums"])
            other_boxes[other].update(
                _box_family(e["value"])
                for e in p["straight_combos"] + p["box_combos"]
            )

    bucket_a: list[dict[str, Any]] = []
    bucket_b: list[dict[str, Any]] = []
    a_nums:   set[str] = set()

    for num, sess_list in num_sessions.items():
        if len(sess_list) >= 2:
            entry = {**num_best[num], "sessions_present": sorted(set(sess_list)), "multi_session": True}
            bucket_a.append(entry)
            a_nums.add(num)

    for num, sess_list in num_sessions.items():
        if num in a_nums:
            continue
        src = sess_list[0]
        best = num_best[num]
        supported = (
            str(best["digit_sum"]) in other_sums.get(src, set())
            or str(best["root_sum"]) in other_roots.get(src, set())
            or _box_family(num) in other_boxes.get(src, set())
        )
        if supported:
            bucket_b.append({**best, "sessions_present": sess_list})

    bucket_a.sort(key=lambda c: (-c["convergence_score"], c["number"]))
    bucket_b.sort(key=lambda c: (-c["convergence_score"], c["number"]))

    return {
        "multi_session_candidates":      bucket_a,
        "overview_supported_candidates": bucket_b,
        "session_summaries": {
            sess: {
                "tier_1_count":        res["tier_1_count"],
                "tier_2_count":        res["tier_2_count"],
                "tier_3_count":        res["tier_3_count"],
                "total_candidates":    res["total_candidates"],
                "last_processed_draw": res["metadata"]["last_processed_draw"],
            }
            for sess, res in by_session.items()
        },
        "metadata": {
            "source":       "baseline+runtime",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
