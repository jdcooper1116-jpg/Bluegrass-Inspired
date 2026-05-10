from __future__ import annotations

from typing import Any

from bluegrass.app.dashboard import get_dashboard_payload


def _trim_items(items: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    keep_keys = [
        "item_type",
        "session",
        "subtype",
        "value",
        "times_drawn",
        "expected_times",
        "draws_since",
        "last_seen",
        "baseline_priority_score",
        "why_flagged",
        "source_url",
    ]
    trimmed: list[dict[str, Any]] = []
    for item in items[:limit]:
        trimmed.append({key: item.get(key) for key in keep_keys if key in item})
    return trimmed


def build_homepage_view() -> dict[str, Any]:
    payload = get_dashboard_payload()
    baseline = payload["baseline_summary"]
    spotlight = payload["spotlight"]

    hero_cards = [
        {"id": "runs", "label": "Baseline Runs", "value": baseline["total_runs"]},
        {"id": "pairs", "label": "Pair Rows", "value": baseline["pair_rows"]},
        {"id": "combinations", "label": "Combination Rows", "value": baseline["combination_rows"]},
        {
            "id": "jurisdiction",
            "label": "Jurisdiction",
            "value": ", ".join(baseline["jurisdictions"]),
        },
    ]

    session_spotlights = {
        "midday": _trim_items(spotlight.get("midday_pairs", []), limit=5),
        "evening": _trim_items(spotlight.get("evening_pairs", []), limit=5),
        "night": _trim_items(spotlight.get("night_pairs", []), limit=5),
    }

    priority_combos = {
        "midday": _trim_items(spotlight.get("midday_combos", []), limit=5),
        "evening": _trim_items(spotlight.get("evening_combos", []), limit=5),
        "night": _trim_items(spotlight.get("night_combos", []), limit=5),
    }

    metadata = {
        "sessions": baseline["sessions"],
        "jurisdictions": baseline["jurisdictions"],
        "game_family": baseline["game_family"],
        "source_sections": ["baseline_summary", "spotlight"],
    }

    return {
        "hero_cards": hero_cards,
        "session_spotlights": session_spotlights,
        "priority_combos": priority_combos,
        "metadata": metadata,
    }


# SESSION_HOMEPAGE_VIEW
_VALID_SESSION_NAMES = {
    "midday": "Midday",
    "evening": "Evening",
    "night": "Night",
}


def _normalize_sessions(values: list[str]) -> list[str]:
    discovered: set[str] = set()
    allowed_order = ["Midday", "Evening", "Night"]

    for value in values:
        for part in str(value).split("|"):
            part = part.strip()
            if part in allowed_order:
                discovered.add(part)

    return [session for session in allowed_order if session in discovered]


_original_build_homepage_view = build_homepage_view


def build_homepage_view() -> dict[str, Any]:
    payload = _original_build_homepage_view()
    metadata = dict(payload.get("metadata", {}))
    metadata["sessions"] = _normalize_sessions(list(metadata.get("sessions", [])))
    payload["metadata"] = metadata
    return payload


def build_session_homepage_view(session: str) -> dict[str, Any]:
    session_key = session.strip().lower()
    if session_key not in _VALID_SESSION_NAMES:
        raise ValueError(f"Unsupported session: {session}")

    session_label = _VALID_SESSION_NAMES[session_key]
    payload = build_homepage_view()

    return {
        "session": session_label,
        "hero_cards": list(payload["hero_cards"]) + [
            {"id": "selected_session", "label": "Selected Session", "value": session_label}
        ],
        "pair_spotlight": list(payload["session_spotlights"][session_key][:5]),
        "combo_spotlight": list(payload["priority_combos"][session_key][:5]),
        "metadata": {
            **payload["metadata"],
            "selected_session": session_label,
        },
    }
