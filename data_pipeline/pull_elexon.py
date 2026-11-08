"""Stage 2: Elexon FUELHH, preserving raw responses and source fuel codes.

Run from the project root: python data_pipeline/pull_elexon.py
Use --offline to rebuild from already-downloaded responses.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pull_neso import make_session, settlement_to_utc


API = "https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH"


def windows():
    """The API now caps requests at seven inclusive settlement dates."""
    for year in (2024, 2025):
        for month in range(1, 13):
            start = date(year, month, 1)
            last = date(year, month, calendar.monthrange(year, month)[1])
            while start <= last:
                end = min(start + timedelta(days=6), last)
                yield start, end
                start = end + timedelta(days=1)


def load_raw(root: Path, offline: bool) -> pd.DataFrame:
    raw = root / "data/raw/elexon"
    raw.mkdir(parents=True, exist_ok=True)
    frames = []
    manifests = {}
    batches = list(windows())
    with make_session() as session:
        for index, (start, end) in enumerate(batches, 1):
            name = f"{start}_{end}.json"
            path = raw / name
            params = {"settlementDateFrom": str(start),
                      "settlementDateTo": str(end), "format": "json"}
            if not path.exists() and not offline:
                print(f"[{index}/{len(batches)}] Downloading {start} through {end}", flush=True)
                response = session.get(API, params=params, timeout=(15, 120))
                response.raise_for_status()
                # Save response bytes before decoding JSON or converting values.
                temporary = path.with_suffix(".json.tmp")
                temporary.write_bytes(response.content)
                temporary.replace(path)
                metadata = {
                    "source_url": response.url,
                    "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                }
                path.with_suffix(".source.json").write_text(
                    json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
                time.sleep(0.5)
            if not path.exists():
                raise FileNotFoundError(f"Missing saved response: {path}; run without --offline first")
            payload = json.loads(path.read_bytes())
            records = payload.get("data")
            if not isinstance(records, list) or not records:
                raise ValueError(f"Empty or invalid Elexon response in {path}")
            frame = pd.DataFrame(records)
            dates = pd.to_datetime(frame["settlementDate"], format="%Y-%m-%d", errors="raise")
            if dates.isna().any() or not dates.between(pd.Timestamp(start), pd.Timestamp(end)).all():
                raise ValueError(f"Dates outside requested window in {path}")
            frames.append(frame)
            manifests.setdefault(str(start)[:7], []).append(name)
    # These monthly files are manifests, not fabricated API responses.
    for month, files in manifests.items():
        (raw / f"{month}.json").write_text(json.dumps({
            "kind": "monthly_manifest", "source": API,
            "reason": "FUELHH has a seven-day inclusive request limit",
            "raw_response_files": files,
        }, indent=2) + "\n", encoding="utf-8")
    return pd.concat(frames, ignore_index=True)


def pivot_generation(frame: pd.DataFrame):
    required = {"settlementDate", "settlementPeriod", "fuelType", "generation", "publishTime", "startTime"}
    if missing := required - set(frame):
        raise ValueError(f"Missing Elexon fields: {sorted(missing)}")
    if frame[list(required)].isna().any().any():
        raise ValueError("Null required fields in Elexon raw data")
    frame = frame.copy()
    converted = settlement_to_utc(frame.settlementDate, frame.settlementPeriod)
    frame["timestamp_utc"] = converted.timestamp_utc
    source_times = pd.to_datetime(frame.startTime, utc=True, errors="raise")
    if not source_times.eq(frame.timestamp_utc).all():
        bad = frame.loc[~source_times.eq(frame.timestamp_utc)].head()
        raise ValueError(f"Settlement conversion disagrees with Elexon startTime:\n{bad}")
    frame["generation"] = pd.to_numeric(frame.generation, errors="raise")
    if not np.isfinite(frame.generation).all():
        raise ValueError("Non-finite generation")
    frame["publish_utc"] = pd.to_datetime(frame.publishTime, utc=True, errors="raise")
    keys = ["timestamp_utc", "fuelType"]
    # Preserve the latest published revision, never sum repeated publications.
    same_publication = frame.groupby(keys + ["publish_utc"]).generation.nunique()
    if same_publication.gt(1).any():
        raise ValueError("Conflicting generation values for the same publication")
    frame = frame.sort_values("publish_utc")
    before = len(frame)
    frame = frame.drop_duplicates(keys, keep="last")
    revisions = before - len(frame)
    wide = frame.pivot(index="timestamp_utc", columns="fuelType", values="generation").sort_index()
    fuels = sorted(wide.columns)
    wide = wide[fuels]
    wind = [fuel for fuel in fuels if "WIND" in fuel.upper()]
    if not wind:
        raise ValueError(f"No wind fuel type found among {fuels}")
    wide["wind_total_mw"] = wide[wind].sum(axis=1, min_count=len(wind))
    solar = [fuel for fuel in fuels if "SOLAR" in fuel.upper()]
    if solar:
        wide["solar_mw"] = wide[solar].sum(axis=1, min_count=len(solar))
    wide.columns.name = None
    return wide.reset_index(), fuels, revisions


def validate(wide: pd.DataFrame, fuels: list[str], revisions: int, root: Path) -> str:
    demand = pd.read_parquet(root / "data/raw/neso/national_demand.parquet")
    if demand.timestamp_utc.duplicated().any() or wide.timestamp_utc.duplicated().any():
        raise ValueError("Duplicate timestamps prevent a one-to-one join")
    expected = pd.date_range("2024-01-01", "2026-01-01", freq="30min", tz="UTC", inclusive="left")
    if not pd.DatetimeIndex(wide.timestamp_utc).equals(expected):
        raise ValueError("Generation does not have a complete 2024-2025 UTC grid")
    joined = demand.merge(wide, on="timestamp_utc", how="inner", validate="one_to_one")
    rate = len(joined) / len(demand)
    if rate < .95:
        raise ValueError(f"Demand/generation join rate {rate:.2%} is below 95%")
    if wide.wind_total_mw.isna().any():
        raise ValueError("Missing wind generation")
    missing = wide[fuels].isna().sum()
    detail = []
    for fuel in fuels:
        valid = wide.loc[wide[fuel].notna(), "timestamp_utc"]
        inside = wide.timestamp_utc.between(valid.min(), valid.max())
        interior = int(wide.loc[inside, fuel].isna().sum())
        detail.append(f"{fuel}: {int(missing[fuel])} unpublished cells; "
                      f"first={valid.min()}, last={valid.max()}, interior_missing={interior}")
    return "\n".join([
        "Stage 2 generation checks: PASS",
        f"Demand rows: {len(demand):,}; generation rows: {len(wide):,}; joined rows: {len(joined):,}",
        f"Demand/generation timestamp join rate: {rate:.2%}",
        "Duplicate timestamps: 0; missing half-hours: 0",
        "All converted timestamps match Elexon's published startTime",
        f"Repeated publications resolved to latest: {revisions:,}",
        "Fuel types found: " + ", ".join(fuels),
        "wind_total_mw sums source wind categories; it excludes embedded wind.",
        ("solar_mw included from source solar categories." if "solar_mw" in wide else
         "No solar category in FUELHH; solar_mw omitted, not invented as zero."),
        "Fuel columns retain source codes and MW values, including signed flows if published.",
        "Missing fuel cells remain null, not silently filled with zero:",
        *detail,
        "Timestamp join coverage alone does not imply complete coverage for every fuel.",
        "Generation totals need not equal NESO ND: the definitions and coverage differ.",
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    frame, fuels, revisions = pivot_generation(load_raw(args.root, args.offline))
    report = validate(frame, fuels, revisions, args.root)
    schema = pa.schema([(name, pa.timestamp("us", tz="UTC") if name == "timestamp_utc"
                         else pa.float32()) for name in frame])
    table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
    path = args.root / "data/raw/elexon/generation_by_fuel.parquet"
    temporary = path.with_suffix(".parquet.tmp")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(path)
    results = args.root / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "stage2_checks.txt").write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"Wrote: {path.resolve()}")


if __name__ == "__main__":
    main()
