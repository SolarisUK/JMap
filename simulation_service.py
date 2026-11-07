"""Deterministic API adapter for the supplied GridEnv, without changing its physics.

Defaults use the provided synthetic parquet, the supplied heuristic baselines and a
labelled historical-demand forecast. Configure model factories as module:attribute
with JMAP_FORECAST_PROVIDER / JMAP_POLICY_PROVIDER when trained models are available.
All paths resolve against this repository, never the caller's working directory.
"""
from __future__ import annotations

from bisect import bisect_left
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import importlib
import json
import math
import os
from pathlib import Path
import threading
import uuid

import numpy as np

import agents_baseline as AB
import grid_env
import schemas as S

ROOT = Path(__file__).resolve().parent
DEFAULT_SCENARIO = S.SCENARIOS[0]


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def parse_utc(value: str | datetime) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timestamp must include a timezone, for example 2025-01-08T00:00:00Z.")
    return result.astimezone(timezone.utc)


def _load_provider(spec: str | None):
    if not spec:
        return None
    module_name, separator, attribute = spec.partition(":")
    if not separator or not attribute:
        raise ValueError("Model provider must be module:factory (or module:instance).")
    provider = getattr(importlib.import_module(module_name), attribute)
    return provider() if callable(provider) else provider


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Simulator returned a non-finite value; refusing invalid JSON.")
        return 0.0 if abs(number) < 1e-10 else round(number, 6)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


