"""Generate real example payloads for every API endpoint, from the live simulator.

Leonard serves these from disk at hour 0, so his dashboard is finished before the real API
exists. They are produced by the actual env, so the shapes are identical to what the real
endpoints will return -- not hand-written approximations that drift.

Usage: python3 scripts/make_api_stubs.py
Writes: stubs/*.json
"""

import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agents_baseline as AB
import grid_env
import schemas as S

OUT = Path("stubs")
OUT.mkdir(exist_ok=True)


def _round(o, nd=3):
    """Round every float in a nested structure, so payloads don't carry 7.5e-05 noise."""
    if isinstance(o, float):
        return 0.0 if abs(o) < 1e-3 else round(o, nd)
    if isinstance(o, dict):
        return {k: _round(v, nd) for k, v in o.items()}
    if isinstance(o, list):
        return [_round(v, nd) for v in o]
    return o


def write(name: str, payload) -> None:
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(_round(payload), indent=2))
    print(f"  stubs/{name}.json  ({path.stat().st_size:,} bytes)")


# -- GET /zones ---------------------------------------------------------------
# Placeholder geometry: a box around each zone centroid, sized by demand share. Ranya replaces
# this with real DNO service-area polygons. The PROPERTIES are final -- build against those.
features = []
for z in S.ZONES:
    w = 0.8 + 6.0 * z.demand_share
    h = 0.6 + 4.0 * z.demand_share
    features.append(
        {
            "type": "Feature",
            "properties": {
                "zone_id": z.id,
                "name": z.name,
                "demand_share": round(z.demand_share, 3),
                "storage_mwh": z.storage_mwh,
                "dr_mw": z.dr_mw,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [round(z.lon - w, 4), round(z.lat - h, 4)],
                        [round(z.lon + w, 4), round(z.lat - h, 4)],
                        [round(z.lon + w, 4), round(z.lat + h, 4)],
                        [round(z.lon - w, 4), round(z.lat + h, 4)],
                        [round(z.lon - w, 4), round(z.lat - h, 4)],
                    ]
                ],
            },
        }
    )
write("zones", {"type": "FeatureCollection", "features": features})


# -- GET /edges ---------------------------------------------------------------
# Static topology, so the map can draw the corridors before any simulation runs.
write(
    "edges",
    {
        "edges": [
            {
                "edge_id": e.id,
                "from": e.frm,
                "to": e.to,
                "limit_mw": e.limit_mw,
                "circuits": e.circuits,
                "from_lat": S.ZONE_BY_ID[e.frm].lat,
                "from_lon": S.ZONE_BY_ID[e.frm].lon,
                "to_lat": S.ZONE_BY_ID[e.to].lat,
                "to_lon": S.ZONE_BY_ID[e.to].lon,
            }
            for e in S.EDGES
        ]
    },
)


# -- GET /state?t= ------------------------------------------------------------
# Two snapshots: one calm, one mid-incident, so the dashboard's red states can be built and
# styled before anything real is wired up.
env = grid_env.make_scenario_env("b6_trip_windy_peak")
opt = AB.OptimiserAgent()
obs, info = env.reset(seed=1)
calm = None
for k in range(S.STEPS_PER_EPISODE):
    obs, r, term, trunc, info = env.step(opt.act(obs, info))
    if k == 10:
        calm = json.loads(json.dumps(info))
    if k == 38:  # four hours into the B6 trip
        write("state_incident", info)
    if term:
        break
write("state_calm", calm)


# -- GET /state/series --------------------------------------------------------
# One whole episode per strategy, so the split screen shows two genuinely different runs.
# "agents" is not trained yet: it is the optimiser's run, flagged as a placeholder.
def series_for(agent, strategy):
    env2 = grid_env.make_scenario_env("b6_trip_windy_peak")
    obs, info = env2.reset(seed=1)
    frames = []
    for _ in range(S.STEPS_PER_EPISODE):
        obs, r, term, trunc, info = env2.step(agent.act(obs, info))
        frames.append(
            {
                "timestamp_utc": info["timestamp_utc"],
                "zones": {
                    z: {
                        "demand_mw": round(v["demand_mw"], 1),
                        "generation_mw": round(v["generation_mw"], 1),
                        "unserved_mw": round(v["unserved_mw"], 1),
                        "storage_soc": round(v["storage_soc"], 3),
                    }
                    for z, v in info["zones"].items()
                },
                "edges": {
                    e: {"flow_mw": round(v["flow_mw"], 1), "loading_frac": round(v["loading_frac"], 3),
                        "tripped": v["tripped"]}
                    for e, v in info["edges"].items()
                },
                "incidents": info["incidents"],
            }
        )
        if term:
            break
    return {"scenario": "b6_trip_windy_peak", "strategy": strategy, "frames": frames}


