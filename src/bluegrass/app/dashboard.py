"""Dashboard payload helpers powered by the baseline packet."""

from __future__ import annotations

from bluegrass.app.watchlist import get_homepage_watchlist
from bluegrass.research.baseline import baseline_packet_summary


def get_dashboard_payload() -> dict[str, object]:
    return {
        "baseline_summary": baseline_packet_summary(),
        "watchlist": get_homepage_watchlist(),
    }
