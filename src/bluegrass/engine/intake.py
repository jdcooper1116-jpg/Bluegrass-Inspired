"""Engine result intake adapter – normalize raw draw payloads into EngineResult."""

from __future__ import annotations

from dataclasses import dataclass

_SESSION_ALIASES: dict[str, str] = {
    "midday": "Midday",
    "mid": "Midday",
    "afternoon": "Midday",
    "evening": "Evening",
    "eve": "Evening",
    "night": "Night",
    "ngt": "Night",
    "late": "Night",
}

VALID_SESSIONS = frozenset({"Midday", "Evening", "Night"})


@dataclass(frozen=True)
class EngineResult:
    date: str          # "YYYY-MM-DD"
    session: str       # "Midday" | "Evening" | "Night"
    result: str        # 3-digit string, leading zeros preserved e.g. "012"
    jurisdiction: str  # e.g. "GA"
    game_family: str   # e.g. "Pick 3"


def normalize_result(raw: dict) -> EngineResult:
    """Normalize a raw engine payload into an EngineResult.

    Accepts flexible key names; preserves leading zeros; raises ValueError for
    any missing or unrecognized required field.
    """
    date_raw = str(
        raw.get("date") or raw.get("draw_date") or raw.get("drawn_at") or ""
    )
    if not date_raw:
        raise ValueError("raw payload missing date field")
    date = date_raw[:10]  # trim datetime strings to YYYY-MM-DD

    session_raw = str(raw.get("session") or raw.get("draw_session") or "")
    session = _SESSION_ALIASES.get(session_raw.lower(), session_raw)
    if session not in VALID_SESSIONS:
        raise ValueError(f"unrecognized session: {session_raw!r}")

    result_raw = str(
        raw.get("result")
        or raw.get("winning_number")
        or raw.get("draw")
        or raw.get("number")
        or ""
    )
    digits = "".join(c for c in result_raw if c.isdigit())
    if not digits:
        raise ValueError("raw payload missing result digits")
    result = digits.zfill(3)[:3]

    jurisdiction = str(raw.get("jurisdiction") or raw.get("state") or "GA")
    game_family = str(raw.get("game_family") or "Pick 3")

    return EngineResult(
        date=date,
        session=session,
        result=result,
        jurisdiction=jurisdiction,
        game_family=game_family,
    )