class SimulationService:
    def __init__(self, data_path=None, forecast_provider=None, policy_provider=None):
        self.data_path = resolve_path(data_path or os.getenv("JMAP_DATA_PATH", S.CANONICAL_PATH + "/_fake.parquet"))
        self.forecaster = forecast_provider if forecast_provider is not None else _load_provider(os.getenv("JMAP_FORECAST_PROVIDER"))
        self.policy = policy_provider if policy_provider is not None else _load_provider(os.getenv("JMAP_POLICY_PROVIDER"))
        self.forecast_is_placeholder = self.forecaster is None
        self.agents_is_placeholder = self.policy is None
        self.data_is_synthetic = os.getenv("JMAP_DATA_IS_SYNTHETIC", "true").lower() != "false"
        self._lock = threading.RLock()
        self._episodes = {}
        self._extra_incidents = {name: [] for name in S.SCENARIOS}
        self._revisions = {name: 0 for name in S.SCENARIOS}
        self.scenario_definitions = {}
        for name in S.SCENARIOS:
            definition = json.loads((ROOT / S.SCENARIO_DIR / f"{name}.json").read_text(encoding="utf-8"))
            for item in definition["incidents"]:
                self.validate_incident(item)
            self.scenario_definitions[name] = definition
        self._template = grid_env.GridEnv(data_path=self.data_path, forecaster=self.forecaster, scenario=[], random_incidents=False)
        if self._template.n_t < S.STEPS_PER_EPISODE + 1:
            raise ValueError("Canonical data must contain at least 49 complete half-hours.")
        self.times = [parse_utc(time) for time in self._template.times]
        self._time_index = {time: index for index, time in enumerate(self.times)}
        self.default_start = self._choose_start()

    def _choose_start(self):
        # A complete UTC day with prior history, chosen deterministically from
        # actual supplied weather. Prefer the winter operating season and rank
        # by Scottish evening wind, rather than inventing a "windy" date.
        available = len(self.times) - S.STEPS_PER_EPISODE - 1
        warmup = min(S.HALF_HOURS_PER_DAY * 7, max(available, 0))
        candidates = [index for index in range(warmup, available + 1) if self.times[index].hour == self.times[index].minute == 0]
        if not candidates:
            return 0
        winter = [index for index in candidates if self.times[index].month in (11, 12, 1, 2)]
        north = [S.ZONE_INDEX[zone] for zone in ("NSCO", "SSCO")]
        return max(winter or candidates, key=lambda index: float(np.mean(self._template.wind[index + 30:index + 48, north])))

    def validate_scenario(self, name):
        if name not in S.SCENARIOS:
            raise ValueError(f"Unknown scenario {name!r}; choose one of {S.SCENARIOS}.")
        return name

    def validate_strategy(self, strategy):
        if strategy not in S.STRATEGIES:
            raise ValueError(f"Unknown strategy {strategy!r}; choose one of {S.STRATEGIES}.")
        return strategy

    @staticmethod
    def validate_incident(payload):
        required = {"type", "target", "start_step", "duration_steps", "magnitude"}
        if set(payload) != required:
            raise ValueError("Incident requires exactly type, target, start_step, duration_steps and magnitude.")
        for field in ("start_step", "duration_steps"):
            if isinstance(payload[field], bool) or not isinstance(payload[field], int):
                raise ValueError(f"{field} must be an integer.")
        magnitude = payload["magnitude"]
        if isinstance(magnitude, bool) or not isinstance(magnitude, (int, float)) or not math.isfinite(magnitude):
            raise ValueError("magnitude must be a finite number.")
        incident = S.Incident(**payload)
        if incident.type == "demand_spike":
            if magnitude < 1:
                raise ValueError("demand_spike magnitude must be at least 1.")
        elif not 0 <= magnitude <= 1:
            raise ValueError(f"{incident.type} magnitude must be between 0 and 1.")
        return incident

    def flags(self):
        return {
            "agents_is_placeholder": self.agents_is_placeholder,
            "forecast_is_placeholder": self.forecast_is_placeholder,
            "data_is_synthetic": self.data_is_synthetic,
            "simulator_is_simplified": True,
            "optimiser_is_heuristic": True,
        }

    def reference(self):
        return {
            "contract_version": S.CONTRACT_VERSION,
            "zone_order": list(S.ZONE_ORDER), "edge_order": list(S.EDGE_ORDER),
            "fuel_order": list(S.FUEL_ORDER), "fuels": [asdict(fuel) for fuel in S.FUELS],
            "incident_types": list(S.INCIDENT_TYPES), "strategies": list(S.STRATEGIES),
            "scenarios": list(S.SCENARIOS), "display_timezone": S.DISPLAY_TZ,
            "steps_per_episode": S.STEPS_PER_EPISODE, "forecast_horizon": S.FORECAST_HORIZON,
            "quantiles": list(S.QUANTILE_NAMES), "obs_dim": S.OBS_DIM, "act_dim": S.ACT_DIM,
            "quality_flags": {name: getattr(S.QF, name) for name in ("OK", "MISSING", "INTERPOLATED", "ZERO_RUN", "JUMP", "DST_BOUNDARY")},
            "zones": [asdict(zone) for zone in S.ZONES],
            "episode_start_utc": self.times[self.default_start].isoformat(),
            "data_source": self.data_path.name,
            "backend_mode": "simulation",
            "episode_selection": "Fixed complete UTC day with prior history; highest Scottish evening wind in the available winter operating season, otherwise the available period.",
            "forecast_method": "historical-week/persistence baseline with illustrative uncertainty" if self.forecast_is_placeholder else os.getenv("JMAP_FORECAST_PROVIDER", "configured provider"),
            "agents_status": "not yet trained; optimiser replay used as placeholder" if self.agents_is_placeholder else "configured policy provider",
            "geometry_is_placeholder": self.zones().get("geometry_is_placeholder", False),
            "physics_description": "Supplied simplified minimum-norm network flow simulator; not operational grid telemetry.",
            "colour_bands": {"edges": {"healthy_below": .75, "watch_below": 1.0, "overloaded_above": 1.0}, "zones": {"healthy_unserved_mw": 0}},
            **self.flags(),
        }

    def zones(self):
        geo_path = ROOT / S.GEO_PATH
        if geo_path.exists():
            geometry = json.loads(geo_path.read_text(encoding="utf-8"))
            if {feature["properties"]["zone_id"] for feature in geometry["features"]} != set(S.ZONE_ORDER):
                raise ValueError("Configured zone GeoJSON does not match canonical zone IDs.")
            return geometry
        features = []
        for zone in S.ZONES:
            width, height = .8 + 6 * zone.demand_share, .6 + 4 * zone.demand_share
            ring = [[zone.lon-width, zone.lat-height], [zone.lon+width, zone.lat-height], [zone.lon+width, zone.lat+height], [zone.lon-width, zone.lat+height], [zone.lon-width, zone.lat-height]]
            features.append({"type": "Feature", "properties": {"zone_id": zone.id, "name": zone.name, "demand_share": zone.demand_share, "storage_mwh": zone.storage_mwh, "dr_mw": zone.dr_mw, "lat": zone.lat, "lon": zone.lon}, "geometry": {"type": "Polygon", "coordinates": [ring]}})
        return {"type": "FeatureCollection", "features": features, "geometry_is_placeholder": True}

    @staticmethod
    def edges():
        return {"edges": [{"edge_id": edge.id, "from": edge.frm, "to": edge.to, "limit_mw": edge.limit_mw, "circuits": edge.circuits, "from_lat": S.ZONE_BY_ID[edge.frm].lat, "from_lon": S.ZONE_BY_ID[edge.frm].lon, "to_lat": S.ZONE_BY_ID[edge.to].lat, "to_lon": S.ZONE_BY_ID[edge.to].lon} for edge in S.EDGES]}

    def scenarios(self):
        return {"scenarios": [{"name": name, "description": self.scenario_definitions[name]["description"], "start_timestamp_utc": self._scenario_start(name).isoformat(), "incidents": deepcopy(self.scenario_definitions[name]["incidents"]), "revision": self._revisions[name]} for name in S.SCENARIOS]}

    def _scenario_start(self, scenario):
        supplied = self.scenario_definitions[scenario].get("start_timestamp_utc")
        return parse_utc(supplied) if supplied else self.times[self.default_start]

    def _episode(self, scenario, strategy):
        self.validate_scenario(scenario)
        self.validate_strategy(strategy)
        with self._lock:
            key = (scenario, strategy, self._revisions[scenario])
            if key in self._episodes:
                return self._episodes[key]
            if strategy == "agents" and self.agents_is_placeholder:
                frames = deepcopy(self._episode(scenario, "optimiser"))
                for frame in frames:
                    frame["strategy"] = "agents"
                    frame["strategy_source"] = "optimiser placeholder; agents not yet trained"
                self._episodes[key] = frames
                return frames
            start = self._scenario_start(scenario)
            start_index = self._time_index.get(start)
            if start_index is None or start_index + S.STEPS_PER_EPISODE >= len(self.times):
                raise ValueError("Scenario start must identify a complete 48-step episode in the canonical data.")
            incidents = [self.validate_incident(item) for item in self.scenario_definitions[scenario]["incidents"] + self._extra_incidents[scenario]]
            env = deepcopy(self._template)
            env.fixed_scenario = incidents
            obs, info = env.reset(seed=1)
            env.t0 = start_index
            obs, info = env._observe(), env._info()
            agent = AB.NoOpAgent() if strategy == "none" else AB.OptimiserAgent() if strategy == "optimiser" else self.policy
            if hasattr(agent, "reset"):
                agent.reset()
            frames = []
            for step in range(S.STEPS_PER_EPISODE):
                action = agent.act(obs, info)
                S.validate_action(action)
                obs, reward, terminated, truncated, info = env.step(action)
                state = deepcopy(info)
                # GridEnv reports the next observation time after stepping; these
                # values describe the interval that just started, not the next one.
                state.update({"timestamp_utc": self.times[start_index + step].isoformat(), "step_index": step, "scenario": scenario, "strategy": strategy, "revision": self._revisions[scenario], **self.flags()})
                for zone_index, zone_id in enumerate(S.ZONE_ORDER):
                    state["zones"][zone_id]["generation_by_fuel_mw"] = {fuel: float(env.output[zone_index, fuel_index]) for fuel_index, fuel in enumerate(S.FUEL_ORDER)}
                frames.append(_json_safe(state))
                if terminated or truncated:
                    break
            if len(frames) != S.STEPS_PER_EPISODE:
                raise RuntimeError("Simulator did not complete all 48 half-hours.")
            self._episodes[key] = frames
            return frames

    def states(self, scenario=DEFAULT_SCENARIO, strategy="optimiser"):
        return deepcopy(self._episode(scenario, strategy))

    def state(self, scenario=DEFAULT_SCENARIO, strategy="optimiser", t=None):
        frames = self._episode(scenario, strategy)
        if t is None:
            index = 0
        elif isinstance(t, int) or (isinstance(t, str) and t.isdecimal()):
            index = int(t)
            if not 0 <= index < S.STEPS_PER_EPISODE:
                raise ValueError("Step must be between 0 and 47.")
        else:
            wanted = parse_utc(t)
            start = parse_utc(frames[0]["timestamp_utc"])
            offset = (wanted - start).total_seconds() / 1800
            if not offset.is_integer() or not 0 <= offset < len(frames):
                raise ValueError("t must match a half-hour interval within the selected episode.")
            index = int(offset)
        return deepcopy(frames[index])

    def series(self, scenario=DEFAULT_SCENARIO, strategy="optimiser"):
        frames = self._episode(scenario, strategy)
        return {"scenario": scenario, "strategy": strategy, "revision": self._revisions[scenario], **self.flags(), "frames": [{"timestamp_utc": frame["timestamp_utc"], "step_index": frame["step_index"], "zones": {zone: {field: values[field] for field in ("demand_mw", "generation_mw", "unserved_mw", "storage_soc")} for zone, values in frame["zones"].items()}, "edges": {edge: {field: values[field] for field in ("flow_mw", "loading_frac", "tripped")} for edge, values in frame["edges"].items()}, "incidents": deepcopy(frame["incidents"])} for frame in frames]}

    def compare(self, scenario=DEFAULT_SCENARIO):
        self.validate_scenario(scenario)
        return {"scenario": scenario, "revision": self._revisions[scenario], "strategies": {strategy: deepcopy(self._episode(scenario, strategy)[-1]["totals"]) for strategy in S.STRATEGIES}, **self.flags()}

    def add_incident(self, payload, scenario=DEFAULT_SCENARIO):
        self.validate_scenario(scenario)
        incident = self.validate_incident(payload)
        with self._lock:
            self._extra_incidents[scenario].append(incident.to_dict())
            self._revisions[scenario] += 1
            self._episodes = {key: value for key, value in self._episodes.items() if key[0] != scenario}
            return {"ok": True, "incident_id": "inc_" + uuid.uuid4().hex[:12], "incident": incident.to_dict(), "scenario": scenario, "revision": self._revisions[scenario]}

    def forecast(self, zone_id, issue_time=None):
        if zone_id not in S.ZONE_BY_ID:
            raise ValueError(f"Unknown zone {zone_id!r}.")
        issue = parse_utc(issue_time) if issue_time else self.times[self.default_start]
        if issue < self.times[1] or issue > self.times[-1] + timedelta(minutes=30):
            raise ValueError("Forecast issue time must follow available history and remain within the canonical data period.")
        timestamps = [issue + timedelta(minutes=30 * index) for index in range(S.FORECAST_HORIZON)]
        if self.forecaster is not None:
            rows = self.forecaster.predict(zone_id, issue)
            S.validate_forecast(rows)
            explain = getattr(self.forecaster, "explain", None)
            explanation = explain(zone_id, issue) if explain else ["Forecast supplied by the configured model provider.", "Feature explanations are not available from this provider.", "The displayed P10–P90 interval is the provider's estimate."]
        else:
            zone_index = S.ZONE_INDEX[zone_id]
            last_index = bisect_left(self.times, issue) - 1
            persistence = float(self._template.demand[last_index, zone_index])
            rows = []
            weekly_count = 0
            for index, target in enumerate(timestamps):
                history_time = target - timedelta(days=7)
                history_index = self._time_index.get(history_time)
                if history_index is not None and history_time < issue:
                    middle = float(self._template.demand[history_index, zone_index])
                    weekly_count += 1
                else:
                    middle = persistence
                spread = .06 + .0025 * index
                rows.append([max(0, middle * (1-spread)), middle, middle * (1+spread)])
            explanation = [f"Baseline forecast: same half-hour last week used for {weekly_count} of 48 intervals.", "Missing weekly history falls back to the last observed half-hour; no future demand is read.", "P10–P90 is an illustrative widening range, not calibrated uncertainty or SHAP attribution."]
        payload = {"zone_id": zone_id, "issue_time_utc": issue.isoformat(), "unit": "MW", "quantiles": list(S.QUANTILE_NAMES), "timestamps_utc": [time.isoformat() for time in timestamps], "forecast": rows, "explanation": explanation, "forecast_is_placeholder": self.forecast_is_placeholder, "forecast_method": "historical-week/persistence baseline" if self.forecast_is_placeholder else "configured provider", "explanation_is_shap": bool(getattr(self.forecaster, "explanation_is_shap", False)), "data_is_synthetic": self.data_is_synthetic}
        S.validate_forecast(rows)
        return _json_safe(payload)

    def bundle(self):
        return {"reference": self.reference(), "zones": self.zones(), "edges": self.edges(), "scenarios": self.scenarios(), "compare": {scenario: self.compare(scenario) for scenario in S.SCENARIOS}, "series": {scenario: {strategy: self.series(scenario, strategy) for strategy in S.STRATEGIES} for scenario in S.SCENARIOS}, "states": {scenario: {strategy: self.states(scenario, strategy) for strategy in S.STRATEGIES} for scenario in S.SCENARIOS}, "forecasts": {zone: self.forecast(zone) for zone in S.ZONE_ORDER}}


