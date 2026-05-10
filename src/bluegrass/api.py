from __future__ import annotations

from fastapi import FastAPI

from bluegrass.app.dashboard import get_dashboard_payload
from bluegrass.research.baseline import baseline_packet_summary

app = FastAPI(title="Bluegrass Baseline API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/baseline/summary")
def baseline_summary() -> dict[str, object]:
    return baseline_packet_summary()


@app.get("/dashboard/homepage")
def dashboard_homepage() -> dict[str, object]:
    return get_dashboard_payload()
