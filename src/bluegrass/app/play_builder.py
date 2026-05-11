"""Thin view-model adapter for the Play Builder UI.

Composes build_session_convergence + build_session_audit into the
shape the Play Builder templates consume directly.  Backend builders
are never changed here; this is presentation-only glue.
"""

from __future__ import annotations

from typing import Any

from bluegrass.app.audit import build_audit_overview, build_session_audit
from bluegrass.app.convergence import build_convergence_overview, build_session_convergence
from bluegrass.app.playlist import _VALID_SESSIONS

_SESSIONS = ("Midday", "Evening", "Night")
_GAME_LABEL = "Georgia Cash 3"

_CONFIDENCE: dict[int, tuple[str, str]] = {
    1: ("Highest Convergence", "Strongest Signals"),
    2: ("Strong Signals", "Multiple Matches"),
    3: ("Moderate Signals", "Value Plays"),
}

_PAIR_POS_LABEL: dict[str, str] = {
    "front": "Front Pair",
    "back": "Back Pair",
    "split": "Split Pair",
}


# ---------------------------------------------------------------------------
# Card enrichment
# ---------------------------------------------------------------------------

def _play_type(sig: dict[str, Any]) -> str:
    s = bool(sig.get("straight_match"))
    b = bool(sig.get("box_family_match"))
    if s and b:
        return "both"
    if s:
        return "straight"
    if b:
        return "box"
    return "any"


def _human_rationale(c: dict[str, Any]) -> str:
    sig = c["signals"]
    parts: list[str] = []
    if sig.get("sum_match"):
        rank = sig.get("sum_rank")
        rank_str = f" #{rank}" if rank else ""
        parts.append(f"Sum {sig['sum_value']}{rank_str}")
    if sig.get("root_sum_match"):
        parts.append(f"Root {sig['root_sum_value']}")
    hits = sig.get("pair_hits") or []
    if hits:
        labels = [h.replace("_", " ").title() for h in hits[:2]]
        parts.append(", ".join(labels))
    if sig.get("straight_match"):
        parts.append(f"Straight #{sig['straight_rank']}")
    if sig.get("box_family_match"):
        parts.append(f"Box {sig['box_family']}")
    return " · ".join(parts) if parts else "Signal convergence"


def _enrich_play_card(c: dict[str, Any]) -> dict[str, Any]:
    tier = c["tier"]
    cl, cd = _CONFIDENCE.get(tier, ("", ""))
    return {
        **c,
        "confidence_label": cl,
        "confidence_desc": cd,
        "play_type": _play_type(c["signals"]),
        "human_rationale": _human_rationale(c),
    }


# ---------------------------------------------------------------------------
# Family aggregation helpers
# ---------------------------------------------------------------------------

def _pair_families(pairs_by_subtype: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Deduplicate across subtypes, keeping the highest draws_since per pair value."""
    best: dict[str, dict[str, Any]] = {}
    for subtype, entries in pairs_by_subtype.items():
        pos = subtype.split("_")[0]
        for e in entries:
            val = e["value"]
            ds = e.get("draws_since") or 0
            if val not in best or ds > (best[val].get("draws_since") or 0):
                best[val] = {
                    "pair": val,
                    "position": pos,
                    "position_label": _PAIR_POS_LABEL.get(pos, pos.title()),
                    "draws_since": ds,
                }
    return sorted(best.values(), key=lambda x: x["draws_since"], reverse=True)[:12]


def _box_families(box_combos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group by sorted-digit family, keep highest draws_since per family."""
    best: dict[str, dict[str, Any]] = {}
    for e in box_combos:
        fam = "".join(sorted(e["value"]))
        ds = e.get("draws_since") or 0
        if fam not in best or ds > (best[fam].get("draws_since") or 0):
            best[fam] = {
                "family": fam,
                "example": e["value"],
                "draws_since": ds,
                "rank": e["rank"],
            }
    return sorted(best.values(), key=lambda x: x["draws_since"], reverse=True)[:8]


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------

def build_play_builder_session(session: str) -> dict[str, Any]:
    """View model for the Play Builder session page.

    Combines convergence signal_pools (top-10 per type) with tiered play
    candidates and audit freshness data.
    """
    if session not in _VALID_SESSIONS:
        raise ValueError(f"unrecognized session: {session!r}")

    conv = build_session_convergence(session)
    audit = build_session_audit(session)
    pools = conv["signal_pools"]

    plays_by_tier: dict[int, list[dict[str, Any]]] = {1: [], 2: [], 3: []}
    for c in conv["candidates"]:
        plays_by_tier[c["tier"]].append(_enrich_play_card(c))

    return {
        "session": session,
        "game_label": f"{_GAME_LABEL} {session}",
        "rail": {
            "due_sums": pools["sums"],
            "due_root_sums": pools["root_sums"],
            "due_pairs": pools["pairs_by_subtype"],
            "due_straight_combos": pools["straight_combos"],
            "due_box_combos": pools["box_combos"],
            "pattern_singles": pools["singles"],
            "pattern_doubles": pools["doubles"],
            "pattern_triples": pools["triples"],
        },
        "plays": {
            "tier_1": plays_by_tier[1],
            "tier_2": plays_by_tier[2],
            "tier_3": plays_by_tier[3],
            "tier_1_count": conv["tier_1_count"],
            "tier_2_count": conv["tier_2_count"],
            "tier_3_count": conv["tier_3_count"],
            "total": conv["total_candidates"],
        },
        "straight_plays": pools["straight_combos"][:10],
        "box_plays": pools["box_combos"][:10],
        "pair_families": _pair_families(pools["pairs_by_subtype"]),
        "box_families": _box_families(pools["box_combos"]),
        "audit": audit,
        "metadata": conv["metadata"],
    }


def build_play_builder_overview() -> dict[str, Any]:
    """View model for the Play Builder overview/dashboard page."""
    overview_conv = build_convergence_overview()
    audit_ov = build_audit_overview()

    session_cards: dict[str, Any] = {}
    for sess in _SESSIONS:
        conv = build_session_convergence(sess)
        sa = audit_ov["sessions"][sess]
        pools = conv["signal_pools"]
        session_cards[sess] = {
            "session": sess,
            "game_label": f"{_GAME_LABEL} {sess}",
            "freshness_status": sa["freshness_status"],
            "draws_behind": sa.get("draws_behind"),
            "coverage": sa["coverage"],
            "tier_1_count": conv["tier_1_count"],
            "tier_2_count": conv["tier_2_count"],
            "tier_3_count": conv["tier_3_count"],
            "total_candidates": conv["total_candidates"],
            "last_processed_draw": conv["metadata"]["last_processed_draw"],
            "top_sum": pools["sums"][0] if pools["sums"] else None,
            "top_root": pools["root_sums"][0] if pools["root_sums"] else None,
            "top_candidates": [_enrich_play_card(c) for c in conv["candidates"][:4]],
        }

    return {
        "session_cards": session_cards,
        "multi_session": overview_conv["multi_session_candidates"],
        "overview_supported": overview_conv["overview_supported_candidates"],
        "audit": audit_ov,
        "metadata": overview_conv["metadata"],
    }
