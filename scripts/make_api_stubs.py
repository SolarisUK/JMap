"""Copy real map geometry and optionally generate simulator API examples.

Ranya's handover: python scripts/make_api_stubs.py --zones-only
Full simulator examples: python scripts/make_api_stubs.py

Forecast curves and agent scores in full mode remain labelled placeholders.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import importlib.util
import json
import math
import os
import sys
from datetime import timedelta
from pathlib import Path


GEO_PROPERTIES = ("zone_id", "name", "demand_share", "storage_mwh", "dr_mw")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_schema(root):
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("schemas", root / "schemas.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["schemas"] = module
    spec.loader.exec_module(module)
    return module


def _round(value, nd=3):
    if isinstance(value, float):
        return 0.0 if abs(value) < 1e-3 else round(value, nd)
    if isinstance(value, dict):
        return {key: _round(item, nd) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round(item, nd) for item in value]
    return value


def write_json(root, name, payload):
    path = root / "stubs" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(_round(payload), indent=2, allow_nan=False)+"\n", encoding="utf-8")
    temp.replace(path)
    print(f"  stubs/{name}.json ({path.stat().st_size:,} bytes)")


def copy_zone_stub(root, S):
    source = root / "data/geo/zones.geojson"
    provenance_path = source.with_name("zones.provenance.json")
    raw = source.read_bytes()
    collection = json.loads(raw)
    if collection.get("type") != "FeatureCollection":
        raise ValueError("Expected a GeoJSON FeatureCollection")
    features = collection.get("features", [])
    order = list(S.ZONE_ORDER)
    if [f.get("properties", {}).get("zone_id") for f in features] != order:
        raise ValueError("GeoJSON zone IDs/order differ from schemas.ZONE_ORDER")
    lookup = {z.id: z for z in S.ZONES}
    for feature in features:
        properties = feature["properties"]
        zone = lookup[properties["zone_id"]]
        expected = {"zone_id": zone.id, "name": zone.name, "demand_share": zone.demand_share,
                    "storage_mwh": zone.storage_mwh, "dr_mw": zone.dr_mw}
        if feature.get("type") != "Feature" or set(properties) != set(GEO_PROPERTIES) or properties != expected:
            raise ValueError("Zone properties differ from the five contract properties")
        geometry = feature.get("geometry", {})
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError("Zones must contain Polygon/MultiPolygon geometry")
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        if not polygons:
            raise ValueError("Empty zone geometry")
        for polygon in polygons:
            if not polygon:
                raise ValueError("Empty polygon")
            for ring in polygon:
                if len(ring) < 4 or ring[0] != ring[-1]:
                    raise ValueError("Invalid or unclosed polygon ring")
                if any(len(p) != 2 or not (-9.5 < p[0] < 2.5 and 49 < p[1] < 61.5) for p in ring):
                    raise ValueError("Zone coordinates are outside the GB longitude/latitude range")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(raw).hexdigest()
    if provenance["output_sha256"] != source_hash:
        raise ValueError("Zone file changed after Stage 7 validation; rerun build_geo.py")
    target = root / "stubs/zones.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".json.tmp")
    # Do not call _round here: keep every validated coordinate unchanged.
    temp.write_bytes(raw)
    temp.replace(target)
    if digest(target) != source_hash:
        raise ValueError("Zone stub copy differs from its validated source")
    print(f"  stubs/zones.json ({len(raw):,} bytes; exact source copy)")
    return {"source": "data/geo/zones.geojson", "sha256": source_hash,
            "zones": len(features), "coordinate_precision": "unchanged"}


def simulator_modules(root):
    # The supplied repository originally used agents_baseline(1).py.
    if (root / "agents_baseline.py").is_file():
        baseline = importlib.import_module("agents_baseline")
    elif (root / "agents_baseline(1).py").is_file():
        spec = importlib.util.spec_from_file_location("agents_baseline", root / "agents_baseline(1).py")
        baseline = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = baseline
        spec.loader.exec_module(baseline)
    else:
        raise FileNotFoundError("Full mode needs agents_baseline.py or agents_baseline(1).py; use --zones-only for the map handover")
    return baseline, importlib.import_module("grid_env")


def make_simulator_stubs(root, S):
    """Preserve the supplied generator's payload layouts and placeholder logic."""
    AB, grid_env = simulator_modules(root)
    write_json(root, "edges", {"edges": [
        {"edge_id": e.id, "from": e.frm, "to": e.to, "limit_mw": e.limit_mw, "circuits": e.circuits,
         "from_lat": S.ZONE_BY_ID[e.frm].lat, "from_lon": S.ZONE_BY_ID[e.frm].lon,
         "to_lat": S.ZONE_BY_ID[e.to].lat, "to_lon": S.ZONE_BY_ID[e.to].lon} for e in S.EDGES]})

    env = grid_env.GridEnv(scenario=grid_env.load_scenario("b6_trip_windy_peak"))
    opt = AB.OptimiserAgent()
    obs, info = env.reset(seed=1)
    calm = incident = None
    for k in range(S.STEPS_PER_EPISODE):
        obs, reward, term, trunc, info = env.step(opt.act(obs, info))
        if k == 10:
            calm = copy.deepcopy(info)
        if k == 38:  # Four half-hours after the trip at step 34.
            incident = copy.deepcopy(info)
        if term or trunc:
            break
    if calm is None or incident is None:
        raise ValueError("Episode ended before both required state snapshots were available")
    write_json(root, "state_incident", incident)
    write_json(root, "state_calm", calm)

    env2 = grid_env.GridEnv(scenario=grid_env.load_scenario("b6_trip_windy_peak"))
    obs, info = env2.reset(seed=1)
    frames = []
    for _ in range(S.STEPS_PER_EPISODE):
        obs, reward, term, trunc, info = env2.step(opt.act(obs, info))
        frames.append({
            "timestamp_utc": info["timestamp_utc"],
            "zones": {z: {"demand_mw": round(v["demand_mw"], 1),
                          "generation_mw": round(v["generation_mw"], 1),
                          "unserved_mw": round(v["unserved_mw"], 1),
                          "storage_soc": round(v["storage_soc"], 3)} for z,v in info["zones"].items()},
            "edges": {e: {"flow_mw": round(v["flow_mw"], 1), "loading_frac": round(v["loading_frac"], 3),
                          "tripped": v["tripped"]} for e,v in info["edges"].items()},
            "incidents": info["incidents"],
        })
        if term or trunc:
            break
    write_json(root, "state_series", {"scenario": "b6_trip_windy_peak", "strategy": "optimiser", "frames": frames})

    env3 = grid_env.GridEnv()
    obs, info = env3.reset(seed=0)
    t0 = env3.times[env3.t0]
    p50, p90 = env3._forecast_block(env3.t0)
    rows = []
    for h in range(S.FORECAST_HORIZON):
        base = float(p50[S.ZONE_INDEX["LOND"], 0])
        mid = base * (1.0 + .18*math.sin(2*math.pi*(h-10)/48.0))
        spread = .04 + .0025*h
        rows.append([round(mid*(1-spread), 1), round(mid, 1), round(mid*(1+spread), 1)])
    write_json(root, "forecast_LOND", {
        "zone_id": "LOND", "issue_time_utc": t0.isoformat(), "unit": "MW",
        "quantiles": ["p10", "p50", "p90"],
        "timestamps_utc": [(t0+timedelta(minutes=30*i)).isoformat() for i in range(S.FORECAST_HORIZON)],
        "forecast": rows,
        "explanation": ["colder than usual for the time of year", "demand elevated over the last 24 hours",
                        "weekday evening peak approaching"],
    })

    def totals(agent, scenario):
        env = grid_env.GridEnv(scenario=scenario)
        obs, info = env.reset(seed=1)
        for _ in range(S.STEPS_PER_EPISODE):
            obs, reward, term, trunc, info = env.step(agent.act(obs, info))
            if term or trunc:
                break
        return {key: round(value, 1) for key,value in info["totals"].items()}

    compare = {}
    for name in S.SCENARIOS:
        scenario = grid_env.load_scenario(name)
        strategies = {"none": totals(AB.NoOpAgent(), scenario), "optimiser": totals(AB.OptimiserAgent(), scenario)}
        strategies["agents"] = dict(strategies["optimiser"])
        compare[name] = {"scenario": name, "strategies": strategies, "agents_is_placeholder": True}
    write_json(root, "compare", compare)
    write_json(root, "scenarios", {"scenarios": [
        {"name": name, "description": json.loads((Path(S.SCENARIO_DIR)/f"{name}.json").read_text(encoding="utf-8"))["description"]}
        for name in S.SCENARIOS]})
    write_json(root, "incident_response", {"ok": True, "incident_id": "inc_7f3a",
               "incident": S.Incident("line_trip", "SSCO-NORT", 34, 14, .5).to_dict()})
    write_json(root, "reference", {
        "zone_order": list(S.ZONE_ORDER), "edge_order": list(S.EDGE_ORDER), "fuel_order": list(S.FUEL_ORDER),
        "fuels": [{"id": f.id, "cost_gbp_per_mwh": f.cost_gbp_per_mwh, "carbon_t_per_mwh": f.carbon_t_per_mwh,
                   "dispatchable": f.dispatchable, "curtailable": f.curtailable} for f in S.FUELS],
        "incident_types": list(S.INCIDENT_TYPES), "strategies": list(S.STRATEGIES),
        "quality_flags": {name: getattr(S.QF, name) for name in
                          ["OK", "MISSING", "INTERPOLATED", "ZERO_RUN", "JUMP", "DST_BOUNDARY"]},
        "steps_per_episode": S.STEPS_PER_EPISODE, "forecast_horizon": S.FORECAST_HORIZON,
    })


