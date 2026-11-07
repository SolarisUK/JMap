"""Contract and behavioural tests for the nine requested simulator API endpoints."""
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import schemas as S
from api import create_app
from simulation_service import SimulationService, StubService, parse_utc


@pytest.fixture(scope="module")
def service():
    return SimulationService()


@pytest.fixture(scope="module")
def client(service):
    with TestClient(create_app(service)) as browser:
        yield browser


def test_reference_is_the_canonical_contract_and_declares_placeholders(client):
    response = client.get("/reference")
    assert response.status_code == 200
    payload = response.json()
    assert payload["zone_order"] == list(S.ZONE_ORDER)
    assert payload["edge_order"] == list(S.EDGE_ORDER)
    assert payload["fuel_order"] == list(S.FUEL_ORDER)
    assert payload["strategies"] == list(S.STRATEGIES)
    assert payload["steps_per_episode"] == 48
    assert payload["obs_dim"] == S.OBS_DIM
    assert payload["display_timezone"] == S.DISPLAY_TZ
    assert payload["agents_is_placeholder"] is True
    assert payload["forecast_is_placeholder"] is True
    assert payload["data_is_synthetic"] is True
    assert "geometry_is_placeholder" in payload


def test_static_geography_and_signed_corridor_topology(client):
    zones = client.get("/zones").json()
    assert zones["type"] == "FeatureCollection"
    assert {feature["properties"]["zone_id"] for feature in zones["features"]} == set(S.ZONE_ORDER)
    assert sum(feature["properties"]["demand_share"] for feature in zones["features"]) == pytest.approx(1)
    edges = client.get("/edges").json()["edges"]
    assert [edge["edge_id"] for edge in edges] == list(S.EDGE_ORDER)
    assert all(edge["from"] in S.ZONE_ORDER and edge["to"] in S.ZONE_ORDER for edge in edges)
    assert next(edge for edge in edges if edge["edge_id"] == S.B6_EDGE)["limit_mw"] == S.EDGE_BY_ID[S.B6_EDGE].limit_mw


@pytest.mark.parametrize("scenario", S.SCENARIOS)
@pytest.mark.parametrize("strategy", S.STRATEGIES)
def test_all_episodes_have_48_matching_reduced_and_full_states(client, scenario, strategy):
    series = client.get("/state/series", params={"scenario": scenario, "strategy": strategy}).json()
    assert series["scenario"] == scenario and series["strategy"] == strategy
    frames = series["frames"]
    assert len(frames) == 48
    for index, frame in enumerate(frames):
        assert set(frame["zones"]) == set(S.ZONE_ORDER)
        assert set(frame["edges"]) == set(S.EDGE_ORDER)
        assert parse_utc(frame["timestamp_utc"]) == parse_utc(frames[0]["timestamp_utc"]) + timedelta(minutes=30 * index)
    full = client.get("/state", params={"scenario": scenario, "strategy": strategy, "t": frames[34]["timestamp_utc"]}).json()
    assert full["timestamp_utc"] == frames[34]["timestamp_utc"]
    assert full["step_index"] == 34
    for zone in S.ZONE_ORDER:
        assert set(full["zones"][zone]) >= {"demand_mw", "generation_mw", "unserved_mw", "cost_gbp", "carbon_t", "curtailed_mw", "storage_soc", "dr_called_mw"}
        for field, value in frames[34]["zones"][zone].items():
            assert full["zones"][zone][field] == value


def test_preset_incidents_match_contract_and_switch_on_at_the_right_step(service, client):
    scenarios = client.get("/scenarios").json()["scenarios"]
    assert [scenario["name"] for scenario in scenarios] == list(S.SCENARIOS)
    b6 = service.states(S.SCENARIOS[0], "none")
    assert not b6[33]["edges"][S.B6_EDGE]["tripped"]
    assert b6[34]["edges"][S.B6_EDGE]["tripped"]
    assert b6[34]["edges"][S.B6_EDGE]["limit_mw"] == 3000
    cold = service.states("cold_snap", "none")
    assert len(cold[30]["incidents"]) == 10
    assert not cold[29]["incidents"] and not cold[42]["incidents"]
    for zone in S.ZONE_ORDER:
        assert cold[30]["zones"][zone]["demand_mw"] == pytest.approx(b6[30]["zones"][zone]["demand_mw"] * 1.18, abs=1e-5)
    low_wind = next(scenario for scenario in scenarios if scenario["name"] == "nuclear_outage_low_wind")
    assert {incident["target"] for incident in low_wind["incidents"] if incident["type"] == "wind_lull"} == set(S.ZONE_ORDER)


