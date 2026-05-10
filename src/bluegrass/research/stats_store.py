"""Runtime stats state – incremental overlay on top of the baseline seed.

State is persisted to data/runtime/stats_state.json and never mutates the
baseline seed CSVs. An absent file means no draws have been processed yet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


RUNTIME_DIR = _repo_root() / "data" / "runtime"
STATS_STATE_PATH = RUNTIME_DIR / "stats_state.json"


def load_stats_state() -> dict[str, Any]:
    """Return persisted runtime state, or empty dict if none exists yet."""
    if not STATS_STATE_PATH.exists():
        return {}
    with STATS_STATE_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_stats_state(state: dict[str, Any]) -> None:
    """Persist runtime state, creating data/runtime/ if needed."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with STATS_STATE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)


def reset_stats_state() -> None:
    """Delete the runtime state file. Used in tests and manual resets."""
    if STATS_STATE_PATH.exists():
        STATS_STATE_PATH.unlink()