def prepare_handover(root, geo_info, full_mode):
    canonical = root / "data/canonical/real.parquet"
    metadata = json.loads((root / "results/canonical_metadata.json").read_text(encoding="utf-8"))
    quality = json.loads((root / "results/data_quality_summary.json").read_text(encoding="utf-8"))
    canonical_hash = digest(canonical)
    if metadata.get("original_checker_return_code") != 0 or metadata.get("output_sha256") != canonical_hash:
        raise ValueError("Canonical data does not match a successful team-checker run")
    if quality.get("canonical_sha256") != canonical_hash:
        raise ValueError("Quality report is stale; rerun quality_report.py")
    names = ["data/canonical/real.parquet", "data/geo/zones.geojson", "stubs/zones.json",
             "data/raw/elexon/generation_by_fuel.parquet",
             "results/data_quality.md", "results/data_quality_summary.json", "results/data_coverage.png",
             "results/zones_preview.png", "results/stage5_checks.txt", "results/stage7_checks.txt"]
    files = {name: {"bytes": (root/name).stat().st_size, "sha256": digest(root/name)} for name in names}
    manifest = {"stage": 8, "mode": "all_examples" if full_mode else "zones_only",
                "rows": quality["rows"], "zones": quality["zones"], "start_utc": quality["start_utc"],
                "last_interval_start_utc": quality["last_interval_start_utc"], "zone_stub": geo_info,
                "files": files, "team_validator": "PASS for the hashed canonical file",
                "model_training": "Eugene must retrain and evaluate on real.parquet",
                "simulator_examples_regenerated": full_mode,
                "simulator_canonical_input_verified": False,
                "forecast_example": "illustrative curve, not trained-model output",
                "agent_scores": "placeholder optimiser copy in supplied generator, not trained-policy evidence",
                "git_commit_push_and_notifications": "pending user actions"}
    (root/"results/handover_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    notes = f"""DATA HANDOVER

Canonical file: data/canonical/real.parquet
Rows: {quality['rows']:,}; zones: {quality['zones']}; UTC half-hour starts.
Window: {quality['start_utc']} to {quality['last_interval_start_utc']}.
The supplied team checker passed; the manifest records the current file hashes.

EUGENE
Train and evaluate on data/canonical/real.parquet. The nine column names and
Arrow types match the fake-data contract. Rerun train.py and evaluate.py and
replace metrics from synthetic data. Report the same-half-hour-last-week
baseline as required by the contract.

LEONARD
Use stubs/zones.json for /zones, or serve data/geo/zones.geojson directly.
They are byte-identical. The five feature properties are unchanged. Preserve
coordinate precision; applying the generator's three-decimal rounding to
GeoJSON would alter the validated boundaries. Check results/zones_preview.png.

DHRUV / FULL SIMULATOR RUN
Check that GridEnv loads real.parquet and that scenario timestamps lie inside
the data window. This handover does not change or verify GridEnv's input loader.
Supporting national generation is in data/raw/elexon/generation_by_fuel.parquet;
its source categories and limitations are listed in results/stage2_checks.txt.
The full generator is available with no --zones-only flag once its simulator,
agents and scenario files are installed. Simulation states remain simulations.

DATA LIMITS
Regional demand is estimated from national demand and temperature, not measured
at regional meters. Regional targets depend on temperature used in the split.
Weather issue times are proxies and do not establish a leak-free day-ahead
backtest. DNO polygons are approximate service areas; WALE includes Merseyside
and Cheshire. See results/data_quality.md and data/geo/zones.provenance.json.

EXAMPLE-PAYLOAD STATUS
This run regenerated {'all supplied example payloads' if full_mode else 'only the real zones payload'}.
The supplied forecast example is a mock curve and its explanations are mock
text. The agents comparison copies optimiser results and is labelled as a
placeholder. Neither is a trained-model result. Existing non-zone stubs are
{'regenerated from the supplied simulator logic' if full_mode else 'left in place without claiming they were checked or regenerated'}.

PUBLISHING
No Git commit, push or teammate notification is performed by this script.
Review git status before staging the generated outputs and code. Send the
canonical file/report path to Eugene and the zone-file path to Leonard after
sharing the files. Owner actions above still need to be carried out.
"""
    (root/"results/handover_notes.txt").write_text(notes, encoding="utf-8")
    provenance = {"zones": geo_info, "other_stubs_regenerated": full_mode,
                  "forecast_is_mock": True if full_mode else None,
                  "agent_scores_are_placeholder": True if full_mode else None,
                  "untouched_payloads": "not inspected in zones-only mode" if not full_mode else None,
                  "supplied_full_generator_forecast_and_agent_scores_are_placeholders": True,
                  "simulator_real_data_source_verified": False}
    (root/"stubs/provenance.json").write_text(json.dumps(provenance, indent=2)+"\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--zones-only", action="store_true", help="Refresh /zones and handover files without importing the simulator")
    args = parser.parse_args()
    root = args.root.resolve()
    S = load_schema(root)
    geo_info = copy_zone_stub(root, S)
    # Preserve relative scenario/data paths used by the supplied simulator.
    os.chdir(root)
    if not args.zones_only:
        make_simulator_stubs(root, S)
    prepare_handover(root, geo_info, full_mode=not args.zones_only)
    print("Stage 8 map handover: PASS")
    print("stubs/zones.json exactly matches data/geo/zones.geojson")
    print("Wrote: results/handover_notes.txt and results/handover_manifest.json")
    if args.zones_only:
        print("Only zone stubs refreshed; simulator/model example payloads were not regenerated.")
    print("Git commit/push and teammate notifications remain pending.")


if __name__ == "__main__":
    main()
