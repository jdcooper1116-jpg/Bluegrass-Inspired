"""Read-only loaders for the Bluegrass baseline seed packet."""

from __future__ import annotations

from csv import DictReader
from functools import lru_cache
import json
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


BASELINE_DIR = _repo_root() / "data" / "baseline"
RUNS_CSV = BASELINE_DIR / "seeds" / "runs.csv"
PAIRS_CSV = BASELINE_DIR / "seeds" / "pairs.csv"
COMBINATIONS_CSV = BASELINE_DIR / "seeds" / "combinations.csv"
PRIORITY_SHORTLIST_CSV = BASELINE_DIR / "seeds" / "priority_shortlist.csv"
MANIFEST_JSON = BASELINE_DIR / "meta" / "manifest.json"


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in DictReader(handle)]


@lru_cache(maxsize=1)
def load_baseline_manifest() -> dict[str, Any]:
    with MANIFEST_JSON.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_baseline_runs() -> list[dict[str, str]]:
    return _read_csv_rows(RUNS_CSV)


@lru_cache(maxsize=1)
def load_baseline_pairs() -> list[dict[str, str]]:
    return _read_csv_rows(PAIRS_CSV)


@lru_cache(maxsize=1)
def load_baseline_combinations() -> list[dict[str, str]]:
    return _read_csv_rows(COMBINATIONS_CSV)


@lru_cache(maxsize=1)
def load_priority_shortlist() -> list[dict[str, str]]:
    return _read_csv_rows(PRIORITY_SHORTLIST_CSV)


def baseline_packet_summary() -> dict[str, Any]:
    manifest = load_baseline_manifest()
    summary = manifest.get("summary", {})
    return {
        "total_runs": summary.get("total_runs", 0),
        "pair_rows": summary.get("pair_rows", 0),
        "combination_rows": summary.get("combination_rows", 0),
        "sessions": list(summary.get("sessions", [])),
        "jurisdictions": list(summary.get("jurisdictions", [])),
        "game_family": list(summary.get("game_family", [])),
    }


def filter_priority_shortlist(
    *,
    item_type: str | None = None,
    session: str | None = None,
    subtype: str | None = None,
    limit: int | None = None,
) -> list[dict[str, str]]:
    rows = load_priority_shortlist()

    filtered = [
        row
        for row in rows
        if (item_type is None or row["item_type"] == item_type)
        and (session is None or row["session"] == session)
        and (subtype is None or row["subtype"] == subtype)
    ]

    filtered.sort(
        key=lambda row: float(row.get("baseline_priority_score") or "0"),
        reverse=True,
    )

    if limit is not None:
        return filtered[:limit]
    return filtered
