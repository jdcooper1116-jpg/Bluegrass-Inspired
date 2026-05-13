"""Daily session board builder.

Two parallel card lists per family
-----------------------------------
Compact  (top_sums, top_root_sums, top_pairs, top_combinations)
    Stable contract consumed by overview.py, tests, and downstream aggregators.
    Keys: family, value, draws_since, last_seen, why_flagged, [subtype],
          signal_quality, deviation_note.
    Never contains bulk keys: combo_count, times_drawn, run_id,
    baseline_priority_score, source_url, item_type.

Detail   (top_sums_detail, top_root_sums_detail, top_pairs_detail,
          top_combinations_detail)
    Full deviation payload for session.html and direct API consumers.
    All compact fields plus gap_ratio, severity_band, expected_gap_draws,
    expected_hits, observed_hits, multi_window_agreement, gap_zscore,
    combo_count, draws_processed, short/medium/long_term_cold.

Sort modes (sort_mode kwarg)
----------------------------
"overdue"   — raw draws_since desc (section cards)
"deviation" — gap_ratio desc (section cards)
"composite" — gap_ratio x structural-weight desc (default; section cards)
The shortlist is always composite-scored regardless of sort_mode.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bluegrass.app.playlist import _VALID_SESSIONS, _last_processed_draw
from bluegrass.app.watchlist import get_watchlist
from bluegrass.research.config import ANALYSIS_WINDOW_DAYS, SYNC_WINDOW_DAYS
from bluegrass.research.stats_engine import (
    PAIR_EXPECTED_GAP,
    PAIR_QUANT,
    ROOT_MAX_QUANT,
    SUM_MAX_QUANT,
    composite_score,
    compute_deviation_metrics,
    describe_deviation,
)
from bluegrass.research.stats_store import load_stats_state
from bluegrass.research.sums import build_root_sums_board, build_sums_board

_SECTION_SIZE = 4
_SHORTLIST_QUOTA = 3
_COMBO_SHORTLIST_QUOTA = 2
_PULL = 10

_SORT_MODES = ("overdue", "deviation", "composite")
_DEFAULT_SORT_MODE = "composite"

# Keys that must never appear in compact cards
_BULK_KEYS = frozenset({
    "combo_count", "times_drawn", "run_id",
    "baseline_priority_score", "source_url", "item_type",
})


# ---------------------------------------------------------------------------
# Rank comparison across all three sort modes
# ---------------------------------------------------------------------------

def _compute_rank_comparisons(
    all_rows: list[dict[str, Any]],
    max_quant: int,
) -> dict[str, dict[str, int]]:
    """Return {value: {overdue_rank, deviation_rank, composite_rank}} for every row.

    Ranks are 1-based positions in the full sorted list (not just the top-N slice).
    Used to inject rank movement context into detail cards.
    """
    ov = _sort_rows(all_rows, "overdue",    max_quant)
    dv = _sort_rows(all_rows, "deviation",  max_quant)
    cv = _sort_rows(all_rows, "composite",  max_quant)
    ov_rank = {r["value"]: i + 1 for i, r in enumerate(ov)}
    dv_rank = {r["value"]: i + 1 for i, r in enumerate(dv)}
    cv_rank = {r["value"]: i + 1 for i, r in enumerate(cv)}
    result: dict[str, dict[str, int]] = {}
    for r in all_rows:
        v = r["value"]
        result[v] = {
            "overdue_rank":    ov_rank.get(v, 0),
            "deviation_rank":  dv_rank.get(v, 0),
            "composite_rank":  cv_rank.get(v, 0),
        }
    return result


def _movement_label(rank_info: dict[str, int], sort_mode: str) -> str:
    """Return a compact label showing whether this value moved relative to overdue baseline.

    Always compares to overdue rank because overdue is the most intuitive baseline.
    """
    ov = rank_info["overdue_rank"]
    if sort_mode == "deviation":
        current = rank_info["deviation_rank"]
    elif sort_mode == "composite":
        current = rank_info["composite_rank"]
    else:
        return "steady"   # overdue mode — no movement relative to itself

    delta = ov - current   # positive → promoted (lower rank number = higher position)
    if abs(delta) <= 1:
        return "steady"
    if delta >= 5:
        return "↑↑ promoted"
    if delta >= 2:
        return "↑ elevated"
    if delta <= -5:
        return "↓↓ demoted"
    return "↓ lower"


def _compare_note(
    value: str,
    rank_info: dict[str, int],
    sort_mode: str,
    gap_ratio: float | None,
) -> str | None:
    """One-sentence explanation for significant rank movement vs overdue baseline."""
    ov = rank_info["overdue_rank"]
    if sort_mode == "overdue":
        return None
    current = rank_info["deviation_rank"] if sort_mode == "deviation" else rank_info["composite_rank"]
    delta = ov - current
    if abs(delta) <= 1:
        return None
    direction = "promoted" if delta > 0 else "demoted"
    by = abs(delta)
    if gap_ratio is not None:
        reason = (
            f"gap_ratio {gap_ratio:.1f}x outweighs raw absence"
            if delta > 0 else
            f"structural weighting reduced score relative to gap"
        )
        return f"sum {value} {direction} {by} places by {sort_mode} logic — {reason}"
    return f"sum {value} {direction} {by} places in {sort_mode} ranking"


# ---------------------------------------------------------------------------
# Signal quality classification
# ---------------------------------------------------------------------------

def _signal_quality(quant: int, has_runtime: bool) -> str:
    if quant <= 3:
        return "sparse-data"
    return "deviation-backed" if has_runtime else "overdue-only"


# ---------------------------------------------------------------------------
# Pair enrichment from runtime stats
# ---------------------------------------------------------------------------

def _pair_position_from_subtype(subtype: str | None) -> str:
    if not subtype:
        return ""
    s = subtype.lower()
    if "front" in s:
        return "front"
    if "back" in s:
        return "back"
    if "split" in s:
        return "split"
    return ""


def _enrich_pairs_from_runtime(
    rows: list[dict[str, Any]],
    session: str,
) -> list[dict[str, Any]]:
    """Attach engine-runtime deviation data to baseline watchlist pair rows."""
    state = load_stats_state()
    sess_state = state.get("by_session", {}).get(session, {})
    runtime_pairs: dict[str, Any] = sess_state.get("pairs", {})
    draws_processed: int = sess_state.get("draws_processed", 0)

    enriched: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        position = _pair_position_from_subtype(row.get("subtype", ""))
        value = str(row.get("value", ""))
        runtime = runtime_pairs.get(position, {}).get(value) if position else None

        if runtime and draws_processed > 0:
            ds    = runtime["draws_since"]
            times = runtime.get("times_seen_runtime", 0)
            dev   = compute_deviation_metrics(ds, times, draws_processed, PAIR_QUANT)
            row.update({
                "draws_since":            ds,
                "draws_processed":        draws_processed,
                "times_drawn_runtime":    times,
                "expected_gap_draws":     dev["expected_gap_draws"],
                "expected_hits":          dev["expected_hits"],
                "observed_hits":          dev["observed_hits"],
                "gap_ratio":              dev["gap_ratio"],
                "gap_zscore":             dev["gap_zscore"],
                "severity_band":          dev["severity_band"],
                "short_term_cold":        dev["short_term_cold"],
                "medium_term_cold":       dev["medium_term_cold"],
                "long_term_cold":         dev["long_term_cold"],
                "multi_window_agreement": dev["multi_window_agreement"],
                "signal_quality":         _signal_quality(PAIR_QUANT, has_runtime=True),
                "deviation_note":         None,
                "why_flagged":            describe_deviation(
                    value, "pair", ds, PAIR_QUANT,
                    dev["severity_band"], dev["gap_ratio"],
                    dev["multi_window_agreement"],
                ),
            })
        else:
            row.setdefault("gap_ratio",              None)
            row.setdefault("gap_zscore",             None)
            row.setdefault("severity_band",          None)
            row.setdefault("expected_gap_draws",     PAIR_EXPECTED_GAP)
            row.setdefault("multi_window_agreement", None)
            row["signal_quality"] = "overdue-only"
            row["deviation_note"] = (
                "Draws_since from baseline CSV; no engine-runtime record yet"
            )
        enriched.append(row)
    return enriched


# ---------------------------------------------------------------------------
# Compact card builders — stable public contract, no bulk keys
# ---------------------------------------------------------------------------

def _compact_sum_card(row: dict[str, Any], family: str) -> dict[str, Any]:
    quant = row.get("combo_count", 1) or 1
    sq = row.get("signal_quality") or _signal_quality(quant, has_runtime=True)
    return {
        "family":         family,
        "value":          row["value"],
        "draws_since":    row["draws_since"],
        "last_seen":      row.get("last_seen", ""),
        "why_flagged":    row.get("why_flagged", ""),
        "signal_quality": sq,
        "deviation_note": row.get("deviation_note"),
    }


def _compact_pair_card(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "family":         "pair",
        "value":          row.get("value", ""),
        "draws_since":    row.get("draws_since", ""),
        "last_seen":      row.get("last_seen", ""),
        "why_flagged":    row.get("why_flagged", ""),
        "subtype":        row.get("subtype", ""),
        "signal_quality": row.get("signal_quality", "overdue-only"),
        "deviation_note": row.get("deviation_note"),
    }


def _compact_combo_card(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "family":         "combination",
        "value":          row.get("value", ""),
        "draws_since":    row.get("draws_since", ""),
        "last_seen":      row.get("last_seen", ""),
        "why_flagged":    row.get("why_flagged", ""),
        "subtype":        row.get("subtype", ""),
        "signal_quality": "overdue-only",
        "deviation_note": (
            "Combination overdue from baseline CSV; "
            "engine-runtime deviation not modeled."
        ),
    }


# ---------------------------------------------------------------------------
# Detail card builders — full deviation payload
# ---------------------------------------------------------------------------

def _detail_sum_card(
    row: dict[str, Any],
    family: str,
    rank_info: dict[str, int] | None = None,
    sort_mode: str = "composite",
) -> dict[str, Any]:
    """Full deviation detail card with rank comparison fields."""
    quant = row.get("combo_count", 1) or 1
    sq = row.get("signal_quality") or _signal_quality(quant, has_runtime=True)

    ri    = rank_info or {}
    ov_r  = ri.get("overdue_rank",   0)
    dv_r  = ri.get("deviation_rank", 0)
    cv_r  = ri.get("composite_rank", 0)
    cur_r = {"overdue": ov_r, "deviation": dv_r, "composite": cv_r}.get(sort_mode, cv_r)

    return {
        "family":                  family,
        "value":                   row["value"],
        "draws_since":             row["draws_since"],
        "last_seen":               row.get("last_seen", ""),
        "why_flagged":             row.get("why_flagged", ""),
        "signal_quality":          sq,
        "deviation_note":          row.get("deviation_note"),
        "gap_ratio":               row.get("gap_ratio"),
        "gap_zscore":              row.get("gap_zscore"),
        "severity_band":           row.get("severity_band"),
        "expected_gap_draws":      row.get("expected_gap_draws"),
        "expected_hits":           row.get("expected_hits"),
        "observed_hits":           row.get("observed_hits"),
        "multi_window_agreement":  row.get("multi_window_agreement"),
        "short_term_cold":         row.get("short_term_cold"),
        "medium_term_cold":        row.get("medium_term_cold"),
        "long_term_cold":          row.get("long_term_cold"),
        "combo_count":             row.get("combo_count"),
        "draws_processed":         row.get("draws_processed"),
        # Rank comparison — mode movement indicators
        "overdue_rank":            ov_r,
        "deviation_rank":          dv_r,
        "composite_rank":          cv_r,
        "current_rank":            cur_r,
        "current_mode":            sort_mode,
        "movement_label":          _movement_label(ri, sort_mode) if ri else "steady",
        "compare_note":            _compare_note(
            row["value"], ri, sort_mode, row.get("gap_ratio")
        ) if ri else None,
    }


def _detail_pair_card(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "family":                  "pair",
        "value":                   row.get("value", ""),
        "draws_since":             row.get("draws_since", ""),
        "last_seen":               row.get("last_seen", ""),
        "why_flagged":             row.get("why_flagged", ""),
        "subtype":                 row.get("subtype", ""),
        "signal_quality":          row.get("signal_quality", "overdue-only"),
        "deviation_note":          row.get("deviation_note"),
        "gap_ratio":               row.get("gap_ratio"),
        "gap_zscore":              row.get("gap_zscore"),
        "severity_band":           row.get("severity_band"),
        "expected_gap_draws":      row.get("expected_gap_draws"),
        "expected_hits":           row.get("expected_hits"),
        "observed_hits":           row.get("observed_hits"),
        "multi_window_agreement":  row.get("multi_window_agreement"),
        "short_term_cold":         row.get("short_term_cold"),
        "medium_term_cold":        row.get("medium_term_cold"),
        "long_term_cold":          row.get("long_term_cold"),
        "draws_processed":         row.get("draws_processed"),
    }


def _detail_combo_card(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "family":                  "combination",
        "value":                   row.get("value", ""),
        "draws_since":             row.get("draws_since", ""),
        "last_seen":               row.get("last_seen", ""),
        "why_flagged":             row.get("why_flagged", ""),
        "subtype":                 row.get("subtype", ""),
        "signal_quality":          "overdue-only",
        "deviation_note":          (
            "Combination overdue from baseline CSV; "
            "engine-runtime deviation not modeled."
        ),
        "gap_ratio":               None,
        "severity_band":           None,
        "expected_gap_draws":      None,
        "multi_window_agreement":  None,
    }


# ---------------------------------------------------------------------------
# Shortlist scorer
# ---------------------------------------------------------------------------

def _recency_factor(last_seen: str) -> float:
    if not last_seen:
        return 0.0
    try:
        year = int(last_seen[:4])
    except (ValueError, IndexError):
        return 0.0
    if year >= 2022:
        return 1.0
    if year >= 2018:
        return 0.7
    if year >= 2015:
        return 0.4
    if year >= 2010:
        return 0.2
    return 0.0


def _family_max_ds(rows: list[dict[str, Any]]) -> float:
    vals = []
    for r in rows:
        try:
            vals.append(float(r.get("draws_since", 0) or 0))
        except (TypeError, ValueError):
            pass
    return max(vals, default=1.0) or 1.0


def _score_sum(row: dict[str, Any], max_ds: float) -> float:
    quant  = row.get("combo_count", 1) or 1
    gr     = row.get("gap_ratio", 0.0) or 0.0
    family = row.get("family", "sum")
    mq     = SUM_MAX_QUANT if family == "sum" else ROOT_MAX_QUANT
    pw     = (quant / mq) ** 0.25
    return round(gr * pw, 6)


def _score_pair(row: dict[str, Any], max_ds: float) -> float:
    gr = row.get("gap_ratio")
    if gr is None:
        ds = float(row.get("draws_since") or 0)
        gr = ds / PAIR_EXPECTED_GAP
    try:
        priority = min(float(row.get("baseline_priority_score") or 0) / 25.0, 1.0)
    except (TypeError, ValueError):
        priority = 0.0
    return round(0.75 * gr + 0.25 * priority, 6)


def _score_combo(row: dict[str, Any], max_ds: float) -> float:
    try:
        ds = float(row.get("draws_since", 0) or 0)
    except (TypeError, ValueError):
        ds = 0.0
    overdue = ds / max_ds
    try:
        times    = float(row.get("times_drawn") or 0)
        expected = float(row.get("expected_times") or 0)
        below_exp = max(0.0, (expected - times) / expected) if expected > 0 else 0.0
    except (TypeError, ValueError):
        below_exp = 0.0
    recency = _recency_factor(str(row.get("last_seen", "") or ""))
    return round(0.40 * overdue + 0.35 * below_exp + 0.25 * recency, 6)


def _pick_quota(
    rows: list[dict[str, Any]],
    family: str,
    score_fn: Any,
    session: str,
    quota: int,
) -> list[tuple[float, dict[str, Any]]]:
    max_ds = _family_max_ds(rows)
    scored = [(score_fn(r, max_ds), r) for r in rows]
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:quota]


def _build_board_shortlist(
    session: str,
    sums: list[dict[str, Any]],
    root_sums: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    combos: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    buckets = [
        _pick_quota(sums,      "sum",         _score_sum,   session, _SHORTLIST_QUOTA),
        _pick_quota(root_sums, "root_sum",    _score_sum,   session, _SHORTLIST_QUOTA),
        _pick_quota(pairs,     "pair",        _score_pair,  session, _SHORTLIST_QUOTA),
        _pick_quota(combos,    "combination", _score_combo, session, _COMBO_SHORTLIST_QUOTA),
    ]
    shortlist: list[dict[str, Any]] = []
    for scored, family in zip(
        buckets, ("sum", "root_sum", "pair", "combination")
    ):
        for score, row in scored:
            entry = _make_shortlist_entry(row, family, session, composite_score_val=score)
            shortlist.append((score, entry))
    shortlist.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in shortlist]


def _make_shortlist_entry(
    row: dict[str, Any],
    family: str,
    session: str,
    composite_score_val: float = 0.0,
) -> dict[str, Any]:
    why = row.get("why_flagged") or (
        f"{family.replace('_', ' ')} {row.get('value')} "
        f"absent {row.get('draws_since')} draws"
    )
    sq = row.get("signal_quality")
    if sq is None:
        sq = "deviation-backed" if row.get("gap_ratio") is not None else "overdue-only"

    # Compact score breakdown for explainability
    quant = row.get("combo_count") or 0
    gr    = row.get("gap_ratio")
    mq    = SUM_MAX_QUANT if family == "sum" else (ROOT_MAX_QUANT if family == "root_sum" else 0)
    pw    = round((quant / mq) ** 0.25, 4) if (mq > 0 and quant > 0) else None

    if family in ("sum", "root_sum") and gr is not None:
        score_components = {
            "gap_ratio":         gr,
            "structural_weight": pw,
            "composite_score":   composite_score_val,
            "scoring_mode":      "always composite",
        }
    elif family == "pair":
        score_components = {
            "gap_ratio":        gr,
            "composite_score":  composite_score_val,
            "scoring_mode":     "always composite",
        }
    else:
        score_components = {
            "composite_score": composite_score_val,
            "scoring_mode":    "always composite",
        }

    return {
        "family":                  family,
        "value":                   row.get("value", ""),
        "draws_since":             row.get("draws_since", ""),
        "last_seen":               row.get("last_seen", ""),
        "why_flagged":             why,
        "subtype":                 row.get("subtype"),
        "session":                 session,
        "gap_ratio":               row.get("gap_ratio"),
        "severity_band":           row.get("severity_band"),
        "multi_window_agreement":  row.get("multi_window_agreement"),
        "expected_gap_draws":      row.get("expected_gap_draws"),
        "combo_count":             row.get("combo_count"),
        "signal_quality":          sq,
        "deviation_note":          row.get("deviation_note"),
        "score_components":        score_components,
    }


# ---------------------------------------------------------------------------
# Rationale
# ---------------------------------------------------------------------------

def _build_rationale(
    session: str,
    detail_sums: list[dict[str, Any]],
    detail_root_sums: list[dict[str, Any]],
    detail_pairs: list[dict[str, Any]],
    shortlist: list[dict[str, Any]],
    sort_mode: str,
) -> str:
    parts: list[str] = [f"{session} [{sort_mode}]"]

    if detail_sums:
        s  = detail_sums[0]
        gr = s.get("gap_ratio")
        band = s.get("severity_band", "")
        if gr:
            parts.append(
                f"sum {s['value']} {s['draws_since']} draws absent "
                f"({gr:.1f}x expected; {band})"
            )
        else:
            parts.append(f"sum {s['value']} absent {s['draws_since']} draws")

    if detail_root_sums:
        rs = detail_root_sums[0]
        gr = rs.get("gap_ratio")
        if gr:
            parts.append(
                f"root sum {rs['value']} {rs['draws_since']} absent "
                f"({gr:.1f}x expected)"
            )
        else:
            parts.append(f"root sum {rs['value']} absent {rs['draws_since']} draws")

    if detail_pairs:
        p  = detail_pairs[0]
        gr = p.get("gap_ratio")
        if gr:
            parts.append(
                f"pair {p['value']} {p['draws_since']} absent ({gr:.1f}x expected)"
            )
        else:
            parts.append(f"pair {p['value']} absent {p['draws_since']} draws (baseline)")

    family_count = len({e["family"] for e in shortlist})
    parts.append(f"shortlist: {len(shortlist)} plays across {family_count} families")

    return ". ".join(parts) + "."


# ---------------------------------------------------------------------------
# Sort helpers
# ---------------------------------------------------------------------------

def _sort_rows(
    rows: list[dict[str, Any]],
    sort_mode: str,
    max_quant: int,
) -> list[dict[str, Any]]:
    if sort_mode == "deviation":
        return sorted(rows, key=lambda r: (r.get("gap_ratio") or 0.0), reverse=True)
    if sort_mode == "composite":
        return sorted(
            rows,
            key=lambda r: composite_score(
                r.get("draws_since", 0) or 0,
                r.get("combo_count", 1) or 1,
                max_quant,
                r.get("draws_processed", 0) or 0,
            ),
            reverse=True,
        )
    return rows  # "overdue" — already sorted by draws_since from _build_board


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_session_board(
    session: str,
    *,
    sort_mode: str = _DEFAULT_SORT_MODE,
) -> dict[str, Any]:
    """Return a daily board for one session.

    Compact section cards (top_sums, top_root_sums, top_pairs, top_combinations)
    preserve the stable contract: {family, value, draws_since, last_seen,
    why_flagged, subtype?, signal_quality, deviation_note}. No bulk keys.

    Detail section cards (*_detail) carry full deviation fields for the UI.

    sort_mode affects section card ordering. Shortlist is always composite.
    """
    if session not in _VALID_SESSIONS:
        raise ValueError(f"unrecognized session: {session!r}")
    if sort_mode not in _SORT_MODES:
        sort_mode = _DEFAULT_SORT_MODE

    sums_board      = build_sums_board(session, limit=_PULL)
    root_sums_board = build_root_sums_board(session, limit=_PULL)
    pairs_raw       = get_watchlist(session=session, item_type="pair", limit=_PULL)
    combos_raw      = get_watchlist(session=session, item_type="combination", limit=_PULL)
    pairs_enriched  = _enrich_pairs_from_runtime(pairs_raw, session)

    # Compute rank comparisons across all three modes (full list, not just top-N)
    sum_ranks  = _compute_rank_comparisons(sums_board,      SUM_MAX_QUANT)
    root_ranks = _compute_rank_comparisons(root_sums_board, ROOT_MAX_QUANT)

    sums_sorted      = _sort_rows(sums_board,      sort_mode, SUM_MAX_QUANT)
    root_sums_sorted = _sort_rows(root_sums_board, sort_mode, ROOT_MAX_QUANT)

    # Compact cards — stable contract
    top_sums      = [_compact_sum_card(r, "sum")      for r in sums_sorted[:_SECTION_SIZE]]
    top_root_sums = [_compact_sum_card(r, "root_sum") for r in root_sums_sorted[:_SECTION_SIZE]]
    top_pairs     = [_compact_pair_card(r)             for r in pairs_enriched[:_SECTION_SIZE]]
    top_combos    = [_compact_combo_card(r)            for r in combos_raw[:_SECTION_SIZE]]

    # Detail cards — full deviation payload + rank movement
    top_sums_detail = [
        _detail_sum_card(r, "sum",      sum_ranks.get(r["value"]), sort_mode)
        for r in sums_sorted[:_SECTION_SIZE]
    ]
    top_root_sums_detail = [
        _detail_sum_card(r, "root_sum", root_ranks.get(r["value"]), sort_mode)
        for r in root_sums_sorted[:_SECTION_SIZE]
    ]
    top_pairs_detail     = [_detail_pair_card(r)  for r in pairs_enriched[:_SECTION_SIZE]]
    top_combos_detail    = [_detail_combo_card(r) for r in combos_raw[:_SECTION_SIZE]]

    shortlist = _build_board_shortlist(
        session, sums_board, root_sums_board, pairs_enriched, combos_raw
    )

    generated_at    = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state           = load_stats_state()
    draws_processed = (
        state.get("by_session", {}).get(session, {}).get("draws_processed", 0)
    )
    rationale = _build_rationale(
        session, top_sums_detail, top_root_sums_detail, top_pairs_detail,
        shortlist, sort_mode,
    )

    # Mode provenance — explicit per-section messaging
    section_modes = {
        "sums": {
            "sorted_by":       sort_mode,
            "mode_sensitive":  True,
            "label":           f"Sorted by: {sort_mode}",
        },
        "root_sums": {
            "sorted_by":       sort_mode,
            "mode_sensitive":  True,
            "label":           f"Sorted by: {sort_mode}",
        },
        "pairs": {
            "sorted_by":       "composite",
            "mode_sensitive":  False,
            "label":           "Pairs use runtime deviation where available; mode has limited effect",
        },
        "combinations": {
            "sorted_by":       "overdue",
            "mode_sensitive":  False,
            "label":           "Combinations are baseline overdue-only; mode does not affect ranking",
        },
        "shortlist": {
            "sorted_by":       "composite",
            "mode_sensitive":  False,
            "label":           "Shortlist scoring: always composite",
        },
    }

    return {
        "session":                   session,
        # Compact — stable public contract
        "top_sums":                  top_sums,
        "top_root_sums":             top_root_sums,
        "top_pairs":                 top_pairs,
        "top_combinations":          top_combos,
        # Detail — full deviation payload for session UI
        "top_sums_detail":           top_sums_detail,
        "top_root_sums_detail":      top_root_sums_detail,
        "top_pairs_detail":          top_pairs_detail,
        "top_combinations_detail":   top_combos_detail,
        "shortlist":                 shortlist,
        "rationale":                 rationale,
        "section_modes":             section_modes,
        "metadata": {
            "session":               session,
            "source":                "engine-runtime",
            "analysis_window_days":  ANALYSIS_WINDOW_DAYS,
            "sync_window_days":      SYNC_WINDOW_DAYS,
            "draws_processed":       draws_processed,
            "last_processed_draw":   _last_processed_draw(session),
            "sort_mode":             sort_mode,
            "generated_at":          generated_at,
        },
    }
