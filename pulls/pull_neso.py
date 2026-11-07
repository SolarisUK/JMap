"""Stage 1: download and validate NESO national demand for 2024 and 2025.

Run from the project root: python pulls/pull_neso.py
Dependencies: requests pandas pyarrow tzdata
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


API = "https://api.neso.energy/api/3/action/datastore_search_sql"
# Annual outturn resources listed by NESO's Historic Demand Data portal.
RESOURCES = {
    2024: "f6d02c0f-957b-48cb-82ee-09003f2ba759",
    2025: "b2bde559-3455-4021-b179-dfe60c0337b0",
}
OUTPUT_SCHEMA = pa.schema([
    ("timestamp_utc", pa.timestamp("us", tz="UTC")),
    ("national_demand_mw", pa.float32()),
    ("embedded_wind_mw", pa.float32()),
    ("embedded_solar_mw", pa.float32()),
    ("dst_flag", pa.bool_()),
])


def settlement_to_utc(dates: pd.Series, periods: pd.Series) -> pd.DataFrame:
    """Convert ISO settlement dates and period numbers to interval-start UTC.

    Localise midnight first, then add elapsed half-hours in UTC. This preserves
    both occurrences of October's repeated hour and skips March's missing hour.
    Other pull scripts should import this function rather than copy it.
    """
    dates = pd.to_datetime(dates, format="%Y-%m-%d", errors="raise")
    if dates.isna().any() or not dates.eq(dates.dt.normalize()).all():
        raise ValueError("Expected non-null settlement dates at midnight")
    periods = pd.to_numeric(periods, errors="raise")
    if periods.isna().any() or not periods.mod(1).eq(0).all():
        raise ValueError("Settlement periods must be non-null integers")
    start = dates.dt.tz_localize("Europe/London").dt.tz_convert("UTC")
    # Add a day before localising: a settlement day can last 23, 24 or 25 hours.
    end = (dates + pd.Timedelta(days=1)).dt.tz_localize("Europe/London")
    end = end.dt.tz_convert("UTC")
    expected = (end - start) / pd.Timedelta(minutes=30)
    if not (periods.ge(1) & periods.le(expected)).all():
        raise ValueError("Settlement period lies outside its local day")
    return pd.DataFrame({
        "timestamp_utc": start + pd.to_timedelta((periods - 1) * 30, unit="min"),
        "dst_flag": expected.ne(48),
    })


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1,
                  status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "JMap-data-stage1/1.0"
    return session


def load_year(session: requests.Session, year: int, root: Path,
              offline: bool) -> pd.DataFrame:
    raw_dir = root / "data/raw/neso"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{year}.json"
    query = (f'SELECT * FROM "{RESOURCES[year]}" '
             'ORDER BY "SETTLEMENT_DATE", "SETTLEMENT_PERIOD"')
    if not offline:
        print(f"Downloading NESO {year}...", flush=True)
        response = session.get(API, params={"sql": query}, timeout=(15, 120))
        response.raise_for_status()
        # Preserve the response bytes before JSON decoding or data conversion.
        temporary = raw_path.with_suffix(".json.tmp")
        temporary.write_bytes(response.content)
        temporary.replace(raw_path)
        metadata = {
            "source_url": response.url,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "resource_id": RESOURCES[year],
        }
        raw_path.with_suffix(".source.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    payload = json.loads(raw_path.read_bytes())
    if not payload.get("success"):
        raise ValueError(f"NESO {year} returned an error: {payload.get('error')}")
    frame = pd.DataFrame(payload["result"]["records"])
    required = {"SETTLEMENT_DATE", "SETTLEMENT_PERIOD", "ND",
                "EMBEDDED_WIND_GENERATION", "EMBEDDED_SOLAR_GENERATION"}
    if missing := required - set(frame.columns):
        raise ValueError(f"NESO {year} missing columns: {sorted(missing)}")
    if "FORECAST_ACTUAL_INDICATOR" in frame:
        actual = frame["FORECAST_ACTUAL_INDICATOR"].astype("string").str.strip().str.upper().eq("A")
        print(f"{year}: excluding {int((~actual.fillna(False)).sum())} non-actual rows")
        frame = frame.loc[actual.fillna(False)].copy()
    else:
        print(f"{year}: annual historic outturn; no forecast/actual column")
    frame = frame.reset_index(drop=True)
    stamps = settlement_to_utc(frame["SETTLEMENT_DATE"], frame["SETTLEMENT_PERIOD"])
    out = stamps.assign(
        national_demand_mw=pd.to_numeric(frame["ND"], errors="raise"),
        embedded_wind_mw=pd.to_numeric(frame["EMBEDDED_WIND_GENERATION"], errors="raise"),
        embedded_solar_mw=pd.to_numeric(frame["EMBEDDED_SOLAR_GENERATION"], errors="raise"),
    )
    return out[list(OUTPUT_SCHEMA.names)]


def validate(frame: pd.DataFrame) -> str:
    expected = pd.date_range("2024-01-01", "2026-01-01", freq="30min",
                             tz="UTC", inclusive="left")
    actual = pd.DatetimeIndex(frame.timestamp_utc)
    if not actual.equals(expected):
        raise ValueError(
            f"Incomplete or repeated time grid: {len(expected.difference(actual))} missing; "
            f"{actual.duplicated().sum()} duplicates; "
            f"{len(actual.difference(expected))} unexpected timestamps")
    for column in ["national_demand_mw", "embedded_wind_mw", "embedded_solar_mw"]:
        if not np.isfinite(frame[column]).all() or frame[column].lt(0).any():
            raise ValueError(f"Null, non-finite or negative values in {column}")
    if not frame.national_demand_mw.gt(0).all():
        raise ValueError("Zero national demand")
    local_dates = frame.timestamp_utc.dt.tz_convert("Europe/London").dt.date
    daily = frame.groupby(local_dates).size()
    distribution = {int(k): int(v) for k, v in daily.value_counts().sort_index().items()}
    if distribution != {46: 2, 48: 727, 50: 2}:
        raise ValueError(f"Unexpected local-day coverage: {distribution}")
    expected_flags = local_dates.map(daily).ne(48)
    if not frame.dst_flag.equals(expected_flags.rename("dst_flag")):
        raise ValueError("Incorrect DST flags")
    stats = frame.national_demand_mw.agg(["min", "mean", "max"])
    return "\n".join([
        "Stage 1 national-demand checks: PASS",
        f"Rows / distinct timestamps: {len(frame):,} / {actual.nunique():,}",
        f"UTC interval starts: {actual.min()} -> {actual.max()}",
        "Duplicates: 0; missing half-hours: 0; null data values: 0",
        f"Local-day counts (periods: days): {distribution}",
        "Clock-change days:\n" + daily[daily.ne(48)].to_string(),
        f"DST-flagged half-hours: {int(frame.dst_flag.sum())}",
        f"Demand MW: min={stats['min']:.0f}, mean={stats['mean']:.2f}, max={stats['max']:.0f}",
        "Do not reject valid low demand solely because it is below the runbook's rough 18 GW guide.",
        "This is the national-demand intermediate, not the final nine-column zone/weather table.",
        "The project's scripts/check_parquet.py has not been supplied or run.",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="Project root; default is the current directory")
    parser.add_argument("--offline", action="store_true",
                        help="Rebuild from saved raw JSON without downloading")
    args = parser.parse_args()
    with make_session() as session:
        frame = pd.concat([load_year(session, year, args.root, args.offline)
                           for year in RESOURCES], ignore_index=True)
    frame = frame.sort_values("timestamp_utc").reset_index(drop=True)
    report = validate(frame)
    table = pa.Table.from_pandas(frame, schema=OUTPUT_SCHEMA, preserve_index=False)
    path = args.root / "data/raw/neso/national_demand.parquet"
    temporary = path.with_suffix(".parquet.tmp")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(path)
    results = args.root / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "stage1_checks.txt").write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"Wrote: {path.resolve()}")


if __name__ == "__main__":
    main()
