"""The backend. Serves the stub files now, real data later.

Run it:
    python -B UI/scripts/export-api-stubs.py --backend-root dhruv_latest
    uvicorn api:app --reload --port 8000

Then open http://localhost:8000/docs to click through every endpoint.

Every endpoint reads a file from stubs/. At hour 10 you replace the body of each function with a
real call; the URLs, the parameters and the JSON shapes do not change, so the dashboard carries on
working while you do it.
"""

import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

STUBS = Path(__file__).parent / "stubs"

app = FastAPI(title="Grid API", version="0.1.0")

# Streamlit runs on a different port, so the browser needs this.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def stub(name: str):
    path = STUBS / f"{name}.json"
    if not path.exists():
        raise HTTPException(
            503, f"{path} missing. Run: python -B UI/scripts/export-api-stubs.py --backend-root dhruv_latest"
        )
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _cached_replay(path: str, modified: int, size: int):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def replay():
    path = STUBS / "replay.json"
    if not path.is_file():
        raise HTTPException(503, "Complete replay missing. Run: python -B UI/scripts/export-api-stubs.py --backend-root dhruv_latest")
    version = path.stat()
    return _cached_replay(str(path), version.st_mtime_ns, version.st_size)


def run(scenario: str, strategy: str, collection: str):
    data = replay()
    if scenario not in data[collection]:
        raise HTTPException(404, f"Unknown scenario: {scenario}")
    if strategy not in data[collection][scenario]:
        raise HTTPException(404, f"Unknown strategy: {strategy}")
    return data[collection][scenario][strategy]


def utc(value: str):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() != timedelta(0):
            raise ValueError("UTC required")
        return stamp
    except (ValueError, TypeError):
        raise HTTPException(422, "Timestamp must be an ISO 8601 UTC date and time.") from None


@app.get("/zones")
def zones():
    """GeoJSON polygons for the 10 zones. Join key is properties.zone_id."""
    return replay()["zones"]


@app.get("/edges")
def edges():
    """The 14 transmission corridors, with endpoint lat/lons for drawing lines."""
    return replay()["edges"]


@app.get("/state")
def state(t: str | None = None, incident: bool = False,
          scenario: str = "b6_trip_windy_peak", strategy: str = "optimiser"):
    """One half-hour snapshot: demand, generation, unserved MW per zone; flows per edge.

    Select the scenario, strategy and exact UTC interval start. Without t, return the
    first interval; incident=true selects the first recorded active incident.
    """
    frames = run(scenario, strategy, "states")
    if t is not None:
        requested = utc(t)
        for frame in frames:
            if utc(frame["timestamp_utc"]) == requested:
                return frame
        raise HTTPException(404, "Requested timestamp is not in this scenario's episode.")
    if incident:
        for frame in frames:
            if frame.get("incidents"):
                return frame
        raise HTTPException(404, "This episode has no active incident snapshot.")
    return frames[0]


@app.get("/state/series")
def series(scenario: str = "b6_trip_windy_peak", strategy: str = "optimiser"):
    """All 48 half-hours of one episode. This is what the time slider reads.

    Fetch it twice -- strategy="none" and strategy="agents" -- to show the same incident with and
    without the response, side by side.
    """
    return run(scenario, strategy, "series")


@app.get("/forecast/{zone_id}")
def forecast(zone_id: str, issue_time: str | None = None,
             scenario: str = "b6_trip_windy_peak"):
    """48 half-hours of [p10, p50, p90] demand in MW, plus a plain-English explanation."""
    forecasts = replay()["scenario_forecasts"]
    if scenario not in forecasts or zone_id not in forecasts[scenario]:
        raise HTTPException(404, "Unknown scenario or forecast zone.")
    data = forecasts[scenario][zone_id]
    if issue_time and utc(issue_time) != utc(data["issue_time_utc"]):
        raise HTTPException(409, "Read-only forecast is available only at this scenario's recorded issue time.")
    return data


@app.get("/scenarios")
def scenarios():
    """The three scripted scenarios, for the picker."""
    return replay()["scenarios"]


class Incident(BaseModel):
    type: str
    target: str
    start_step: int = 34
    duration_steps: int = 14
    magnitude: float = 1.0


@app.post("/incident")
def post_incident(body: Incident):
    """Inject an incident. Returns an acknowledgement."""
    raise HTTPException(409, "Read-only replay. Select a pre-generated scenario; custom incidents require a running simulator.")


@app.get("/compare")
def compare(scenario: str = "b6_trip_windy_peak"):
    """Episode scoreboard; real cost and model penalties remain separate fields."""
    data = stub("compare")
    if scenario not in data:
        raise HTTPException(404, f"unknown scenario {scenario}; have {sorted(data)}")
    return data[scenario]


@app.get("/reference")
def reference():
    """Zone order, edge order, fuel order, incident types, strategy keys. Don't hardcode these."""
    return replay()["reference"]


@app.get("/health")
def health():
    missing = [
        n
        for n in (
            "zones", "edges", "state_calm", "state_incident", "state_series",
            "forecast_LOND", "compare", "scenarios", "incident_response", "reference",
            "state_series_none", "state_series_optimiser", "replay",
        )
        if not (STUBS / f"{n}.json").exists()
    ]
    return {"ok": not missing, "missing_stubs": missing}
