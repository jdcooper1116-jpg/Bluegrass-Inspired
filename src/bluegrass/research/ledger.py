"""Forecast ledger — store pre-draw snapshots and score them post-draw.

Snapshots are written to data/runtime/forecasts/YYYY-MM-DD_Session.json.
Each file is write-once: the first call for a (date, session) pair stores
the forecast. Subsequent calls before the result is scored are no-ops.

Scoring is called after a draw result is available and marks exact/box/pair/
sum/root hits in the same file, together with explicit tier attribution and
a human-readable verdict.
"""

from __future__ import annotations

import json
from datetime import date as _date_type
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bluegrass.research.sums import digit_sum, root_sum

_REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER_DIR = _REPO_ROOT / "data" / "runtime" / "forecasts"


def _forecast_path(draw_date: str, session: str) -> Path:
    return LEDGER_DIR / f"{draw_date}_{session}.json"


def _load(draw_date: str, session: str) -> dict[str, Any] | None:
    path = _forecast_path(draw_date, session)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _save(snap: dict[str, Any]) -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    path = _forecast_path(snap["date"], snap["session"])
    with path.open("w", encoding="utf-8") as fh:
        json.dump(snap, fh, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Pure attribution helpers (no I/O)
# ---------------------------------------------------------------------------

def _find_tier(result: str, snap: dict[str, Any]) -> int | None:
    """Return the first tier (1, 2, or 3) that contains result as an exact match.

    Returns None if the result is not present in any tier.
    """
    for tier_num in (1, 2, 3):
        numbers = {c["number"] for c in snap.get(f"tier_{tier_num}", [])}
        if result in numbers:
            return tier_num
    return None


def _find_box_tier(result: str, snap: dict[str, Any]) -> int | None:
    """Return the first tier that contains a box-equivalent of result.

    Box-equivalent = digits sorted ascending. Scans tier 1 first so the
    highest-confidence tier is attributed.
    Returns None if no box-form match exists in any tier.
    """
    result_box = "".join(sorted(result))
    for tier_num in (1, 2, 3):
        boxes = {"".join(sorted(c["number"])) for c in snap.get(f"tier_{tier_num}", [])}
        if result_box in boxes:
            return tier_num
    return None


def _compute_verdict(
    exact_tier: int | None,
    box_tier: int | None,
    support_channels: list[str],
) -> str:
    """Return a human-readable verdict string.

    Priority: exact > box > support > miss.
    """
    if exact_tier is not None:
        return f"Exact hit — Tier {exact_tier}"
    if box_tier is not None:
        return f"Box hit — Tier {box_tier}"
    if support_channels:
        return "Support hit — " + " + ".join(support_channels)
    return "Miss"


# ---------------------------------------------------------------------------
# Public ledger operations
# ---------------------------------------------------------------------------

def take_snapshot(
    session: str,
    vm: dict[str, Any],
    *,
    draw_date: str | None = None,
    freshness_meta: dict[str, Any] | None = None,
) -> bool:
    """Store a pre-draw forecast snapshot. Write-once — returns False if already stored.

    `vm` is the view-model dict from build_play_builder_session(session).
    `draw_date` defaults to today (YYYY-MM-DD).
    `freshness_meta` is an optional dict with keys:
        snapshot_freshness_status   — "fresh" | "stale" | "baseline-only" | "engine-unknown"
        snapshot_source_state_date  — last processed draw date at snapshot time
        snapshot_draws_behind       — int | None
    """
    today = draw_date or _date_type.today().isoformat()
    if _load(today, session) is not None:
        return False  # already snapshotted today

    plays = vm.get("plays", {})
    rail = vm.get("rail", {})

    top_sum = None
    due_sums = rail.get("due_sums") or []
    if due_sums:
        top_sum = due_sums[0].get("value")

    top_root = None
    due_roots = rail.get("due_root_sums") or []
    if due_roots:
        top_root = due_roots[0].get("value")

    top_pairs: dict[str, str | None] = {"front": None, "back": None, "split": None}
    for pf in vm.get("pair_families") or []:
        pos = pf.get("position")
        if pos in top_pairs and top_pairs[pos] is None:
            top_pairs[pos] = pf.get("pair")

    fm = freshness_meta or {}

    snap: dict[str, Any] = {
        "date": today,
        "session": session,
        "snapshot_at": datetime.now(UTC).isoformat(),
        # Freshness metadata — records the state quality at snapshot time
        "snapshot_freshness_status":   fm.get("snapshot_freshness_status", "unknown"),
        "snapshot_source_state_date":  fm.get("snapshot_source_state_date"),
        "snapshot_draws_behind":       fm.get("snapshot_draws_behind"),
        # Frozen forecast contents
        "tier_1": [
            {"number": c["number"], "score": c.get("score", 0), "signals": c.get("signals", {})}
            for c in plays.get("tier_1", [])
        ],
        "tier_2": [
            {"number": c["number"], "score": c.get("score", 0), "signals": c.get("signals", {})}
            for c in plays.get("tier_2", [])
        ],
        "tier_3": [
            {"number": c["number"], "score": c.get("score", 0), "signals": c.get("signals", {})}
            for c in plays.get("tier_3", [])
        ],
        "top_sum": top_sum,
        "top_root": top_root,
        "top_pairs": top_pairs,
        # Filled in after the draw
        "result": None,
        "scored_at": None,
        "hits": None,
    }
    _save(snap)
    return True


def score_forecast(draw_date: str, session: str, result: str) -> dict[str, Any]:
    """Score a stored forecast against the actual draw result.

    Idempotent — calling with the same result twice returns the same hits dict.
    Returns {} if no snapshot exists for (draw_date, session).

    The returned hits dict contains both the original boolean flags and the
    richer attribution fields added in this version:
        result_in_tier      — int | None (which tier has the exact result)
        result_box_in_tier  — int | None (which tier has a box-form match)
        support_channels    — list[str] (["pair"], ["sum", "root"], etc.)
        verdict             — str (human-readable outcome label)
    """
    snap = _load(draw_date, session)
    if snap is None:
        return {}
    if snap.get("result") is not None:
        return snap.get("hits", {})

    all_numbers = (
        [c["number"] for c in snap.get("tier_1", [])]
        + [c["number"] for c in snap.get("tier_2", [])]
        + [c["number"] for c in snap.get("tier_3", [])]
    )
    tier_1_numbers = {c["number"] for c in snap.get("tier_1", [])}
    box_set = {"".join(sorted(n)) for n in all_numbers}

    result_sum   = str(digit_sum(result))
    result_root  = str(root_sum(result))
    result_box   = "".join(sorted(result))
    result_front = result[0] + result[1]
    result_back  = result[1] + result[2]
    result_split = result[0] + result[2]

    top_pairs = snap.get("top_pairs", {}) or {}

    # ── Original boolean flags (unchanged contract) ──────────────────────
    pair_hit = (
        result_front == (top_pairs.get("front") or "")
        or result_back  == (top_pairs.get("back")  or "")
        or result_split == (top_pairs.get("split") or "")
    )
    sum_hit  = result_sum  == (snap.get("top_sum")  or "")
    root_hit = result_root == (snap.get("top_root") or "")

    hits: dict[str, Any] = {
        "exact":     result in tier_1_numbers,
        "box":       result_box in box_set,
        "pair_hit":  pair_hit,
        "sum_hit":   sum_hit,
        "root_hit":  root_hit,
        "near_miss": result_box in box_set and result not in tier_1_numbers,
    }
    hits["any_hit"] = any(hits[k] for k in ("exact", "box", "pair_hit", "sum_hit", "root_hit"))

    # ── Richer attribution (additive — does not remove existing keys) ────
    exact_tier = _find_tier(result, snap)
    box_tier   = _find_box_tier(result, snap)

    support_channels: list[str] = []
    if pair_hit:  support_channels.append("pair")
    if sum_hit:   support_channels.append("sum")
    if root_hit:  support_channels.append("root")

    hits["result_in_tier"]     = exact_tier
    hits["result_box_in_tier"] = box_tier
    hits["support_channels"]   = support_channels
    hits["verdict"]            = _compute_verdict(exact_tier, box_tier, support_channels)

    snap["result"]    = result
    snap["scored_at"] = datetime.now(UTC).isoformat()
    snap["hits"]      = hits
    _save(snap)
    return hits


def load_forecast(draw_date: str, session: str) -> dict[str, Any] | None:
    """Return the stored snapshot for (draw_date, session), or None."""
    return _load(draw_date, session)


def list_forecasts(session: str | None = None) -> list[dict[str, Any]]:
    """Return all forecast snapshots, optionally filtered by session, sorted date desc."""
    if not LEDGER_DIR.exists():
        return []
    results = []
    for path in sorted(LEDGER_DIR.glob("*.json"), reverse=True):
        try:
            with path.open("r", encoding="utf-8") as fh:
                snap = json.load(fh)
            if session is None or snap.get("session") == session:
                results.append(snap)
        except (json.JSONDecodeError, OSError):
            continue
    return results