write("state_series_none", series_for(AB.NoOpAgent(), "none"))
write("state_series_optimiser", series_for(AB.OptimiserAgent(), "optimiser"))
write("state_series", series_for(AB.OptimiserAgent(), "optimiser"))  # kept for older clients


# -- GET /forecast/{zone_id} --------------------------------------------------
env3 = grid_env.GridEnv()
obs, info = env3.reset(seed=0)
t0 = env3.times[env3.t0]
p50, p90 = env3._forecast_block(env3.t0)
rows = []
for h in range(S.FORECAST_HORIZON):
    base = float(p50[S.ZONE_INDEX["LOND"], 0])
    # A plausible 48-step curve for the stub; the real one comes from Eugene's model.
    import math

    shape = 1.0 + 0.18 * math.sin(2 * math.pi * (h - 10) / 48.0)
    mid = base * shape
    spread = 0.04 + 0.0025 * h  # widens with horizon, as a real forecast does
    rows.append([round(mid * (1 - spread), 1), round(mid, 1), round(mid * (1 + spread), 1)])

write(
    "forecast_LOND",
    {
        "zone_id": "LOND",
        "issue_time_utc": t0.isoformat(),
        "unit": "MW",
        "quantiles": ["p10", "p50", "p90"],
        "timestamps_utc": [(t0 + timedelta(minutes=30 * i)).isoformat() for i in range(48)],
        "forecast": rows,
        "explanation": [
            "colder than usual for the time of year",
            "demand elevated over the last 24 hours",
            "weekday evening peak approaching",
        ],
    },
)


# -- GET /compare -------------------------------------------------------------
def totals(agent, name):
    e = grid_env.make_scenario_env(name)
    o, i = e.reset(seed=1)
    for _ in range(S.STEPS_PER_EPISODE):
        o, r, t, tr, i = e.step(agent.act(o, i))
        if t:
            break
    return {k: round(v, 1) for k, v in i["totals"].items()}


compare = {}
for name in S.SCENARIOS:
    strategies = {
        "none": totals(AB.NoOpAgent(), name),
        "optimiser": totals(AB.OptimiserAgent(), name),
    }
    # "agents" is not trained yet. Shown here as the optimiser's numbers so the scoreboard
    # renders; Eugene overwrites this with the real policy at stage 11.
    strategies["agents"] = dict(strategies["optimiser"])
    compare[name] = {"scenario": name, "strategies": strategies, "agents_is_placeholder": True}
write("compare", compare)


# -- GET /scenarios -----------------------------------------------------------
write(
    "scenarios",
    {
        "scenarios": [
            {
                "name": n,
                "description": json.loads(
                    (Path(S.SCENARIO_DIR) / f"{n}.json").read_text()
                )["description"],
            }
            for n in S.SCENARIOS
        ]
    },
)


# -- POST /incident -----------------------------------------------------------
write(
    "incident_response",
    {
        "ok": True,
        "incident_id": "inc_7f3a",
        "incident": S.Incident("line_trip", "SSCO-NORT", 34, 14, 0.5).to_dict(),
    },
)


# -- reference: the enumerations the UI needs ---------------------------------
write(
    "reference",
    {
        "zone_order": list(S.ZONE_ORDER),
        "edge_order": list(S.EDGE_ORDER),
        "fuel_order": list(S.FUEL_ORDER),
        "fuels": [
            {
                "id": f.id,
                "cost_gbp_per_mwh": f.cost_gbp_per_mwh,
                "carbon_t_per_mwh": f.carbon_t_per_mwh,
                "dispatchable": f.dispatchable,
                "curtailable": f.curtailable,
            }
            for f in S.FUELS
        ],
        "incident_types": list(S.INCIDENT_TYPES),
        "strategies": list(S.STRATEGIES),
        "quality_flags": {
            "OK": S.QF.OK,
            "MISSING": S.QF.MISSING,
            "INTERPOLATED": S.QF.INTERPOLATED,
            "ZERO_RUN": S.QF.ZERO_RUN,
            "JUMP": S.QF.JUMP,
            "DST_BOUNDARY": S.QF.DST_BOUNDARY,
        },
        "steps_per_episode": S.STEPS_PER_EPISODE,
        "forecast_horizon": S.FORECAST_HORIZON,
    },
)

print("\nall stubs written. serve them from disk at hour 0.")
