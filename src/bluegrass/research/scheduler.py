"""Background catch-up scheduler — periodically applies new draws automatically.

Started once at app startup. Uses a daemon thread so it dies with the process.
The catch-up is idempotent: already-processed draw IDs are skipped.

Configure interval via env var BLUEGRASS_REFRESH_INTERVAL_SECONDS (default 900 = 15 min).
"""

from __future__ import annotations

import logging
import os
import threading
import time

_log = logging.getLogger(__name__)

_INTERVAL_SECONDS = int(os.environ.get("BLUEGRASS_REFRESH_INTERVAL_SECONDS", "900"))
_started = False
_lock = threading.Lock()


def start_scheduler(interval: int | None = None) -> None:
    """Start the background refresh thread. Safe to call multiple times — only one thread starts."""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    effective_interval = interval if interval is not None else _INTERVAL_SECONDS

    def _loop() -> None:
        while True:
            time.sleep(effective_interval)
            try:
                from bluegrass.research.catchup import run_catchup
                result = run_catchup()
                if result["applied"] > 0:
                    _log.info(
                        "scheduler catch-up: applied=%d skipped=%d errors=%d",
                        result["applied"], result["skipped"], result["errors"],
                    )
            except Exception:
                _log.exception("scheduler catch-up failed")

    t = threading.Thread(target=_loop, daemon=True, name="bluegrass-refresh")
    t.start()
    _log.info("Bluegrass refresh scheduler started (interval=%ds)", effective_interval)


def reset_scheduler_state() -> None:
    """Reset started flag — for testing only."""
    global _started
    with _lock:
        _started = False
