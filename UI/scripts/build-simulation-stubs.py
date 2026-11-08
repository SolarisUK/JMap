"""Refresh the UI replay bundle from fixed, scenario-file-driven GridEnv runs.

Run with python -B. Backend sources and inputs are read-only; output stays in UI.
An existing complete JSON/JS export can also be validated with --import-bundle.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

sys.dont_write_bytecode = True
UI_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = UI_ROOT / "assets" / "simulation-stubs.js"
TOTAL_FIELDS = ("unserved_mwh", "cost_gbp", "penalty_gbp", "carbon_t", "curtailed_mwh")


def utc(value):
    if not isinstance(value, str):
        raise ValueError("A UTC timestamp is required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() != timedelta(0):
        raise ValueError(f"Timestamp must be UTC: {value}")
    return result


def read_bundle(path):
    text = Path(path).read_text(encoding="utf-8-sig").strip()
    if text.startswith("{"):
        return json.loads(text)
    # Read the known data assignment as JSON; never execute an imported script.
    assignment = re.search(r"window\.JMAP_SIMULATION_STUBS\s*=\s*", text)
    if not assignment:
        raise ValueError("Expected JSON or window.JMAP_SIMULATION_STUBS assignment")
    data = text[assignment.end():]
    value, end = json.JSONDecoder().raw_decode(data)
    trailing = data[end:].strip()
    if trailing not in ("", ";"):
        raise ValueError("Unexpected content after the simulation bundle")
    return value


def validate_bundle(bundle):
    ref = bundle["reference"]
    zones, edges = ref["zone_order"], ref["edge_order"]
    strategies = ("none", "optimiser")
    if "none" not in strategies or "optimiser" not in strategies:
        raise ValueError("Baseline and optimiser strategies are required")
    scenarios = bundle["scenarios"]["scenarios"]
    names = [scenario["name"] for scenario in scenarios]
    if not names or len(names) != len(set(names)):
        raise ValueError("Scenario names must be present and unique")
    for scenario in scenarios:
        name = scenario["name"]
        start = utc(scenario.get("episode_start_utc") or scenario.get("start_timestamp_utc"))
        comparison = bundle["compare"][name]
        if comparison["scenario"] != name:
            raise ValueError(f"{name}: mismatched scoreboard identity")
        timeline = None
        for strategy in strategies:
            series = bundle["series"][name][strategy]
            states = bundle["states"][name][strategy]
            if series["scenario"] != name or series["strategy"] != strategy:
                raise ValueError(f"{name}/{strategy}: mismatched episode identity")
            frames = series["frames"]
            if len(frames) != 48 or len(states) != 48:
                raise ValueError(f"{name}/{strategy}: expected 48 half-hours")
            times = [utc(frame["timestamp_utc"]) for frame in frames]
            # GridEnv currently timestamps post-step snapshots at interval end.
            if times[0] not in (start, start + timedelta(minutes=30)):
                raise ValueError(f"{name}/{strategy}: episode does not use its fixed start")
            if any(time != times[0] + timedelta(minutes=30*i) for i, time in enumerate(times)):
                raise ValueError(f"{name}/{strategy}: non-consecutive half-hours")
            if timeline is not None and times != timeline:
                raise ValueError(f"{name}: strategy timelines do not align")
            timeline = times
            for frame, state, time in zip(frames, states, times):
                if utc(state["timestamp_utc"]) != time:
                    raise ValueError(f"{name}/{strategy}: snapshot and slider times differ")
                if any(key not in frame["zones"] or key not in state["zones"] for key in zones):
                    raise ValueError(f"{name}/{strategy}: missing zone")
                if any(key not in frame["edges"] or key not in state["edges"] for key in edges):
                    raise ValueError(f"{name}/{strategy}: missing corridor")
            for key in TOTAL_FIELDS:
                if key == "penalty_gbp" and key not in states[-1]["totals"] and key not in comparison["strategies"][strategy]:
                    continue  # Older replay exports did not report penalties.
                final = states[-1]["totals"][key]
                reported = comparison["strategies"][strategy][key]
                if not isinstance(final, (int, float)) or not math.isfinite(final):
                    raise ValueError(f"{name}/{strategy}: unavailable final {key}")
                if not isinstance(reported, (int, float)) or not math.isfinite(reported) or not math.isclose(final, reported, rel_tol=1e-9, abs_tol=0.001):
                    raise ValueError(f"{name}/{strategy}: scoreboard {key} differs from final snapshot")
        forecasts = bundle["scenario_forecasts"][name] if "scenario_forecasts" in bundle else bundle["forecasts"]
        for zone in zones:
            forecast = forecasts[zone]
            issue = utc(forecast["issue_time_utc"])
            if issue != start or forecast["zone_id"] != zone:
                raise ValueError(f"{name}/{zone}: forecast is from a different scenario start")
            if forecast["unit"] != "MW" or forecast["quantiles"] != ["p10", "p50", "p90"]:
                raise ValueError(f"{name}/{zone}: invalid forecast units or quantiles")
            if len(forecast["timestamps_utc"]) != 48 or len(forecast["forecast"]) != 48:
                raise ValueError(f"{name}/{zone}: expected 48 forecast rows")
            for i, (stamp, row) in enumerate(zip(forecast["timestamps_utc"], forecast["forecast"])):
                if utc(stamp) != issue + timedelta(minutes=30*i):
                    raise ValueError(f"{name}/{zone}: shifted forecast timestamp")
                if len(row) != 3 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in row) or not row[0] <= row[1] <= row[2]:
                    raise ValueError(f"{name}/{zone}: invalid forecast quantiles")
            if len(forecast["explanation"]) != 3:
                raise ValueError(f"{name}/{zone}: expected three forecast factors")
    return bundle


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024*1024), b""):
            result.update(chunk)
    return result.hexdigest()


def baseline_forecasts(env, schema, start):
    forecasts = {}
    for j, zone in enumerate(schema.ZONE_ORDER):
        rows = []
        for h in range(48):
            previous_week = env.t0 + h - 336
            mid = float(env.demand[previous_week if previous_week >= 0 else env.t0, j])
            spread = 0.04 + 0.0025*h
            rows.append([mid*(1-spread), mid, mid*(1+spread)])
        forecasts[zone] = {
            "zone_id": zone, "issue_time_utc": start, "unit": "MW",
            "quantiles": ["p10", "p50", "p90"],
            "timestamps_utc": [(utc(start)+timedelta(minutes=30*h)).isoformat() for h in range(48)],
            "forecast": rows, "forecast_is_placeholder": True, "explanation_is_shap": False,
            "explanation": ["Uses the same half-hour last week where available.", "Falls back to demand at issue time when history is unavailable.", "Uncertainty bands are illustrative and uncalibrated."],
        }
    return forecasts


def build_from_backend(backend_root, scenarios_dir=None, agents_file=None, seed=1, allow_seeded_start=False):
    root = Path(backend_root).resolve()
    folder = Path(scenarios_dir).resolve() if scenarios_dir else root / "scenarios"
    paths = sorted(folder.glob("*.json"))
    if not paths:
        raise ValueError(f"No scenario files in {folder}. Sync the scenario JSON files before refreshing the UI bundle.")
    specs = {path.stem: json.loads(path.read_text(encoding="utf-8-sig")) for path in paths}
    for name, spec in specs.items():
        if not spec.get("episode_start_utc") and not allow_seeded_start:
            raise ValueError(f"{name}: episode_start_utc is required for deterministic replay")
        if spec.get("episode_start_utc"):
            utc(spec["episode_start_utc"])
        data = root / spec.get("selected_from", "data/canonical/_fake.parquet")
        if not data.is_file():
            raise ValueError(f"{name}: selected data file is missing: {data}")
    agents_path = Path(agents_file).resolve() if agents_file else root / "agents_baseline.py"
    if not agents_path.is_file():
        raise ValueError(f"Missing {agents_path}. Supply --agents-file with the supplied baseline module path.")
    sys.path.insert(0, str(root))
    try:
        import grid_env
        import schemas as S
        spec = importlib.util.spec_from_file_location("ui_baseline_agents", agents_path)
        baselines = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baselines)
    except ImportError as error:
        raise ValueError(f"Simulator dependency unavailable: {error}. Install the backend's declared dependencies, then rerun.") from error
    if not hasattr(grid_env, "make_scenario_env"):
        raise ValueError("Sync grid_env.py with make_scenario_env() before regenerating")
    missing = [name for name in S.SCENARIOS if name not in specs]
    if missing:
        raise ValueError(f"Missing canonical scenarios: {', '.join(missing)}")
    # Helper paths resolve against the backend checkout, never the UI directory.
    previous_cwd, previous_folder = Path.cwd(), S.SCENARIO_DIR
    S.SCENARIO_DIR = str(folder)
    os.chdir(root)
    try:
        names = [name for name in S.SCENARIOS if name in specs] + [name for name in specs if name not in S.SCENARIOS]
        bundle = {
            "reference": {}, "zones": {"type": "FeatureCollection", "features": []},
            "edges": {"edges": []}, "scenarios": {"scenarios": []},
            "series": {}, "states": {}, "compare": {}, "forecasts": {},
            "scenario_forecasts": {},
        }
        for name in names:
            scenario = dict(specs[name])
            if not scenario.get("episode_start_utc"):
                # Keep the scenario file read-only. Use midnight of the seed-
                # selected day when the source omits a fixed episode start.
                probe = grid_env.make_scenario_env(name, random_incidents=False)
                try:
                    _, initial = probe.reset(seed=seed)
                    selected = utc(initial["timestamp_utc"]).replace(hour=0, minute=0, second=0, microsecond=0)
                    scenario["episode_start_utc"] = selected.isoformat()
                    scenario["start_selection"] = f"UTC midnight of simulator seed {seed} selected day"
                finally:
                    probe.close()
            data_path = root / scenario.get("selected_from", str(grid_env.DEFAULT_DATA))
            synthetic = scenario.get("data_is_synthetic", True if "fake" in data_path.name.lower() else None)
            metadata = {**scenario, "name": name, "start_timestamp_utc": scenario["episode_start_utc"], "data_is_synthetic": synthetic, "scenario_sha256": digest(folder/f"{name}.json"), "data_sha256": digest(data_path)}
            bundle["scenarios"]["scenarios"].append(metadata)
            bundle["series"][name], bundle["states"][name] = {}, {}
            strategies = {}
            for key, controller_class in (("none", baselines.NoOpAgent), ("optimiser", baselines.OptimiserAgent)):
                options = {"start_utc": scenario["episode_start_utc"]} if not specs[name].get("episode_start_utc") else {}
                env = grid_env.make_scenario_env(name, random_incidents=False, **options)
                try:
                    observation, info = env.reset(seed=seed)
                    if utc(info["timestamp_utc"]) != utc(scenario["episode_start_utc"]):
                        raise ValueError(f"{name}: make_scenario_env did not apply episode_start_utc")
                    if key == "none":
                        bundle["scenario_forecasts"][name] = baseline_forecasts(env, S, scenario["episode_start_utc"])
                    controller = controller_class()
                    controller.reset()
                    frames, states = [], []
                    for index in range(S.STEPS_PER_EPISODE):
                        observation, reward, terminated, truncated, info = env.step(controller.act(observation, info))
                        snapshot = copy.deepcopy(info)
                        snapshot.update(scenario=name, strategy=key, step_index=index, forecast_is_placeholder=True, data_is_synthetic=synthetic)
                        states.append(snapshot)
                        frames.append({field: copy.deepcopy(snapshot[field]) for field in ("timestamp_utc", "zones", "edges", "incidents")})
                        if terminated or truncated:
                            break
                    bundle["series"][name][key] = {"scenario": name, "strategy": key, "frames": frames}
                    bundle["states"][name][key] = states
                    strategies[key] = copy.deepcopy(info["totals"])
                finally:
                    env.close()
            bundle["compare"][name] = {"scenario": name, "strategies": strategies}
        flags = {entry["data_is_synthetic"] for entry in bundle["scenarios"]["scenarios"]}
        ref = bundle["reference"]
        ref.update(
            contract_version=S.CONTRACT_VERSION,
            zone_order=list(S.ZONE_ORDER), edge_order=list(S.EDGE_ORDER),
            fuel_order=list(S.FUEL_ORDER), strategies=["none", "optimiser"],
            fuels=[vars(fuel).copy() for fuel in S.FUELS],
            incident_types=list(S.INCIDENT_TYPES), quantiles=list(S.QUANTILE_NAMES),
            quality_flags={key: value for key, value in vars(S.QF).items() if key.isupper() and isinstance(value, int)},
            obs_dim=S.OBS_DIM, act_dim=S.ACT_DIM,
            scenarios=names, steps_per_episode=S.STEPS_PER_EPISODE,
            forecast_horizon=S.FORECAST_HORIZON, display_timezone=S.DISPLAY_TZ,
            backend_mode="stubs",
            forecast_is_placeholder=True, geometry_is_placeholder=True,
            simulator_is_simplified=True, optimiser_is_heuristic=True,
            data_is_synthetic=next(iter(flags)) if len(flags)==1 else None,
            episode_start_utc=bundle["scenarios"]["scenarios"][0]["episode_start_utc"],
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            source_hashes={
                "grid_env.py": digest(root/"grid_env.py"),
                "schemas.py": digest(root/"schemas.py"), "agents": digest(agents_path),
            },
        )
        ref["zones"] = []
        for zone in S.ZONES:
            properties = {"zone_id": zone.id, "name": zone.name, "demand_share": zone.demand_share, "storage_mwh": zone.storage_mwh, "dr_mw": zone.dr_mw}
            w, h = .8+6*zone.demand_share, .6+4*zone.demand_share
            ring = [[zone.lon-w,zone.lat-h],[zone.lon+w,zone.lat-h],[zone.lon+w,zone.lat+h],[zone.lon-w,zone.lat+h],[zone.lon-w,zone.lat-h]]
            bundle["zones"]["features"].append({"type": "Feature", "properties": properties, "geometry": {"type": "Polygon", "coordinates": [ring]}})
            ref["zones"].append(copy.deepcopy(vars(zone)))
        for edge in S.EDGES:
            frm, to = S.ZONE_BY_ID[edge.frm], S.ZONE_BY_ID[edge.to]
            bundle["edges"]["edges"].append({"edge_id": edge.id, "from": edge.frm, "to": edge.to, "limit_mw": edge.limit_mw, "circuits": edge.circuits, "from_lat": frm.lat, "from_lon": frm.lon, "to_lat": to.lat, "to_lon": to.lon})
        bundle["forecasts"] = copy.deepcopy(bundle["scenario_forecasts"][names[0]])
        return validate_bundle(bundle)
    finally:
        os.chdir(previous_cwd)
        S.SCENARIO_DIR = previous_folder


def write_bundle(bundle, output):
    output = Path(output).resolve()
    if not output.is_relative_to(UI_ROOT) or output.suffix != ".js":
        raise ValueError("Bundle output must be a .js file inside UI/")
    validate_bundle(bundle)
    payload = json.dumps(bundle, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, prefix=output.name+".", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write("/* Generated optimisation replay data; forecast provenance remains explicit. */\nwindow.JMAP_SIMULATION_STUBS = " + payload + ";\n")
        temporary.replace(output)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-root", type=Path, default=UI_ROOT.parent)
    parser.add_argument("--scenarios-dir", type=Path)
    parser.add_argument("--agents-file", type=Path)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--import-bundle", type=Path, help="Validate and package a complete JSON or JS replay bundle")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        bundle = validate_bundle(read_bundle(args.import_bundle)) if args.import_bundle else build_from_backend(args.backend_root, args.scenarios_dir, args.agents_file, args.seed)
        if not args.check_only:
            write_bundle(bundle, args.output)
        print(f"{'Validated' if args.check_only else 'Updated'} {len(bundle['scenarios']['scenarios'])} scenarios; scoreboard totals match final states.")
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f"Simulation bundle unchanged: {error}\n")


if __name__ == "__main__":
    main()