@pytest.mark.parametrize("scenario", S.SCENARIOS)
def test_scoreboard_uses_cumulative_simulator_totals_and_does_not_claim_a_trained_policy(service, client, scenario):
    payload = client.get("/compare", params={"scenario": scenario}).json()
    assert list(payload["strategies"]) == list(S.STRATEGIES)
    assert payload["agents_is_placeholder"] is True
    assert payload["strategies"]["agents"] == payload["strategies"]["optimiser"]
    for strategy in S.STRATEGIES:
        states = service.states(scenario, strategy)
        assert payload["strategies"][strategy] == states[-1]["totals"]
        unserved = sum(sum(zone["unserved_mw"] for zone in frame["zones"].values()) * .5 for frame in states)
        assert states[-1]["totals"]["unserved_mwh"] == pytest.approx(unserved, abs=1e-3)
        for field in states[-1]["totals"]:
            assert all(later["totals"][field] >= earlier["totals"][field] - 1e-5 for earlier, later in zip(states, states[1:]))


def test_forecast_has_48_ordered_quantiles_explicit_naive_explanations_and_no_future_leakage(service, client):
    payload = client.get("/forecast/LOND").json()
    assert payload["unit"] == "MW"
    assert payload["quantiles"] == list(S.QUANTILE_NAMES)
    assert payload["forecast_is_placeholder"] is True
    assert payload["explanation_is_shap"] is False
    assert len(payload["explanation"]) == 3
    assert "not calibrated" in payload["explanation"][2]
    assert len(payload["timestamps_utc"]) == len(payload["forecast"]) == 48
    S.validate_forecast(payload["forecast"])
    issue = parse_utc(payload["issue_time_utc"])
    assert payload["timestamps_utc"][0] == issue.isoformat()
    assert parse_utc(payload["timestamps_utc"][-1]) == issue + timedelta(minutes=30 * 47)
    saved = service._template.demand[service.default_start:].copy()
    try:
        service._template.demand[service.default_start:] = 999999
        assert service.forecast("LOND")["forecast"] == payload["forecast"]
    finally:
        service._template.demand[service.default_start:] = saved


def test_post_incident_invalidates_all_strategies_and_recomputes_selected_scenario():
    service = SimulationService()
    with TestClient(create_app(service)) as client:
        before = client.get("/state/series", params={"strategy": "none"}).json()
        baseline_compare = client.get("/compare").json()
        payload = {"type": "line_trip", "target": S.B6_EDGE, "start_step": 0, "duration_steps": 48, "magnitude": 1.0}
        response = client.post("/incident", json=payload)
        assert response.status_code == 200 and response.json()["ok"]
        after = client.get("/state/series", params={"strategy": "none"}).json()
        assert after["revision"] == before["revision"] + 1
        state = client.get("/state", params={"strategy": "none", "t": 0}).json()
        assert state["edges"][S.B6_EDGE] == {"flow_mw": 0.0, "limit_mw": 0.0, "loading_frac": 0.0, "tripped": True}
        assert client.get("/compare").json()["revision"] == baseline_compare["revision"] + 1
        assert client.get("/state/series", params={"scenario": "cold_snap"}).json()["revision"] == 0


@pytest.mark.parametrize("change", [
    {"type": "unknown"}, {"target": "all"}, {"start_step": -1}, {"start_step": 48},
    {"start_step": 2.5}, {"duration_steps": 0}, {"magnitude": -0.1}, {"magnitude": 1.1},
    {"extra": True}, {"start_step": True},
])
def test_invalid_incidents_are_rejected_without_mutating_state(client, change):
    before = client.get("/scenarios").json()
    payload = {"type": "line_trip", "target": S.B6_EDGE, "start_step": 34, "duration_steps": 14, "magnitude": 1.0, **change}
    assert client.post("/incident", json=payload).status_code == 422
    assert client.get("/scenarios").json() == before


@pytest.mark.parametrize("url", ["/state?scenario=nope", "/state?strategy=nope", "/state?t=48", "/state?t=2025-01-01", "/forecast/nope", "/forecast/LOND?issue_time=1900-01-01T00:00:00Z", "/compare?scenario=nope"])
def test_invalid_queries_return_a_useful_validation_error(client, url):
    response = client.get(url)
    assert response.status_code == 422
    assert response.json()["detail"]


def test_stub_and_simulation_read_endpoints_have_identical_recorded_results(service):
    bundle_path = ROOT / "stubs" / "bundle.json"
    assert bundle_path.exists(), "Run scripts/make_api_stubs.py before the tests."
    with TestClient(create_app(StubService(bundle_path))) as client:
        for scenario in S.SCENARIOS:
            assert client.get("/compare", params={"scenario": scenario}).json() == service.compare(scenario)
            for strategy in S.STRATEGIES:
                assert client.get("/state/series", params={"scenario": scenario, "strategy": strategy}).json() == service.series(scenario, strategy)
                assert client.get("/state", params={"scenario": scenario, "strategy": strategy, "t": 38}).json() == service.state(scenario, strategy, 38)
        assert client.get("/forecast/LOND").json() == service.forecast("LOND")
        assert client.post("/incident", json={}).status_code == 409


def test_api_serves_ui_and_redirects_root(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/UI/operations.html"
    assert client.get("/UI/main.html").status_code == 200
    assert client.get("/stubs/reference.json").status_code == 200
