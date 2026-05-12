"""Runtime stats state – incremental overlay on top of the baseline seed.

State is persisted to data/runtime/stats_state.json and never mutates the
baseline seed CSVs. An absent file means no draws have been processed yet.

Write safety
------------
save_stats_state() writes atomically: JSON is serialized to a sibling temp
file (stats_state.json.tmp) on the same filesystem, fsynced, then renamed
over the target with os.replace().  os.replace() is atomic on POSIX and
NTFS — readers always see either the complete previous state or the complete
new state, never a partial write.

Read safety
-----------
load_stats_state() retries up to _READ_RETRIES times on JSONDecodeError,
with a short sleep between attempts.  This handles the tiny window between
os.replace() completing on one process and the kernel flushing the dentry
cache on another (rare, but possible on network/overlay filesystems).  If
all retries are exhausted a RuntimeError is raised — partial data is never
silently returned.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


RUNTIME_DIR = _repo_root() / "data" / "runtime"
STATS_STATE_PATH = RUNTIME_DIR / "stats_state.json"
_STATS_STATE_TMP  = RUNTIME_DIR / "stats_state.json.tmp"

_READ_RETRIES  = 3
_READ_RETRY_S  = 0.02   # 20 ms between retries


def load_stats_state() -> dict[str, Any]:
    """Return persisted runtime state, or empty dict if none exists yet.

    Retries up to _READ_RETRIES times on JSONDecodeError to tolerate the
    vanishingly small window where a concurrent atomic rename has not yet
    been visible to this reader.  If the file is absent, returns {} without
    retrying (that is the normal cold-start / post-reset condition).
    """
    if not STATS_STATE_PATH.exists():
        return {}

    last_exc: Exception | None = None
    for attempt in range(_READ_RETRIES):
        try:
            with STATS_STATE_PATH.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except json.JSONDecodeError as exc:
            last_exc = exc
            if attempt < _READ_RETRIES - 1:
                time.sleep(_READ_RETRY_S)
        except FileNotFoundError:
            # File was deleted between the exists() check and open() — treat
            # as cold start rather than an error.
            return {}

    raise RuntimeError(
        f"stats_state.json contains invalid JSON after {_READ_RETRIES} read attempts "
        f"(last error: {last_exc}).  The file may be corrupt — delete it and run "
        f"POST /refresh/rebuild-runtime to recover."
    ) from last_exc


def save_stats_state(state: dict[str, Any]) -> None:
    """Persist runtime state atomically, creating data/runtime/ if needed.

    Writes to a sibling .tmp file, fsyncs, then renames over the target.
    Readers always see a complete file — never a partial write.
    """
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, sort_keys=True)
    tmp = _STATS_STATE_TMP
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, STATS_STATE_PATH)
    except BaseException:
        # Best-effort cleanup of temp file on any failure.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def reset_stats_state() -> None:
    """Delete the runtime state file. Used in tests and manual resets."""
    if STATS_STATE_PATH.exists():
        STATS_STATE_PATH.unlink()
    # Also clean up any leftover tmp file from an interrupted write.
    _STATS_STATE_TMP.unlink(missing_ok=True)

