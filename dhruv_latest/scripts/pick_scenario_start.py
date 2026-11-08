"""Find half-hours that genuinely meet the B6 demo condition, from any canonical table.

The B6 scenario needs a windy winter evening peak: Scottish wind high, national demand high,
evening. Those are the conditions that load the Scotland-England boundary, so that losing it
actually hurts. Picking a date by eye gets this wrong -- high wind and high demand do not
usually coincide.

Note what this does and does not require. We are not claiming the boundary historically tripped
on the chosen date. The trip is a counterfactual the simulator injects; all we need from the data
is a plausible real starting state. So the only requirement is that the conditions existed.

Usage:
    python3 scripts/pick_scenario_start.py data/canonical/_winter.parquet
    python3 scripts/pick_scenario_start.py data/canonical/real.parquet --write
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

import schemas as S

path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/canonical/_fake.parquet")
WRITE = "--write" in sys.argv

SCOTLAND = ("NSCO", "SSCO")
EVENING_HH = range(32, 42)  # 16:00-21:00 UTC


def turbine_frac(w):
    out = np.clip((np.asarray(w, dtype=float) - 3.0) / 9.0, 0.0, 1.0) ** 3
    return np.where(np.asarray(w, dtype=float) > 25.0, 0.0, out)


df = pq.read_table(path).to_pandas()
df = df.sort_values(["zone_id", "timestamp_utc"])

wind_cap = {z.id: z.capacity_mw["WIND"] for z in S.ZONES}
df["wind_mw"] = turbine_frac(df["wind_ms"]) * df["zone_id"].map(wind_cap)

per_t = df.groupby("timestamp_utc").agg(
    national_demand_mw=("demand_mw", "sum"),
    national_wind_mw=("wind_mw", "sum"),
)
scot = (
    df[df.zone_id.isin(SCOTLAND)]
    .groupby("timestamp_utc")
    .agg(scot_wind_mw=("wind_mw", "sum"), scot_demand_mw=("demand_mw", "sum"))
)
t = per_t.join(scot).dropna()
t["scot_surplus_mw"] = t["scot_wind_mw"] - t["scot_demand_mw"]
t["hh"] = (t.index.hour * 2 + (t.index.minute >= 30).astype(int))
t["month"] = t.index.month

d_thresh = t["national_demand_mw"].quantile(0.90)
w_thresh = t["scot_wind_mw"].quantile(0.90)

print(f"=== {path.name} ===")
print(f"half-hours        : {len(t):,}")
print(f"range             : {t.index.min()} -> {t.index.max()}")
print(f"months present    : {sorted(t['month'].unique())}")
print()
print(f"national demand   : p50 {t.national_demand_mw.median():,.0f} MW   "
      f"p90 {d_thresh:,.0f} MW   max {t.national_demand_mw.max():,.0f} MW")
print(f"Scottish wind     : p50 {t.scot_wind_mw.median():,.0f} MW   "
      f"p90 {w_thresh:,.0f} MW   max {t.scot_wind_mw.max():,.0f} MW")
print()

winter = t["month"].isin([11, 12, 1, 2])
evening = t["hh"].isin(EVENING_HH)

tiers = [
    ("demand p90 + Scottish wind p90 + evening + winter", (t.national_demand_mw >= d_thresh) & (t.scot_wind_mw >= w_thresh) & evening & winter),
    ("demand p90 + Scottish wind p90 + evening", (t.national_demand_mw >= d_thresh) & (t.scot_wind_mw >= w_thresh) & evening),
    ("demand p90 + Scottish wind p90", (t.national_demand_mw >= d_thresh) & (t.scot_wind_mw >= w_thresh)),
    ("demand p75 + Scottish wind p75", (t.national_demand_mw >= t.national_demand_mw.quantile(0.75)) & (t.scot_wind_mw >= t.scot_wind_mw.quantile(0.75))),
]

chosen = None
for label, mask in tiers:
    n = int(mask.sum())
    print(f"{label:52} {n:5d} half-hours")
    if chosen is None and n >= 1:
        chosen = (label, mask)

print()
if chosen is None:
    print("NO QUALIFYING CONDITIONS in this file.")
    print("High wind and high demand never coincide here. Use a winter table:")
    print("  python3 -I scripts/make_fake_canonical.py 120 data/canonical/_winter.parquet 4242 2026-03-01")
    sys.exit(1)

label, mask = chosen
cand = t[mask].copy()
# Rank by how much power Scotland is trying to push south: that is what loads the boundary.
cand = cand.sort_values("scot_surplus_mw", ascending=False)

print(f"best tier met: {label}")
print()
print(f"{'timestamp_utc':26} {'nat demand':>11} {'scot wind':>10} {'scot surplus':>13}")
print("-" * 64)
for ts, r in cand.head(10).iterrows():
    print(f"{str(ts):26} {r.national_demand_mw:11,.0f} {r.scot_wind_mw:10,.0f} {r.scot_surplus_mw:13,.0f}")

best = cand.index[0]
# Back up to the start of that day: an episode is 48 steps from midnight, and the trip is
# injected at the step matching the chosen half-hour.
day_start = best.normalize()
step = int((best - day_start).total_seconds() // 1800)

print()
print("USE THIS:")
print(f"  episode start (UTC midnight) : {day_start}")
print(f"  trip at step                 : {step}  ({best.strftime('%H:%M')} UTC)")
print(f"  Scottish surplus then        : {cand.loc[best, 'scot_surplus_mw']:,.0f} MW")
print(f"  national demand then         : {cand.loc[best, 'national_demand_mw']:,.0f} MW")

if WRITE:
    import json

    p = Path(S.SCENARIO_DIR) / "b6_trip_windy_peak.json"
    body = json.loads(p.read_text())
    body["incidents"] = [
        S.Incident("line_trip", S.B6_EDGE, step, 14, 1.0).to_dict()
    ]
    body["selected_from"] = str(path)
    body["episode_start_utc"] = day_start.isoformat()
    body["conditions"] = {
        "tier": label,
        "national_demand_mw": round(float(cand.loc[best, "national_demand_mw"]), 1),
        "scottish_wind_mw": round(float(cand.loc[best, "scot_wind_mw"]), 1),
        "scottish_surplus_mw": round(float(cand.loc[best, "scot_surplus_mw"]), 1),
    }
    p.write_text(json.dumps(body, indent=2))
    print(f"\nwrote {p}")
