"""Forecast ledger — store pre-draw snapshots and score them post-draw.

Snapshots are written to data/runtime/forecasts/YYYY-MM-DD_Session.json.
Each file is write-once: the first call for a (date, session) pair stores
the forecast. Subsequent calls before the result is scored are no-ops.

Scoring is called after a draw result is available and marks exact/box/pair/
sum/root hits in the same file.
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


def take_snapshot(session: str, vm: dict[str, Any], *, draw_date: str | None = None) -> bool:
    """Store a pre-draw forecast snapshot. Write-once — returns False if already stored.

    `vm` is the view-model dict from build_play_builder_session(session).
    `draw_date` defaults to today (YYYY-MM-DD).
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

    snap: dict[str, Any] = {
        "date": today,
        "session": session,
        "snapshot_at": datetime.now(UTC).isoformat(),
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

    result_sum = str(digit_sum(result))
    result_root = str(root_sum(result))
    result_box = "".join(sorted(result))
    result_front = result[0] + result[1]
    result_back = result[1] + result[2]
    result_split = result[0] + result[2]

    top_pairs = snap.get("top_pairs", {}) or {}

    hits: dict[str, Any] = {
        "exact":     result in tier_1_numbers,
        "box":       result_box in box_set,
        "pair_hit":  (
            result_front == (top_pairs.get("front") or "")
            or result_back == (top_pairs.get("back") or "")
            or result_split == (top_pairs.get("split") or "")
        ),
        "sum_hit":   result_sum == (snap.get("top_sum") or ""),
        "root_hit":  result_root == (snap.get("top_root") or ""),
        "near_miss": result_box in box_set and result not in tier_1_numbers,
    }
    hits["any_hit"] = any(hits[k] for k in ("exact", "box", "pair_hit", "sum_hit", "root_hit"))

    snap["result"] = result
    snap["scored_at"] = datetime.now(UTC).isoformat()
    snap["hits"] = hits
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
