"""The backend. Serves the stub files now, real data later.

Run it:
    python3 scripts/make_api_stubs.py      # once, creates stubs/
    uvicorn api:app --reload --port 8000

Then open http://localhost:8000/docs to click through every endpoint.

Every endpoint reads a file from stubs/. At hour 10 you replace the body of each function with a
real call; the URLs, the parameters and the JSON shapes do not change, so the dashboard carries on
working while you do it.
"""

import json
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
            503, f"{path} missing. Run: python3 scripts/make_api_stubs.py"
        )
    return json.loads(path.read_text())


@app.get("/zones")
def zones():
    """GeoJSON polygons for the 10 zones. Join key is properties.zone_id."""
    return stub("zones")


@app.get("/edges")
def edges():
    """The 14 transmission corridors, with endpoint lat/lons for drawing lines."""
    return stub("edges")


@app.get("/state")
def state(t: str | None = None, incident: bool = False):
    """One half-hour snapshot: demand, generation, unserved MW per zone; flows per edge.

    `incident=true` returns a snapshot taken mid-outage, so you can build and style the red
    states without waiting for the real simulator.
    """
    return stub("state_incident" if incident else "state_calm")


@app.get("/state/series")
def series(scenario: str = "b6_trip_windy_peak", strategy: str = "optimiser"):
    """All 48 half-hours of one episode. This is what the time slider reads.

    Fetch it twice -- strategy="none" and strategy="agents" -- to show the same incident with and
    without the response, side by side.
    """
    data = stub("state_series")
    data["scenario"] = scenario
    data["strategy"] = strategy
    return data


@app.get("/forecast/{zone_id}")
def forecast(zone_id: str, issue_time: str | None = None):
    """48 half-hours of [p10, p50, p90] demand in MW, plus a plain-English explanation."""
    data = stub("forecast_LOND")
    data["zone_id"] = zone_id
    if issue_time:
        data["issue_time_utc"] = issue_time
    return data


@app.get("/scenarios")
def scenarios():
    """The three scripted scenarios, for the picker."""
    return stub("scenarios")


class Incident(BaseModel):
    type: str
    target: str
    start_step: int = 34
    duration_steps: int = 14
    magnitude: float = 1.0


@app.post("/incident")
def post_incident(body: Incident):
    """Inject an incident. Returns an acknowledgement."""
    data = stub("incident_response")
    data["incident"] = body.model_dump()
    return data


@app.get("/compare")
def compare(scenario: str = "b6_trip_windy_peak"):
    """The scoreboard: unserved MWh, cost, carbon and curtailment for all three strategies."""
    data = stub("compare")
    if scenario not in data:
        raise HTTPException(404, f"unknown scenario {scenario}; have {sorted(data)}")
    return data[scenario]


@app.get("/reference")
def reference():
    """Zone order, edge order, fuel order, incident types, strategy keys. Don't hardcode these."""
    return stub("reference")


@app.get("/health")
def health():
    missing = [
        n
        for n in (
            "zones", "edges", "state_calm", "state_incident", "state_series",
            "forecast_LOND", "compare", "scenarios", "incident_response", "reference",
        )
        if not (STUBS / f"{n}.json").exists()
    ]
    return {"ok": not missing, "missing_stubs": missing}
