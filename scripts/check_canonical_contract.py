"""Independent contract checks; this is not the team's original check_parquet.py.

Run: python -I scripts/check_canonical_contract.py data/canonical/real.parquet
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


ZERO_THRESHOLD_MW = 1.0
JUMP_FRACTION = 0.40


def load_contract(root: Path, snapshot: Path | None = None):
    if snapshot is not None:
        config = json.loads(snapshot.read_text(encoding="utf-8"))
    else:
        spec = importlib.util.spec_from_file_location("_canonical_contract", root / "schemas.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        config = {
            "zone_order": list(module.ZONE_ORDER), "demand_share": dict(module.DEMAND_SHARE),
            "canonical_schema": dict(module.CANONICAL_SCHEMA),
            "quality_flags": {name: getattr(module.QF, name) for name in
                              ["OK", "MISSING", "INTERPOLATED", "ZERO_RUN", "JUMP", "DST_BOUNDARY"]},
        }
    flags = config["quality_flags"]
    values = [flags[n] for n in ["MISSING", "INTERPOLATED", "ZERO_RUN", "JUMP", "DST_BOUNDARY"]]
    if flags["OK"] != 0 or len(set(values)) != len(values) or any(v < 1 or v > 128 or v & (v-1) for v in values):
        raise ValueError("QF values must be distinct uint8 bits, with OK=0")
    order, shares = config["zone_order"], config["demand_share"]
    if len(set(order)) != len(order) or set(order) != set(shares):
        raise ValueError("Inconsistent contract zones and shares")
    if not np.isclose(sum(shares.values()), 1.0, rtol=0, atol=1e-12):
        raise ValueError("Contract demand shares do not sum to one")
    return config


def arrow_schema(config):
    fields = []
    for name, kind in config["canonical_schema"].items():
        match = re.fullmatch(r"timestamp\[(s|ms|us|ns),\s*tz=([^\]]+)\]", kind)
        dtype = pa.timestamp(match[1], tz=match[2]) if match else pa.type_for_alias(kind)
        fields.append(pa.field(name, dtype))
    return pa.schema(fields)


def utc_index(values):
    index = pd.DatetimeIndex(values)
    if index.tz is None or str(index.tz) != "UTC" or index.hasnans:
        raise ValueError("Expected non-null UTC timestamps")
    return index.as_unit("ns")


def dst_boundary_mask(stamps):
    local_dates = utc_index(stamps).tz_convert("Europe/London").tz_localize(None).normalize()
    start = local_dates.tz_localize("Europe/London").tz_convert("UTC")
    end = (local_dates + pd.Timedelta(days=1)).tz_localize("Europe/London").tz_convert("UTC")
    return np.asarray((end - start) != pd.Timedelta(days=1))


def check_table(table, config, root: Path, reference_schema: Path | None = None):
    expected_schema = arrow_schema(config)
    if not table.schema.remove_metadata().equals(expected_schema):
        raise ValueError(f"Canonical Arrow schema mismatch:\nExpected {expected_schema}\nGot {table.schema}")
    reference_result = "No fake reference supplied; schema checked against CANONICAL_SCHEMA."
    if reference_schema is not None:
        fake = pq.read_schema(reference_schema).remove_metadata()
        if not expected_schema.equals(fake):
            raise ValueError("Contract schema differs from the selected fake Parquet schema")
        reference_result = "Column names, order and Arrow types exactly match the selected fake Parquet."
    frame = table.to_pandas()
    keys = ["zone_id", "timestamp_utc"]
    required = keys + ["quality_flag", "is_estimated"]
    if frame[required].isna().any().any() or frame.duplicated(keys).any():
        raise ValueError("Null keys/flags or duplicate zone/time keys")
    sorted_keys = frame[keys].sort_values(keys).reset_index(drop=True)
    if not frame[keys].reset_index(drop=True).equals(sorted_keys):
        raise ValueError("Canonical rows are not sorted by zone_id, timestamp_utc")
    if set(frame.zone_id) != set(config["zone_order"]):
        raise ValueError("Unexpected zone IDs")
    stamps = utc_index(frame.timestamp_utc)
    if (stamps.asi8 % pd.Timedelta(minutes=30).value != 0).any():
        raise ValueError("Timestamps are not half-hour aligned interval starts")
    demand = pd.read_parquet(root / "data/raw/neso/national_demand.parquet")
    demand["timestamp_utc"] = utc_index(demand.timestamp_utc)
    demand = demand.sort_values("timestamp_utc").reset_index(drop=True)
    target = utc_index(demand.timestamp_utc)
    expected = pd.date_range(target.min(), target.max(), freq="30min", tz="UTC").as_unit("ns")
    if not target.equals(expected):
        raise ValueError("Reference national demand has an incomplete or repeated time grid")
    if len(frame) != len(target) * len(config["zone_order"]):
        raise ValueError("Wrong row count for national time grid and contract zones")
    for zone in config["zone_order"]:
        if not utc_index(frame.loc[frame.zone_id.eq(zone), "timestamp_utc"]).equals(target):
            raise ValueError(f"Per-zone gaps or unexpected timestamps for {zone}")
    for name in ["temp_c", "wind_ms", "solar_wm2"]:
        if not np.isfinite(frame[name]).all():
            raise ValueError(f"Missing or non-finite weather: {name}")
    if frame.wind_ms.lt(0).any() or frame.solar_wm2.lt(0).any():
        raise ValueError("Negative wind speed or solar radiation")
    values = frame.demand_mw.to_numpy()
    if np.isinf(values).any() or frame.demand_mw.lt(0).any():
        raise ValueError("Infinite or negative demand")
    flags = config["quality_flags"]
    bits = frame.quality_flag.to_numpy(dtype=np.uint8)
    allowed = sum(v for k, v in flags.items() if k != "OK")
    if (bits & (255 ^ allowed)).any():
        raise ValueError("Unknown quality-flag bits")
    missing = (bits & flags["MISSING"]) != 0
    interpolated = (bits & flags["INTERPOLATED"]) != 0
    if not np.array_equal(missing, frame.demand_mw.isna().to_numpy()):
        raise ValueError("MISSING flags disagree with null demand")
    if np.any(missing & interpolated):
        raise ValueError("A filled value cannot also be marked MISSING")
    if not np.array_equal((bits & flags["DST_BOUNDARY"]) != 0, dst_boundary_mask(stamps)):
        raise ValueError("DST_BOUNDARY flags disagree with local settlement-day lengths")
    for _, subset in frame.groupby("zone_id", sort=False):
        x = subset.demand_mw
        zero = x.le(ZERO_THRESHOLD_MW) & x.notna()
        runs = zero.ne(zero.shift(fill_value=False)).cumsum()
        expected_zero = zero & zero.groupby(runs).transform("size").ge(3)
        previous = x.shift()
        expected_jump = previous.gt(0) & x.notna() & x.sub(previous).abs().gt(JUMP_FRACTION * previous)
        zbits = subset.quality_flag.to_numpy(dtype=np.uint8)
        if not np.array_equal((zbits & flags["ZERO_RUN"]) != 0, expected_zero.to_numpy()):
            raise ValueError("ZERO_RUN flags disagree with near-zero runs")
        if not np.array_equal((zbits & flags["JUMP"]) != 0, expected_jump.to_numpy()):
            raise ValueError("JUMP flags disagree with changes over 40 percent")
    observed_issue = frame.weather_issue_time_utc.notna()
    if not (frame.loc[observed_issue, "weather_issue_time_utc"] <
            frame.loc[observed_issue, "timestamp_utc"]).all():
        raise ValueError("Weather issue time must precede valid time")
    if not frame.is_estimated.all():
        raise ValueError("This split-from-national dataset must mark every row estimated")
    # Cross-check canonical values against the separate source files.
    source = pd.read_parquet(root / "data/raw/zone_demand.parquet")
    original = frame.merge(source[keys + ["demand_mw"]], on=keys, how="left",
                           suffixes=("", "_original"), validate="one_to_one")
    finite_original = original.demand_mw_original.notna()
    if not np.array_equal(original.loc[finite_original, "demand_mw"].to_numpy(),
                          original.loc[finite_original, "demand_mw_original"].to_numpy(dtype=np.float32)):
        raise ValueError("Canonical demand differs from original values after float32 casting")
    if ((original.quality_flag & flags["INTERPOLATED"]).ne(0) & finite_original).any():
        raise ValueError("INTERPOLATED set on an originally present demand target")
    for _, subset in original.groupby("zone_id", sort=False):
        absent = subset.demand_mw_original.isna()
        runs = absent.ne(absent.shift(fill_value=False)).cumsum()
        length = absent.groupby(runs).transform("size")
        bounded = subset.demand_mw_original.ffill().notna() & subset.demand_mw_original.bfill().notna()
        expected_fill = absent & length.lt(4) & bounded
        actual_fill = (subset.quality_flag & flags["INTERPOLATED"]).ne(0)
        if not np.array_equal(expected_fill.to_numpy(), actual_fill.to_numpy()):
            raise ValueError("INTERPOLATED flags disagree with bounded gaps shorter than two hours")
    weather = pd.read_parquet(root / "data/raw/weather/weather.parquet")
    joined = frame.merge(weather, on=keys, suffixes=("", "_source"), validate="one_to_one", how="left")
    for name in ["temp_c", "wind_ms", "solar_wm2"]:
        if not np.array_equal(joined[name].to_numpy(), joined[name + "_source"].to_numpy(dtype=np.float32)):
            raise ValueError(f"Canonical {name} differs from weather source")
    left_issue = pd.DatetimeIndex(joined.weather_issue_time_utc).as_unit("us")
    right_issue = pd.DatetimeIndex(joined.weather_issue_time_utc_source).as_unit("us")
    if not left_issue.equals(right_issue):
        raise ValueError("Weather issue time differs from source")
    usable = ~missing & ~interpolated
    groups = frame.assign(usable=usable, demand_mw=frame.demand_mw.astype("float64")).groupby("timestamp_utc")
    complete = groups.usable.all().reindex(target).to_numpy()
    national = demand.national_demand_mw.to_numpy(dtype=np.float64)
    totals = groups.demand_mw.sum(min_count=len(config["zone_order"])).reindex(target).to_numpy(dtype=float)
    tolerance = max(0.01, float(np.nanmax(np.abs(national))) * np.finfo(np.float32).eps)
    error = float(np.max(np.abs(totals[complete] - national[complete]))) if complete.any() else None
    if complete.any() and not np.allclose(totals[complete], national[complete], rtol=0, atol=tolerance):
        raise ValueError(f"Float32 zone totals differ from national demand: {error} MW")
    comparisons = []
    if complete.any():
        subset = frame.loc[frame.timestamp_utc.isin(target[complete])]
        shares = (subset.assign(demand_mw=subset.demand_mw.astype("float64"))
                  .groupby("zone_id").demand_mw.sum() / national[complete].sum())
        for zone in config["zone_order"]:
            actual, baseline = float(shares[zone]), config["demand_share"][zone]
            if abs(actual - baseline) > .01:
                raise ValueError(f"Aggregate demand share differs by over one percentage point: {zone}")
            comparisons.append({"zone_id": zone, "contract_share": baseline, "actual_share": actual})
    counts = {name: int(((bits & value) != 0).sum()) for name, value in flags.items() if value}
    stats = {"rows": len(frame), "zones": len(config["zone_order"]),
             "rows_per_zone": len(target), "flag_counts": counts,
             "conservation_max_error_mw": error, "conservation_tolerance_mw": tolerance,
             "complete_original_timestamps": int(complete.sum()), "shares": comparisons}
    report = "\n".join([
        "Independent canonical contract checks: PASS",
        reference_result,
        f"Zones: {stats['zones']}; rows per zone: {len(target):,}; total rows: {len(frame):,}",
        f"UTC interval starts: {target.min()} -> {target.max()}",
        "Sorted keys, complete per-zone half-hour grid, duplicates: 0",
        "Weather values and issue-time values match the Stage 3 source",
        "Present demand values match Stage 4 after the required float32 cast",
        "Interpolation flags agree with bounded missing runs of 1-3 half-hours",
        f"Flag counts (bitwise): {counts}",
        f"Rows excluded from scoring (MISSING or INTERPOLATED): {int((~usable).sum()):,}",
        f"National-demand checks on {int(complete.sum()):,} complete original timestamps:",
        f"Maximum float32 sum difference: {error} MW; tolerance: {tolerance:g} MW",
        "Aggregate zone shares remain within one percentage point of the contract.",
        "Every row is labelled is_estimated=True.",
        "Regional targets are allocated estimates; weather issue times retain the documented proxy limitation.",
        "This validator is separate from the team's original scripts/check_parquet.py.",
    ])
    return report, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parquet", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract-file", type=Path)
    parser.add_argument("--reference", type=Path, help="Optional fake Parquet for exact schema comparison")
    args = parser.parse_args()
    report, _ = check_table(pq.read_table(args.parquet), load_contract(args.root, args.contract_file),
                            args.root, args.reference)
    print(report)


if __name__ == "__main__":
    main()
