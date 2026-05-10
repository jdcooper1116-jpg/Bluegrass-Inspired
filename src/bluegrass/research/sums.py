"""Sums and root-sums boards derived from baseline combination data.

Baseline straight combos provide the historical draws_since and last_seen.
The runtime stats overlay (from stats_store) is applied on top so that draws
ingested via refresh_from_result are immediately reflected without touching
the seed CSVs.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from bluegrass.research.baseline import load_baseline_combinations
from bluegrass.research.stats_store import load_stats_state


# ---------------------------------------------------------------------------
# Pure math helpers (no I/O)
# ---------------------------------------------------------------------------

def digit_sum(value: str) -> int:
    """Sum of digit characters in a Pick 3 result string, e.g. '123' → 6."""
    return sum(int(c) for c in value)


def root_sum(value: str) -> int:
    """Digital root for Pick 3: range 0-9 where multiples of 9 map to 9 (not 0).

    '000' is the only value that returns 0.
    """
    s = digit_sum(value)
    if s == 0:
        return 0
    r = s % 9
    return r if r != 0 else 9


# ---------------------------------------------------------------------------
# Baseline aggregation
# ---------------------------------------------------------------------------

def _combos_for_session(session: str) -> list[dict[str, str]]:
    """Return straight combination rows for an exact sessions_scope match."""
    return [
        r for r in load_baseline_combinations()
        if r["sessions_scope"] == session
        and r["subtype"] == "All straight combinations"
    ]


def _aggregate(combos: list[dict[str, str]], key_fn: Any) -> dict[int, dict[str, Any]]:
    """Group combo rows by key_fn(combo_value) and aggregate stats."""
    groups: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"draws_since": float("inf"), "last_seen": "", "times_drawn": 0, "combos": 0}
    )
    for row in combos:
        key = key_fn(row["combo_value"])
        g = groups[key]
        ds = int(row["draws_since"]) if row.get("draws_since") else 0
        g["draws_since"] = min(g["draws_since"], ds)
        if row.get("last_seen", "") > g["last_seen"]:
            g["last_seen"] = row["last_seen"]
        g["times_drawn"] += int(row.get("times_drawn") or 0)
        g["combos"] += 1
    for g in groups.values():
        if g["draws_since"] == float("inf"):
            g["draws_since"] = 0
    return dict(groups)


# ---------------------------------------------------------------------------
# Runtime overlay
# ---------------------------------------------------------------------------

def _apply_overlay(
    groups: dict[int, dict[str, Any]],
    family: str,
    session: str,
) -> dict[int, dict[str, Any]]:
    """Merge runtime incremental state over baseline-derived groups."""
    runtime = (
        load_stats_state()
        .get("by_session", {})
        .get(session, {})
        .get(family, {})
    )
    for key_str, entry in runtime.items():
        key = int(key_str)
        if key not in groups:
            groups[key] = {"draws_since": 0, "last_seen": "", "times_drawn": 0, "combos": 0}
        g = groups[key]
        g["draws_since"] = entry.get("draws_since", g["draws_since"])
        if entry.get("last_seen", "") > g["last_seen"]:
            g["last_seen"] = entry["last_seen"]
        g["times_drawn"] += entry.get("times_seen_runtime", 0)
    return groups


# ---------------------------------------------------------------------------
# Public board builders
# ---------------------------------------------------------------------------

def build_sums_board(session: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    """All digit-sum groups for a session, sorted most-overdue first.

    Each entry: family, value (str), draws_since, last_seen, times_drawn,
    combo_count, session.
    """
    combos = _combos_for_session(session)
    groups = _aggregate(combos, digit_sum)
    groups = _apply_overlay(groups, "sums", session)

    rows = [
        {
            "family": "sum",
            "value": str(s),
            "draws_since": g["draws_since"],
            "last_seen": g["last_seen"],
            "times_drawn": g["times_drawn"],
            "combo_count": g["combos"],
            "session": session,
        }
        for s, g in groups.items()
    ]
    rows.sort(key=lambda r: r["draws_since"], reverse=True)
    return rows[:limit] if limit is not None else rows


def build_root_sums_board(session: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    """All root-sum groups for a session, sorted most-overdue first."""
    combos = _combos_for_session(session)
    groups = _aggregate(combos, root_sum)
    groups = _apply_overlay(groups, "root_sums", session)

    rows = [
        {
            "family": "root_sum",
            "value": str(rs),
            "draws_since": g["draws_since"],
            "last_seen": g["last_seen"],
            "times_drawn": g["times_drawn"],
            "combo_count": g["combos"],
            "session": session,
        }
        for rs, g in groups.items()
    ]
    rows.sort(key=lambda r: r["draws_since"], reverse=True)
    return rows[:limit] if limit is not None else rows
