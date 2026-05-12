"""Tests for stats_store atomic write safety, unique temp files, and read resilience."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from bluegrass.research.stats_store import (
    RUNTIME_DIR,
    STATS_STATE_PATH,
    _READ_RETRIES,
    _WRITE_LOCK,
    load_stats_state,
    reset_stats_state,
    save_stats_state,
)


@pytest.fixture(autouse=True)
def clean_state():
    reset_stats_state()
    yield
    reset_stats_state()


# ---------------------------------------------------------------------------
# Basic round-trip
# ---------------------------------------------------------------------------

def test_save_and_load_roundtrip() -> None:
    state = {"by_session": {"Midday": {"draws_processed": 5}}}
    save_stats_state(state)
    assert load_stats_state() == state


def test_load_returns_empty_when_absent() -> None:
    assert not STATS_STATE_PATH.exists()
    assert load_stats_state() == {}


def test_reset_removes_file() -> None:
    save_stats_state({"x": 1})
    assert STATS_STATE_PATH.exists()
    reset_stats_state()
    assert not STATS_STATE_PATH.exists()


# ---------------------------------------------------------------------------
# Unique temp file — the core fix
# ---------------------------------------------------------------------------

def test_save_uses_unique_temp_not_shared_path() -> None:
    """Each save_stats_state() must use a different temp path."""
    temp_paths: list[str] = []
    real_replace = os.replace

    def capture_replace(src: str, dst: str) -> None:
        temp_paths.append(src)
        real_replace(src, dst)

    with patch("bluegrass.research.stats_store.os.replace", side_effect=capture_replace):
        save_stats_state({"a": 1})
        save_stats_state({"b": 2})

    assert len(temp_paths) == 2
    assert temp_paths[0] != temp_paths[1], "Each write must use a unique temp path"


def test_temp_file_uses_ss_prefix_and_tmp_suffix() -> None:
    """Temp files follow the ss_*.tmp naming convention for cleanup purposes."""
    seen_temps: list[str] = []
    real_replace = os.replace

    def capture(src: str, dst: str) -> None:
        seen_temps.append(src)
        real_replace(src, dst)

    with patch("bluegrass.research.stats_store.os.replace", side_effect=capture):
        save_stats_state({"v": 1})

    assert seen_temps
    name = Path(seen_temps[0]).name
    assert name.startswith("ss_"), f"Expected ss_ prefix, got: {name}"
    assert name.endswith(".tmp"), f"Expected .tmp suffix, got: {name}"


def test_temp_file_absent_after_successful_save() -> None:
    """No ss_*.tmp files should remain after a successful save."""
    save_stats_state({"v": 1})
    leftovers = list(RUNTIME_DIR.glob("ss_*.tmp"))
    assert leftovers == [], f"Leftover temp files: {leftovers}"


def test_no_shared_stats_state_tmp_constant() -> None:
    """Verify there is no _STATS_STATE_TMP module attribute (old shared path)."""
    import bluegrass.research.stats_store as ss_mod
    assert not hasattr(ss_mod, "_STATS_STATE_TMP"), (
        "_STATS_STATE_TMP must not exist; each write should use mkstemp()"
    )


def test_temp_file_cleaned_up_on_write_failure() -> None:
    """If os.replace raises, the unique temp file is removed."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    created_tmp: list[str] = []

    real_mkstemp = __import__("tempfile").mkstemp

    def spy_mkstemp(**kwargs):
        fd, path = real_mkstemp(**kwargs)
        created_tmp.append(path)
        return fd, path

    with patch("bluegrass.research.stats_store.tempfile.mkstemp", side_effect=spy_mkstemp), \
         patch("bluegrass.research.stats_store.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            save_stats_state({"x": 1})

    for path in created_tmp:
        assert not Path(path).exists(), f"Temp file not cleaned up: {path}"


def test_reset_cleans_stale_tmp_files() -> None:
    """reset_stats_state() should remove any lingering ss_*.tmp files."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    stale = RUNTIME_DIR / "ss_stale12345.tmp"
    stale.write_bytes(b"garbage")
    reset_stats_state()
    assert not stale.exists()


# ---------------------------------------------------------------------------
# Write lock — serialises concurrent saves
# ---------------------------------------------------------------------------

def test_concurrent_saves_no_collision_on_temp_files() -> None:
    """Concurrent threads each save different state; the last writer wins
    and no FileNotFoundError or temp-file collision occurs."""
    save_stats_state({"draws": 0})
    errors: list[Exception] = []

    def writer(i: int) -> None:
        try:
            save_stats_state({"draws": i, "payload": "x" * 500})
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,), daemon=True) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert errors == [], f"Concurrent saves raised errors: {errors}"
    state = load_stats_state()
    assert isinstance(state, dict)
    assert "draws" in state


def test_write_lock_is_threading_lock() -> None:
    """_WRITE_LOCK must be a threading.Lock so it serialises within the process."""
    assert isinstance(_WRITE_LOCK, type(threading.Lock()))


# ---------------------------------------------------------------------------
# Target is always valid JSON after concurrent saves
# ---------------------------------------------------------------------------

def test_concurrent_saves_target_always_valid_json() -> None:
    """Reader during concurrent writes never sees invalid JSON."""
    save_stats_state({"draws": 0})
    json_errors: list[Exception] = []

    def reader() -> None:
        for _ in range(40):
            try:
                state = load_stats_state()
                assert isinstance(state, dict)
            except Exception as exc:
                json_errors.append(exc)
            time.sleep(0.002)

    def writer() -> None:
        for i in range(40):
            save_stats_state({"draws": i, "padding": "z" * 2000})
            time.sleep(0.001)

    r = threading.Thread(target=reader, daemon=True)
    w = threading.Thread(target=writer, daemon=True)
    r.start(); w.start()
    w.join(timeout=8); r.join(timeout=8)

    assert json_errors == [], f"Reader saw errors during concurrent writes: {json_errors}"


# ---------------------------------------------------------------------------
# Read retry on JSONDecodeError
# ---------------------------------------------------------------------------

def test_load_retries_on_json_decode_error_then_succeeds() -> None:
    good_state = {"recovered": True}
    save_stats_state(good_state)
    load_call = [0]
    real_load = json.load

    def patched_load(fh):
        load_call[0] += 1
        if load_call[0] == 1:
            raise json.JSONDecodeError("simulated partial read", "", 0)
        return real_load(fh)

    with patch("bluegrass.research.stats_store.json.load", side_effect=patched_load), \
         patch("bluegrass.research.stats_store.time.sleep"):
        result = load_stats_state()

    assert result == good_state
    assert load_call[0] == 2


def test_load_raises_runtime_error_after_all_retries_exhausted() -> None:
    save_stats_state({"x": 1})
    with patch("bluegrass.research.stats_store.json.load",
               side_effect=json.JSONDecodeError("always bad", "", 0)), \
         patch("bluegrass.research.stats_store.time.sleep"):
        with pytest.raises(RuntimeError, match="invalid JSON"):
            load_stats_state()


def test_load_retries_exactly_read_retries_times() -> None:
    save_stats_state({"x": 1})
    call_count = [0]

    def always_bad(fh):
        call_count[0] += 1
        raise json.JSONDecodeError("bad", "", 0)

    with patch("bluegrass.research.stats_store.json.load", side_effect=always_bad), \
         patch("bluegrass.research.stats_store.time.sleep"):
        with pytest.raises(RuntimeError):
            load_stats_state()

    assert call_count[0] == _READ_RETRIES


# ---------------------------------------------------------------------------
# Rebuild path: reset then replay produces valid state
# ---------------------------------------------------------------------------

def test_reset_then_save_then_load_is_valid() -> None:
    save_stats_state({"old": True})
    reset_stats_state()
    assert load_stats_state() == {}
    save_stats_state({"new": True, "draws": 100})
    assert load_stats_state() == {"draws": 100, "new": True}
