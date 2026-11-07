"""Stage 3: archived forecast weather for the contract's zones.

Run from JMap: python pulls/pull_weather.py --offline
The saved issue time is the runbook's proxy, not an exact model-run timestamp.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pull_neso import make_session


API = "https://historical-forecast-api.open-meteo.com/v1/forecast"
VARIABLES = {
    "temperature_2m": "temp_c",
    "wind_speed_100m": "wind_ms",
    "shortwave_radiation": "solar_wm2",
}
UNITS = {"temperature_2m": "°C", "wind_speed_100m": "m/s",
         "shortwave_radiation": "W/m²"}
SCHEMA = pa.schema([
    ("zone_id", pa.string()),
    ("timestamp_utc", pa.timestamp("us", tz="UTC")),
    ("temp_c", pa.float32()),
    ("wind_ms", pa.float32()),
    ("solar_wm2", pa.float32()),
    ("weather_issue_time_utc", pa.timestamp("us", tz="UTC")),
])


def load_zones(root: Path, zones_file: Path | None):
    if zones_file is not None:
        # Supports preparatory downloads from an exported contract coordinate list.
        zones = json.loads(zones_file.read_text(encoding="utf-8"))
    else:
        path = root / "schemas.py"
        spec = importlib.util.spec_from_file_location("_weather_contract", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module  # dataclasses resolve their owning module here.
        spec.loader.exec_module(module)
        zones = [{"id": z.id, "lat": float(z.lat), "lon": float(z.lon)}
                 for z in module.ZONES]
        if [z["id"] for z in zones] != list(module.ZONE_ORDER):
            raise ValueError("schemas.ZONES and ZONE_ORDER disagree")
    if not zones or len({z["id"] for z in zones}) != len(zones):
        raise ValueError("Empty or repeated contract zones")
    for z in zones:
        if not (-90 <= z["lat"] <= 90 and -180 <= z["lon"] <= 180):
            raise ValueError(f"Invalid coordinates for {z['id']}")
    return zones


def load_hourly(session, root: Path, zone: dict, stamps: pd.DatetimeIndex,
                offline: bool):
    # Fetch the following UTC day too, so the last 23:30 value is bracketed.
    params = {
        "latitude": zone["lat"], "longitude": zone["lon"],
        "start_date": stamps.min().strftime("%Y-%m-%d"),
        "end_date": stamps.max().ceil("h").strftime("%Y-%m-%d"),
        "hourly": ",".join(VARIABLES),
        "timezone": "UTC", "wind_speed_unit": "ms", "temperature_unit": "celsius",
    }
    folder = root / "data/raw/weather"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{zone['id']}.json"
    meta_path = path.with_suffix(".source.json")
    if not path.exists() and not offline:
        print(f"Downloading {zone['id']} ({zone['lat']}, {zone['lon']})...", flush=True)
        response = session.get(API, params=params, timeout=(15, 120))
        response.raise_for_status()
        # Save untouched response bytes before decoding or parsing weather values.
        temporary = path.with_suffix(".json.tmp")
        temporary.write_bytes(response.content)
        temporary.replace(path)
        meta_path.write_text(json.dumps({
            "source_url": response.url, "request_params": params,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(response.content).hexdigest(),
        }, indent=2) + "\n", encoding="utf-8")
        time.sleep(0.5)
    if not path.exists() or not meta_path.exists():
        raise FileNotFoundError(f"Missing saved weather for {zone['id']}; run without --offline")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if metadata["request_params"] != params:
        raise ValueError(f"Cached coordinates, dates or units differ from the contract for {zone['id']}")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
        raise ValueError(f"Saved response hash differs for {zone['id']}")
    payload = json.loads(raw)
    if payload.get("error"):
        raise ValueError(f"Open-Meteo error for {zone['id']}: {payload}")
    if payload.get("utc_offset_seconds") != 0:
        raise ValueError("Weather response is not UTC")
    for name, unit in UNITS.items():
        if payload.get("hourly_units", {}).get(name) != unit:
            raise ValueError(f"Unexpected unit for {zone['id']} {name}")
    hourly = payload["hourly"]
    index = pd.DatetimeIndex(pd.to_datetime(hourly["time"], utc=True, errors="raise")).as_unit("ns")
    frame = pd.DataFrame({VARIABLES[k]: hourly[k] for k in VARIABLES}, index=index)
    expected = pd.date_range(index.min(), index.max(), freq="h", tz="UTC").as_unit("ns")
    if not index.equals(expected) or not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError(f"Missing, repeated or non-finite source hours for {zone['id']}")
    if index.min() > stamps.min() or index.max() < stamps.max():
        raise ValueError(f"Source does not bracket all demand times for {zone['id']}")
    return frame


def resample_zone(hourly: pd.DataFrame, stamps: pd.DatetimeIndex, zone_id: str):
    # Normalize internal precision across pandas versions; Arrow writes us below.
    hourly = hourly.copy()
    hourly.index = hourly.index.as_unit("ns")
    stamps = stamps.as_unit("ns")
    # Interpolate inserted half-hours only. Source hourly gaps already fail above.
    combined = hourly.reindex(hourly.index.union(stamps))
    frame = combined.interpolate(method="time", limit=1, limit_area="inside").loc[stamps].copy()
    if not np.isfinite(frame.to_numpy()).all():
        raise ValueError(f"Unfilled weather values for {zone_id}")
    negative_solar = int(frame.solar_wm2.lt(0).sum())
    frame["solar_wm2"] = frame.solar_wm2.clip(lower=0)
    frame.index.name = "timestamp_utc"
    frame = frame.reset_index()
    frame.insert(0, "zone_id", zone_id)
    frame["weather_issue_time_utc"] = (
        frame.timestamp_utc.dt.floor("D") - pd.Timedelta(days=1) + pd.Timedelta(hours=6))
    return frame[list(SCHEMA.names)], negative_solar


def validate(frame: pd.DataFrame, stamps: pd.DatetimeIndex, zones: list, clamped: int):
    if frame.duplicated(["zone_id", "timestamp_utc"]).any():
        raise ValueError("Duplicate zone/time keys")
    if frame.isna().any().any():
        raise ValueError("Null weather or issue-time values")
    if frame.wind_ms.lt(0).any() or frame.solar_wm2.lt(0).any():
        raise ValueError("Negative wind speed or solar radiation")
    if not frame.weather_issue_time_utc.lt(frame.timestamp_utc).all():
        raise ValueError("Proxy issue time must precede valid time")
    if set(frame.zone_id) != {z["id"] for z in zones}:
        raise ValueError("Unexpected zone IDs")
    lines = [
        "Stage 3 weather checks: PASS (coverage and format; forecast vintage remains approximate)",
        f"Zones: {len(zones)}; rows per zone: {len(stamps):,}; total rows: {len(frame):,}",
        f"UTC interval starts: {stamps.min()} -> {stamps.max()}",
        "Demand/weather timestamp coverage per zone: 100.00%",
        "Duplicates: 0; missing half-hours: 0; null values: 0",
        "Wind units explicitly requested and verified: m/s at 100 m",
        f"Negative interpolated solar values clamped to zero: {clamped}",
        "zone | rows | temp min / mean / max C | wind max m/s | solar max 23:00-03:00 UTC | solar max 23:00-01:00 UTC",
    ]
    for zone in zones:
        subset = frame.loc[frame.zone_id.eq(zone["id"])].sort_values("timestamp_utc")
        if not pd.DatetimeIndex(subset.timestamp_utc).as_unit("ns").equals(stamps.as_unit("ns")):
            raise ValueError(f"Incomplete timestamp grid for {zone['id']}")
        minute = subset.timestamp_utc.dt.hour * 60 + subset.timestamp_utc.dt.minute
        broad = subset.loc[minute.ge(23 * 60) | minute.le(3 * 60), "solar_wm2"].max()
        core = subset.loc[minute.ge(23 * 60) | minute.le(60), "solar_wm2"].max()
        if core > 5:
            raise ValueError(f"Unexpected deep-night solar radiation for {zone['id']}: {core} W/m2")
        stats = subset.temp_c.agg(["min", "mean", "max"])
        lines.append(f"{zone['id']} | {len(subset):,} | {stats['min']:.1f} / {stats['mean']:.1f} / "
                     f"{stats['max']:.1f} | {subset.wind_ms.max():.2f} | {broad:.2f} | {core:.2f}")
    lines += [
        "Both solar windows include their stated endpoints. Scotland can have summer daylight at 03:00 UTC.",
        "FORECAST-VINTAGE LIMITATION: this endpoint stitches short forecasts from successive runs.",
        "weather_issue_time_utc = previous UTC calendar day at 06:00 is a contractual PROXY.",
        "It is not a returned or reconstructed model initialization/publication time.",
        "This data does not prove that weather was available at a historical day-ahead issue time.",
        "Do not claim leakage-free day-ahead forecast evaluation with this proxy.",
        "For that evaluation, use actual single-run archives with known initialization and availability times.",
        "Hourly temperature/wind are linearly interpolated to half-hours; these are not extra observations.",
        "Solar follows the runbook's same linear interpolation. The source is a preceding-hour mean,",
        "so solar_wm2 is an approximate feature, not an exact half-hour interval-average irradiance.",
        "Each zone uses one centroid/grid cell rather than a spatially weighted weather average.",
        "The canonical quality INTERPOLATED bit concerns filled demand targets, not routine weather resampling.",
        "The project's canonical checker is still needed at Stage 5.",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--zones-file", type=Path,
                        help="Optional exported id/lat/lon JSON; by default read the project's schemas.py")
    args = parser.parse_args()
    root = args.root.resolve()
    zones = load_zones(root, args.zones_file)
    demand = pd.read_parquet(root / "data/raw/neso/national_demand.parquet")
    stamps = pd.DatetimeIndex(demand.timestamp_utc.sort_values()).as_unit("ns")
    if stamps.tz is None or str(stamps.tz) != "UTC" or not stamps.equals(
            pd.date_range(stamps.min(), stamps.max(), freq="30min", tz="UTC").as_unit("ns")):
        raise ValueError("Demand must have a complete, unique UTC half-hour grid")
    parts, clamped = [], 0
    with make_session() as session:
        for zone in zones:
            hourly = load_hourly(session, root, zone, stamps, args.offline)
            part, count = resample_zone(hourly, stamps, zone["id"])
            parts.append(part)
            clamped += count
    frame = pd.concat(parts, ignore_index=True).sort_values(["zone_id", "timestamp_utc"])
    report = validate(frame, stamps, zones, clamped)
    table = pa.Table.from_pandas(frame, schema=SCHEMA, preserve_index=False)
    path = root / "data/raw/weather/weather.parquet"
    temporary = path.with_suffix(".parquet.tmp")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(path)
    results = root / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "stage3_checks.txt").write_text(report + "\n", encoding="utf-8")
    (root / "data/raw/weather/provenance.json").write_text(json.dumps({
        "source_endpoint": API, "model_selection": "Open-Meteo default best_match",
        "zones": zones, "issue_time_kind": "proxy_not_actual_forecast_issue_time",
        "issue_time_rule": "previous UTC calendar day at 06:00",
        "half_hour_method": "linear interpolation at source time labels; no edge extrapolation",
        "solar_source_semantics": "preceding-hour average, used as approximate interpolated feature",
    }, indent=2) + "\n", encoding="utf-8")
    print(report)
    print(f"Wrote: {path}")


if __name__ == "__main__":
    main()
