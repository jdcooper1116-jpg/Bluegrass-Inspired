"""Runtime stats state – incremental overlay on top of the baseline seed.

State is persisted to data/runtime/stats_state.json and never mutates the
baseline seed CSVs. An absent file means no draws have been processed yet.

Write safety
------------
save_stats_state() is protected by a process-level threading.Lock so
concurrent scheduler ticks, request handlers, and startup bootstrap threads
never stomp each other's writes.

Within each write, a unique temp file is created with tempfile.mkstemp() in
the same directory (same filesystem) as the final file.  The payload is
written through the mkstemp fd, fsynced, then the temp file is atomically
renamed over the target with os.replace().  Because each write uses a unique
temp path, concurrent writes can never collide on the same temp file.

Read safety
-----------
load_stats_state() retries up to _READ_RETRIES times on JSONDecodeError,
with a short sleep between attempts.  This handles the tiny window between
os.replace() completing on one process and the kernel flushing the dentry
cache on another (rare, but possible on network/overlay filesystems).  If
all retries are exhausted a RuntimeError is raised — partial data is never
silently returned.

Concurrency scope
-----------------
The threading.Lock protects within one process (one uvicorn/gunicorn worker).
Multi-process deployments would require a cross-process file lock; that is
out of scope for the current Railway single-worker architecture.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


RUNTIME_DIR = _repo_root() / "data" / "runtime"
STATS_STATE_PATH = RUNTIME_DIR / "stats_state.json"

_READ_RETRIES = 3
_READ_RETRY_S = 0.02   # 20 ms between retries

# Process-level write serialiser.  Acquired for the duration of each
# save_stats_state() call (~milliseconds).  Never held across I/O retries.
_WRITE_LOCK = threading.Lock()


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
            # File was deleted between exists() check and open() — cold start.
            return {}

    raise RuntimeError(
        f"stats_state.json contains invalid JSON after {_READ_RETRIES} read attempts "
        f"(last error: {last_exc}).  The file may be corrupt — delete it and run "
        f"POST /refresh/rebuild-runtime to recover."
    ) from last_exc


def save_stats_state(state: dict[str, Any]) -> None:
    """Persist runtime state atomically, creating data/runtime/ if needed.

    Uses a unique temp file per call (tempfile.mkstemp) so concurrent callers
    never collide on the same temp path.  Serialises via _WRITE_LOCK so
    concurrent threads within this process do not interleave writes.

    Steps:
      1. Acquire _WRITE_LOCK (serialise within process)
      2. Serialise JSON to bytes
      3. mkstemp() in same directory → unique temp file
      4. Write through fd, fsync, close
      5. os.replace(temp, target) — atomic rename
    """
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, sort_keys=True).encode("utf-8")

    with _WRITE_LOCK:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(RUNTIME_DIR), prefix="ss_", suffix=".tmp"
        )
        try:
            try:
                os.write(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp_path, STATS_STATE_PATH)
        except BaseException:
            # Best-effort cleanup of the unique temp file on any failure.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def reset_stats_state() -> None:
    """Delete the runtime state file. Used in tests and manual resets.

    Also cleans up any stale ss_*.tmp files left by interrupted writes.
    """
    if STATS_STATE_PATH.exists():
        STATS_STATE_PATH.unlink()
    # Clean up leftover unique temp files from interrupted writes.
    if RUNTIME_DIR.exists():
        for stale in RUNTIME_DIR.glob("ss_*.tmp"):
            try:
                stale.unlink()
            except OSError:
                pass
