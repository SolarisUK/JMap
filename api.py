"""Local simulator API. Run: .venv/Scripts/python.exe -m uvicorn api:app --reload."""
from __future__ import annotations

import os
from pathlib import Path
import threading
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
import schemas as S
from simulation_service import DEFAULT_SCENARIO, SimulationService, StubService

ROOT = Path(__file__).resolve().parent


def create_app(service=None):
    app = FastAPI(title="JMap grid simulation API", version=S.CONTRACT_VERSION, description="Deterministic demonstration simulator. Synthetic data, simplified physics and untrained-policy placeholders are labelled in every result.")
    app.state.simulation_service = service
    lock = threading.Lock()

    def backend():
        if app.state.simulation_service is None:
            with lock:
                if app.state.simulation_service is None:
                    mode = os.getenv("JMAP_BACKEND_MODE", "simulation")
                    if mode not in {"simulation", "stubs"}:
                        raise RuntimeError("JMAP_BACKEND_MODE must be simulation or stubs.")
                    app.state.simulation_service = StubService() if mode == "stubs" else SimulationService()
        return app.state.simulation_service

    def call(method, *args):
        try:
            return getattr(backend(), method)(*args)
        except (ValueError, TypeError, KeyError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/", include_in_schema=False)
    def homepage():
        return RedirectResponse(url="/UI/operations.html")

    @app.get("/reference")
    def reference():
        return call("reference")

    @app.get("/zones")
    def zones():
        return call("zones")

    @app.get("/edges")
    def edges():
        return call("edges")

    @app.get("/scenarios")
    def scenarios():
        return call("scenarios")

    @app.get("/state/series")
    def series(scenario: str = DEFAULT_SCENARIO, strategy: str = "optimiser"):
        return call("series", scenario, strategy)

    @app.get("/state")
    def state(t: str | None = Query(default=None, description="UTC interval-start ISO timestamp, or a zero-based half-hour step from 0 to 47."), scenario: str = DEFAULT_SCENARIO, strategy: str = "optimiser"):
        return call("state", scenario, strategy, t)

    @app.get("/forecast/{zone_id}")
    def forecast(zone_id: str, issue_time: str | None = None):
        return call("forecast", zone_id, issue_time)

    @app.get("/compare")
    def compare(scenario: str = DEFAULT_SCENARIO):
        return call("compare", scenario)

    @app.post("/incident")
    def incident(payload: dict = Body(...), scenario: str = DEFAULT_SCENARIO):
        return call("add_incident", payload, scenario)

    app.mount("/UI", StaticFiles(directory=ROOT / "UI", html=True), name="ui")
    app.mount("/stubs", StaticFiles(directory=ROOT / "stubs"), name="stubs")
    return app


app = create_app()
