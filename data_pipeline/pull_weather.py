"""Stage 3: Previous Runs day-ahead weather for the contract's zones.

Run from JMap: python data_pipeline/pull_weather.py --offline
The saved issue time is valid time minus 24h, not an exact model-run timestamp.
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
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pull_neso import make_session

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_window import (INTERPOLATION_CAVEAT, WEATHER_CAVEAT, WINDOW_REASON,
                         require_window_grid, trim_to_window)

API = "https://previous-runs-api.open-meteo.com/v1/forecast"
VARIABLES = {
    "temperature_2m_previous_day1": "temp_c",
    "wind_speed_100m_previous_day1": "wind_ms",
    "shortwave_radiation_previous_day1": "solar_wm2",
}
UNITS = {"temperature_2m_previous_day1": "°C", "wind_speed_100m_previous_day1": "m/s",
         "shortwave_radiation_previous_day1": "W/m²"}
SCHEMA = pa.schema([
    ("zone_id", pa.string()),
    ("timestamp_utc", pa.timestamp("us", tz="UTC")),
    ("temp_c", pa.float32()),
    ("wind_ms", pa.float32()),
    ("solar_wm2", pa.float32()),
    ("weather_issue_time_utc", pa.timestamp("us", tz="UTC")),
])


def archive_legacy_weather(root: Path):
    """Move old endpoint caches together, without overwriting an earlier backup."""
    folder = root / "data/raw/weather"
    if not folder.exists():
        return
    sources = list(folder.glob("*.source.json"))
    if not sources:
        if any(folder.iterdir()):
            raise ValueError("Weather folder has no source metadata; inspect it before replacing")
        return
    endpoints = [urlsplit(json.loads(p.read_text(encoding="utf-8"))["source_url"]).netloc
                 for p in sources]
    if all(host == urlsplit(API).netloc for host in endpoints):
        return
    if any(host == urlsplit(API).netloc for host in endpoints):
        raise ValueError("Mixed old/new weather caches; inspect the folder before replacing")
    backup = folder.with_name("weather_OLD_DO_NOT_USE")
    if backup.exists():
        raise FileExistsError("Both old weather folders exist; refusing to overwrite the backup")
    folder.rename(backup)
    print(f"Archived old weather: {backup}", flush=True)


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
    if urlsplit(metadata["source_url"]).netloc != urlsplit(API).netloc:
        raise ValueError(f"Cached response is not from the Previous Runs endpoint: {zone['id']}")
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
    if not index.equals(expected):
        raise ValueError(f"Missing or repeated source hour labels for {zone['id']}")
    if index.min() > stamps.min() or index.max() < stamps.max():
        raise ValueError(f"Source does not bracket all demand times for {zone['id']}")
    # Ignore surplus requested hours after the final interpolation bracket.
    frame = frame.loc[stamps.min().floor("h"):stamps.max().ceil("h")]
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError(f"Missing/non-finite source hours for {zone['id']}; no gap filling allowed")
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
    frame["weather_issue_time_utc"] = frame.timestamp_utc - pd.Timedelta(hours=24)
    return frame[list(SCHEMA.names)], negative_solar


def validate(frame: pd.DataFrame, stamps: pd.DatetimeIndex, zones: list, clamped: int,
             old: pd.DataFrame | None):
    if frame.duplicated(["zone_id", "timestamp_utc"]).any():
        raise ValueError("Duplicate zone/time keys")
    if frame.isna().any().any():
        raise ValueError("Null weather or issue-time values")
    if frame.wind_ms.lt(0).any() or frame.solar_wm2.lt(0).any():
        raise ValueError("Negative wind speed or solar radiation")
    issue = pd.DatetimeIndex(frame.weather_issue_time_utc).as_unit("ns")
    valid = pd.DatetimeIndex(frame.timestamp_utc).as_unit("ns")
    if not issue.equals(valid - pd.Timedelta(hours=24)):
        raise ValueError("Weather issue upper bound must equal valid time minus 24h")
    if set(frame.zone_id) != {z["id"] for z in zones}:
        raise ValueError("Unexpected zone IDs")
    lines = [
        "Stage 3 Previous Runs weather checks: PASS",
        f"Zones: {len(zones)}; rows per zone: {len(stamps):,}; total rows: {len(frame):,}",
        f"UTC interval starts: {stamps.min()} -> {stamps.max()}",
        "Demand/weather timestamp coverage per zone: 100.00%",
        "Duplicates: 0; missing half-hours: 0; null values: 0",
        "Wind units explicitly requested and verified: m/s at 100 m",
        f"Negative interpolated solar values clamped to zero: {clamped}",
        "zone | rows | first UTC -> last UTC | temp min / mean / max C | wind max m/s | solar max 23:00-03:00 UTC | mean abs temp change C",
    ]
    for zone in zones:
        subset = frame.loc[frame.zone_id.eq(zone["id"])].sort_values("timestamp_utc")
        if not pd.DatetimeIndex(subset.timestamp_utc).as_unit("ns").equals(stamps.as_unit("ns")):
            raise ValueError(f"Incomplete timestamp grid for {zone['id']}")
        minute = subset.timestamp_utc.dt.hour * 60 + subset.timestamp_utc.dt.minute
        broad = subset.loc[minute.ge(23 * 60) | minute.le(3 * 60), "solar_wm2"].max()
        if broad > 5:
            raise ValueError(f"Unexpected night solar radiation for {zone['id']}: {broad} W/m2")
        difference_text = "not available"
        if old is not None:
            comparison = subset.merge(old.loc[old.zone_id.eq(zone["id"]), ["timestamp_utc", "temp_c"]],
                                      on="timestamp_utc", how="left", validate="one_to_one",
                                      suffixes=("", "_old"))
            if comparison.temp_c_old.isna().any():
                raise ValueError(f"Old temperature comparison is incomplete for {zone['id']}")
            difference = float((comparison.temp_c - comparison.temp_c_old).abs().mean())
            if difference < 0.05:
                raise ValueError(f"New/old temperature difference is near zero for {zone['id']}: {difference}")
            difference_text = f"{difference:.3f}"
        stats = subset.temp_c.agg(["min", "mean", "max"])
        lines.append(f"{zone['id']} | {len(subset):,} | {subset.timestamp_utc.min()} -> "
                     f"{subset.timestamp_utc.max()} | {stats['min']:.1f} / {stats['mean']:.1f} / "
                     f"{stats['max']:.1f} | {subset.wind_ms.max():.2f} | {broad:.2f} | {difference_text}")
    if old is None:
        lines.append("Old-weather comparison unavailable on this clean build; endpoint, variables, units and coverage were checked.")
    lines += [
        "The night solar window includes both stated endpoints; maximum accepted is 5 W/m2.",
        "Temperature differences are a source-change sanity check, not forecast error against observations.",
        WINDOW_REASON,
        WEATHER_CAVEAT,
        INTERPOLATION_CAVEAT,
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
    archive_legacy_weather(root)
    demand = trim_to_window(pd.read_parquet(root / "data/raw/neso/national_demand.parquet"))
    stamps = require_window_grid(demand.timestamp_utc.sort_values(), "National demand")
    old_path = root / "data/raw/weather_OLD_DO_NOT_USE/weather.parquet"
    # This migration diagnostic is optional for a clean Previous Runs rebuild.
    old = trim_to_window(pd.read_parquet(old_path)) if old_path.is_file() else None
    parts, clamped = [], 0
    with make_session() as session:
        for zone in zones:
            hourly = load_hourly(session, root, zone, stamps, args.offline)
            part, count = resample_zone(hourly, stamps, zone["id"])
            parts.append(part)
            clamped += count
    frame = pd.concat(parts, ignore_index=True).sort_values(["zone_id", "timestamp_utc"])
    table = pa.Table.from_pandas(frame, schema=SCHEMA, preserve_index=False)
    report = validate(table.to_pandas(), stamps, zones, clamped, old)
    path = root / "data/raw/weather/weather.parquet"
    temporary = path.with_suffix(".parquet.tmp")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(path)
    results = root / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "stage3_checks.txt").write_text(report + "\n", encoding="utf-8")
    (root / "data/raw/weather/provenance.json").write_text(json.dumps({
        "source_endpoint": API, "model_selection": "Open-Meteo default best_match",
        "zones": zones, "issue_time_kind": "requested valid-time-minus-24h convention; see interpolation caveat",
        "issue_time_rule": "timestamp_utc - 24 hours",
        "weather_caveat": WEATHER_CAVEAT, "interpolation_caveat": INTERPOLATION_CAVEAT,
        "window_reason": WINDOW_REASON,
        "start_utc": stamps.min().isoformat(), "last_interval_start_utc": stamps.max().isoformat(),
        "half_hour_method": "linear interpolation at source time labels; no edge extrapolation",
        "solar_source_semantics": "preceding-hour average, used as approximate interpolated feature",
    }, indent=2) + "\n", encoding="utf-8")
    print(report)
    print(f"Wrote: {path}")


if __name__ == "__main__":
    main()
