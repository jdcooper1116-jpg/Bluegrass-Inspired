"""Tests for stats_store atomic write safety and read resilience."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from bluegrass.research.stats_store import (
    RUNTIME_DIR,
    STATS_STATE_PATH,
    _STATS_STATE_TMP,
    _READ_RETRIES,
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
    loaded = load_stats_state()
    assert loaded == state


def test_load_returns_empty_when_absent() -> None:
    assert not STATS_STATE_PATH.exists()
    assert load_stats_state() == {}


def test_reset_removes_file() -> None:
    save_stats_state({"x": 1})
    assert STATS_STATE_PATH.exists()
    reset_stats_state()
    assert not STATS_STATE_PATH.exists()


def test_reset_also_removes_tmp_file() -> None:
    _STATS_STATE_TMP.parent.mkdir(parents=True, exist_ok=True)
    _STATS_STATE_TMP.write_text("leftover")
    reset_stats_state()
    assert not _STATS_STATE_TMP.exists()


# ---------------------------------------------------------------------------
# Atomic write: no partial file ever visible
# ---------------------------------------------------------------------------

def test_save_writes_via_tmp_then_replaces() -> None:
    """os.replace is called with tmp → target, so the target is always complete."""
    replaced: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy_replace(src, dst):
        replaced.append((str(src), str(dst)))
        real_replace(src, dst)

    with patch("bluegrass.research.stats_store.os.replace", side_effect=spy_replace):
        save_stats_state({"v": 42})

    assert len(replaced) == 1
    src, dst = replaced[0]
    assert "tmp" in src
    assert src != dst
    assert str(STATS_STATE_PATH) == dst


def test_tmp_file_absent_after_successful_save() -> None:
    """The .tmp file is cleaned up by the atomic rename."""
    save_stats_state({"v": 1})
    assert not _STATS_STATE_TMP.exists()


def test_target_is_valid_json_after_save() -> None:
    save_stats_state({"session": "Midday", "count": 7})
    raw = STATS_STATE_PATH.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["count"] == 7


def test_concurrent_reads_never_see_partial_json() -> None:
    """Spawn a reader thread while the writer is active.

    The reader should never encounter a JSONDecodeError because os.replace
    is atomic — it sees the complete old state or the complete new state.
    """
    save_stats_state({"draws": 0})   # seed with valid initial state

    errors: list[Exception] = []

    def reader():
        for _ in range(50):
            try:
                state = load_stats_state()
                # Must be a dict, never partial
                assert isinstance(state, dict)
            except Exception as exc:
                errors.append(exc)
            time.sleep(0.001)

    def writer():
        for i in range(50):
            save_stats_state({"draws": i, "payload": "x" * 1000})
            time.sleep(0.001)

    r = threading.Thread(target=reader, daemon=True)
    w = threading.Thread(target=writer, daemon=True)
    r.start()
    w.start()
    w.join(timeout=5)
    r.join(timeout=5)

    assert errors == [], f"Reader saw errors: {errors}"


# ---------------------------------------------------------------------------
# Read retry on JSONDecodeError
# ---------------------------------------------------------------------------

def test_load_retries_on_json_decode_error_then_succeeds() -> None:
    """First read raises JSONDecodeError; second succeeds — load returns state."""
    good_state = {"recovered": True}
    call_count = [0]

    original_open = open

    def patched_open(path, *args, **kwargs):
        if str(path) == str(STATS_STATE_PATH) and "r" in args:
            call_count[0] += 1
            if call_count[0] == 1:
                # Simulate partial-write garbage on first read
                m = MagicMock()
                m.__enter__ = lambda s: s
                m.__exit__ = MagicMock(return_value=False)
                m.read = MagicMock(return_value="{bad json")

                class BadFile:
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                    def read(self): return "{bad json"

                import io
                bad = io.StringIO("{bad json")
                bad.__enter__ = lambda s: s
                bad.__exit__ = lambda s, *a: False

                class FakeFile:
                    def __enter__(self): return self
                    def __exit__(self, *a): return False

                import builtins
                orig = builtins.open
                # Use json.load against bad content directly
                raise json.JSONDecodeError("Expecting value", "{bad json", 0)
            # second call — return real file
        return original_open(path, *args, **kwargs)

    # Simpler: patch json.load to fail once then succeed
    save_stats_state(good_state)
    load_call = [0]
    real_json_load = json.load

    def patched_json_load(fh):
        load_call[0] += 1
        if load_call[0] == 1:
            raise json.JSONDecodeError("simulated partial read", "", 0)
        return real_json_load(fh)

    with patch("bluegrass.research.stats_store.json.load", side_effect=patched_json_load), \
         patch("bluegrass.research.stats_store.time.sleep"):
        result = load_stats_state()

    assert result == good_state
    assert load_call[0] == 2   # failed once, succeeded on retry


def test_load_raises_runtime_error_after_all_retries_exhausted() -> None:
    """If every read attempt fails with JSONDecodeError, RuntimeError is raised."""
    save_stats_state({"x": 1})

    with patch(
        "bluegrass.research.stats_store.json.load",
        side_effect=json.JSONDecodeError("always bad", "", 0),
    ), patch("bluegrass.research.stats_store.time.sleep"):
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


def test_load_returns_empty_on_file_not_found_mid_read() -> None:
    """File deleted between exists() check and open() returns {}."""
    save_stats_state({"x": 1})

    with patch(
        "bluegrass.research.stats_store.STATS_STATE_PATH"
    ) as mock_path:
        mock_path.exists.return_value = True
        mock_path.open.side_effect = FileNotFoundError
        mock_path.__str__ = lambda s: str(STATS_STATE_PATH)
        result = load_stats_state()

    assert result == {}


# ---------------------------------------------------------------------------
# save_stats_state: tmp cleanup on failure
# ---------------------------------------------------------------------------

def test_tmp_file_cleaned_up_on_write_failure() -> None:
    """If fsync or rename raises, the .tmp file is removed."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    with patch(
        "bluegrass.research.stats_store.os.replace",
        side_effect=OSError("disk full"),
    ):
        with pytest.raises(OSError, match="disk full"):
            save_stats_state({"x": 1})

    assert not _STATS_STATE_TMP.exists()


# ---------------------------------------------------------------------------
# Rebuild path: save after reset produces valid readable state
# ---------------------------------------------------------------------------

def test_reset_then_save_then_load_is_valid() -> None:
    """Simulates the rebuild path: reset → replay → save → load."""
    save_stats_state({"old": True})
    reset_stats_state()
    assert load_stats_state() == {}

    save_stats_state({"new": True, "draws": 100})
    assert load_stats_state() == {"draws": 100, "new": True}
