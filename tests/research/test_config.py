"""Tests for bluegrass.research.config window constants."""

from bluegrass.research.config import ANALYSIS_WINDOW_DAYS, SYNC_WINDOW_DAYS


def test_sync_window_is_30() -> None:
    assert SYNC_WINDOW_DAYS == 30


def test_analysis_window_is_250() -> None:
    assert ANALYSIS_WINDOW_DAYS == 250


def test_analysis_window_greater_than_sync_window() -> None:
    assert ANALYSIS_WINDOW_DAYS > SYNC_WINDOW_DAYS
