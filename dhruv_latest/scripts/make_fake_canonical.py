"""Generate a contract-conforming fake canonical table.

This is the 30-minute hour-0 job: a stub with the RIGHT SHAPE so Eugene and Leonard can start
before any real data exists. The numbers are plausible, not real.

Usage: python3 -I scripts/make_fake_canonical.py [days] [out_path] [seed] [end_date]
Default: 21 days ending today, seed 20261107, written to data/canonical/_fake.parquet

end_date is YYYY-MM-DD, so a winter window can be generated for scenario-selection work before
real data lands:
    python3 -I scripts/make_fake_canonical.py 120 data/canonical/_winter.parquet 4242 2026-03-01

The seed is explicit so a second, independent draw can be generated for validation:
    python3 -I scripts/make_fake_canonical.py 180 data/canonical/_holdout.parquet 777

Read the note at the bottom of this file before treating such a draw as evidence of model
quality.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/home/claude")

import numpy as np  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

import schemas as S  # noqa: E402

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 21
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/canonical/_fake.parquet")
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 20261107
END_DATE = sys.argv[4] if len(sys.argv) > 4 else None

rng = np.random.default_rng(SEED)

# --- national demand shape -------------------------------------------------
# Half-hourly multipliers, 00:00 to 23:30 UTC. Trough ~04:00, evening peak ~17:30.
# Peak-to-trough ratio about 1.6, which is what GB actually does.
PROFILE = np.array(
    [
        0.86, 0.83, 0.81, 0.79, 0.78, 0.77, 0.76, 0.76, 0.76, 0.77, 0.80, 0.85,
        0.92, 0.99, 1.05, 1.09, 1.11, 1.12, 1.12, 1.11, 1.10, 1.09, 1.08, 1.08,
        1.07, 1.07, 1.06, 1.05, 1.04, 1.04, 1.05, 1.07, 1.11, 1.16, 1.21, 1.23,
        1.22, 1.19, 1.15, 1.11, 1.07, 1.04, 1.01, 0.98, 0.95, 0.92, 0.90, 0.88,
    ]
)
PROFILE = PROFILE / PROFILE.mean()

# National average demand by month, GW. Winter high, summer low.
NATIONAL_GW = {
    1: 36.0, 2: 35.0, 3: 32.0, 4: 29.0, 5: 27.0, 6: 26.0,
    7: 26.0, 8: 26.0, 9: 28.0, 10: 31.0, 11: 34.0, 12: 36.0,
}

WEEKEND_FACTOR = 0.90

# Seasonal mean temperature at 55N, degC, by month.
TEMP_BASE = {
    1: 4.0, 2: 4.5, 3: 6.5, 4: 9.0, 5: 12.0, 6: 15.0,
    7: 17.0, 8: 16.5, 9: 14.0, 10: 10.5, 11: 6.5, 12: 4.5,
}

# How much extra demand each zone draws per degree below 15C, as a fraction.
# Higher where more homes are electrically heated.
HEAT_SENSITIVITY = {
    "NSCO": 0.022, "SSCO": 0.018, "NORT": 0.014, "YORK": 0.013, "WALE": 0.016,
    "MIDL": 0.012, "EAST": 0.011, "SWES": 0.014, "LOND": 0.008, "SOUT": 0.011,
}

# --- time index ------------------------------------------------------------
if END_DATE:
    y, m, d = (int(x) for x in END_DATE.split("-"))
    end = datetime(y, m, d, tzinfo=timezone.utc)
else:
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = end - timedelta(hours=end.hour % 24)  # midnight UTC today
start = end - timedelta(days=DAYS)
n_steps = DAYS * 48
times = [start + timedelta(minutes=30 * i) for i in range(n_steps)]

# GB clock-change days 2026: 29 March (forward), 25 October (back).
DST_DAYS = {(2026, 3, 29), (2026, 10, 25), (2027, 3, 28), (2027, 10, 31)}


def solar_wm2(ts: datetime, lat: float, cloud: float) -> float:
    """Crude clear-sky shortwave, zeroed when the sun is below the horizon."""
    doy = ts.timetuple().tm_yday
    decl = np.radians(23.45) * np.sin(2 * np.pi * (284 + doy) / 365.0)
    hour = ts.hour + ts.minute / 60.0
    hour_angle = np.radians(15.0 * (hour - 12.0))
    latr = np.radians(lat)
    elev = np.arcsin(
        np.sin(latr) * np.sin(decl) + np.cos(latr) * np.cos(decl) * np.cos(hour_angle)
    )
    if elev <= 0:
        return 0.0
    return float(950.0 * np.sin(elev) * (1.0 - 0.75 * cloud))


rows: dict[str, list] = {c: [] for c in S.CANONICAL_COLUMNS}

for zone in S.ZONES:
    share = zone.demand_share
    sens = HEAT_SENSITIVITY[zone.id]

    # AR(1) wind and cloud walks, so consecutive half-hours correlate like weather does.
    wind = np.empty(n_steps)
    cloud = np.empty(n_steps)
    wind[0] = rng.uniform(3, 10)
    cloud[0] = rng.uniform(0.2, 0.8)
    for i in range(1, n_steps):
        wind[i] = np.clip(0.97 * wind[i - 1] + rng.normal(0, 0.6) + 0.03 * 7.0, 0.8, 24.0)
        cloud[i] = np.clip(0.95 * cloud[i - 1] + rng.normal(0, 0.07) + 0.05 * 0.5, 0.0, 1.0)

    # Persistent demand deviation: the part of real demand no feature explains -- weather the
    # forecast missed, behaviour, local events. AR(1) at phi=0.97 per half-hour, a half-life of
    # about 11 hours, stationary sd 2.5%. This is what makes recent observed demand genuinely
    # informative about the next few hours, and that information decays with lead time. Without
    # it, error is flat across horizons and the horizon-degradation gate cannot pass even for a
    # perfect model.
    PHI, DEV_SD = 0.97, 0.025
    dev = np.empty(n_steps)
    dev[0] = rng.normal(0, DEV_SD)
    for i in range(1, n_steps):
        dev[i] = PHI * dev[i - 1] + rng.normal(0, DEV_SD * np.sqrt(1 - PHI**2))

    # Day-ahead weather forecast error, slowly varying (phi 0.9 per half-hour). The table carries
    # the forecast; demand responds to the truth. Same relationship as real data.
    terr = np.empty(n_steps)
    werr = np.empty(n_steps)
    terr[0], werr[0] = rng.normal(0, 1.2), rng.normal(0, 1.5)
    for i in range(1, n_steps):
        terr[i] = 0.9 * terr[i - 1] + rng.normal(0, 1.2 * np.sqrt(1 - 0.81))
        werr[i] = 0.9 * werr[i - 1] + rng.normal(0, 1.5 * np.sqrt(1 - 0.81))

    # Latitude drives both temperature and day length.
    lat_offset = -(zone.lat - 52.5) * 0.55

    for i, ts in enumerate(times):
        hh = ts.hour * 2 + (1 if ts.minute >= 30 else 0)

        # temperature: seasonal base + daily cycle (min 05:00, max 15:00) + latitude + noise
        t_base = TEMP_BASE[ts.month] + lat_offset
        daily = 4.0 * np.sin(2 * np.pi * (hh - 10) / 48.0)
        temp = t_base + daily + rng.normal(0, 0.7) - 2.5 * cloud[i] + 1.0
        temp = float(np.round(temp, 1))

        # demand
        nat = NATIONAL_GW[ts.month] * 1000.0
        if ts.weekday() >= 5:
            nat *= WEEKEND_FACTOR
        heat = 1.0 + sens * max(0.0, 15.0 - temp)
        # Driven by TRUE temperature and the persistent deviation, plus a little white noise.
        mw = nat * PROFILE[hh] * share * heat * (1.0 + dev[i]) * (1.0 + rng.normal(0, 0.005))

        flag = S.QF.OK
        if (ts.year, ts.month, ts.day) in DST_DAYS:
            flag |= S.QF.DST_BOUNDARY

        # Inject a little real-world mess so the exclusion logic gets exercised.
        r = rng.random()
        if r < 0.004:
            flag |= S.QF.MISSING
            mw = float("nan")
        elif r < 0.010:
            flag |= S.QF.INTERPOLATED

        rows["zone_id"].append(zone.id)
        rows["timestamp_utc"].append(ts)
        rows["demand_mw"].append(mw)
        # The table carries the FORECAST, not the truth the demand responded to.
        rows["temp_c"].append(float(np.round(temp + terr[i], 1)))
        rows["wind_ms"].append(float(np.round(max(0.0, wind[i] + werr[i]), 1)))
        rows["solar_wm2"].append(round(solar_wm2(ts, zone.lat, float(cloud[i])), 1))
        # Weather as it would have been forecast, not observed: the 06:00 UTC run of the
        # previous day. This is the leakage discipline, baked into the stub.
        issue = (ts - timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
        rows["weather_issue_time_utc"].append(issue)
        rows["quality_flag"].append(flag)
        rows["is_estimated"].append(True)

# --- write with the contract's exact types ---------------------------------
schema = pa.schema(
    [
        ("zone_id", pa.string()),
        ("timestamp_utc", pa.timestamp("us", tz="UTC")),
        ("demand_mw", pa.float32()),
        ("temp_c", pa.float32()),
        ("wind_ms", pa.float32()),
        ("solar_wm2", pa.float32()),
        ("weather_issue_time_utc", pa.timestamp("us", tz="UTC")),
        ("quality_flag", pa.uint8()),
        ("is_estimated", pa.bool_()),
    ]
)

table = pa.table({c: rows[c] for c in S.CANONICAL_COLUMNS}, schema=schema)

OUT.parent.mkdir(parents=True, exist_ok=True)
pq.write_table(table, OUT, compression="snappy")

print(f"wrote {OUT}  ({table.num_rows:,} rows, {OUT.stat().st_size:,} bytes)")
print(f"  {len(S.ZONES)} zones x {n_steps:,} half-hours")
print(f"  {start:%Y-%m-%d %H:%M} -> {times[-1]:%Y-%m-%d %H:%M} UTC")
print(f"  seed {SEED}")

# WHAT A SECOND DRAW FROM THIS GENERATOR DOES AND DOES NOT TELL YOU
#
# Changing the seed gives an independent realisation of the SAME process. That is genuinely
# useful for one class of bug: code that has quietly come to depend on specific values, column
# orders or row counts in one file. If a pipeline passes on one seed and fails on another,
# something is hardcoded that should not be.
#
# It is NOT evidence that a model is accurate. The generator has a fixed daily profile, a fixed
# temperature response and Gaussian noise. A model fitted to that structure will score well on
# any draw from it, and the score says nothing about real demand, which has strikes, storms,
# televised football, failed substations and weekdays that behave like weekends.
#
# The only honest holdout is real data. Until Ranya's table lands, treat every accuracy number
# as "the pipeline runs", never as "the model works".