class StubService:
    """The same read interface, served from simulator-generated files on disk."""
    def __init__(self, path=None):
        self.path = resolve_path(path or os.getenv("JMAP_STUB_BUNDLE", "stubs/bundle.json"))
        self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def reference(self):
        return {**deepcopy(self.data["reference"]), "backend_mode": "stubs"}

    def zones(self):
        return deepcopy(self.data["zones"])

    def edges(self):
        return deepcopy(self.data["edges"])

    def scenarios(self):
        return deepcopy(self.data["scenarios"])

    @staticmethod
    def _validate(scenario, strategy="optimiser"):
        if scenario not in S.SCENARIOS or strategy not in S.STRATEGIES:
            raise ValueError("Unknown scenario or strategy.")

    def states(self, scenario=DEFAULT_SCENARIO, strategy="optimiser"):
        self._validate(scenario, strategy)
        return deepcopy(self.data["states"][scenario][strategy])

    def state(self, scenario=DEFAULT_SCENARIO, strategy="optimiser", t=None):
        frames = self.states(scenario, strategy)
        if t is None:
            return frames[0]
        if isinstance(t, int) or (isinstance(t, str) and t.isdecimal()):
            if not 0 <= int(t) < len(frames):
                raise ValueError("Step must be between 0 and 47.")
            return frames[int(t)]
        stamp = parse_utc(t)
        for frame in frames:
            if parse_utc(frame["timestamp_utc"]) == stamp:
                return frame
        raise ValueError("t must match a half-hour interval within the selected episode.")

    def series(self, scenario=DEFAULT_SCENARIO, strategy="optimiser"):
        self._validate(scenario, strategy)
        return deepcopy(self.data["series"][scenario][strategy])

    def compare(self, scenario=DEFAULT_SCENARIO):
        self._validate(scenario)
        return deepcopy(self.data["compare"][scenario])

    def forecast(self, zone_id, issue_time=None):
        if zone_id not in S.ZONE_BY_ID:
            raise ValueError("Unknown zone.")
        payload = deepcopy(self.data["forecasts"][zone_id])
        if issue_time and parse_utc(issue_time) != parse_utc(payload["issue_time_utc"]):
            raise ValueError("Static forecasts are available only at their recorded issue time.")
        return payload

    def add_incident(self, payload, scenario=DEFAULT_SCENARIO):
        raise RuntimeError("Stub mode is read-only. Start JMAP_BACKEND_MODE=simulation to recompute incidents.")
