"""Stage 5: build real.parquet in the exact schema defined by schemas.py.

Run from JMap: python pulls/build_canonical.py
Uses independent contract checks, then the team's original checker if present.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


# Explicit path also works when Python is started with -I.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_canonical_contract import (JUMP_FRACTION, ZERO_THRESHOLD_MW, arrow_schema,
                                      check_table, dst_boundary_mask, load_contract, utc_index)


def fill_and_flag_zone(frame, flags):
    """Only bounded missing runs of 1-3 half-hours are eligible for filling."""
    frame = frame.sort_values("timestamp_utc").copy()
    frame.index = utc_index(frame.timestamp_utc)
    demand = frame.demand_mw.astype("float64")
    missing = demand.isna()
    runs = missing.ne(missing.shift(fill_value=False)).cumsum()
    length = missing.groupby(runs).transform("size")
    candidate = demand.interpolate(method="time", limit_area="inside")
    filled = missing & length.lt(4) & candidate.notna()
    demand.loc[filled] = candidate.loc[filled]
    # Flag the actual canonical values, including their required float32 rounding.
    frame["demand_mw"] = demand.astype("float32")
    demand = frame.demand_mw
    bits = np.zeros(len(frame), dtype=np.uint8)
    bits[demand.isna().to_numpy()] |= flags["MISSING"]
    bits[filled.to_numpy()] |= flags["INTERPOLATED"]
    zero = demand.le(ZERO_THRESHOLD_MW) & demand.notna()
    zero_runs = zero.ne(zero.shift(fill_value=False)).cumsum()
    long_zero = zero & zero.groupby(zero_runs).transform("size").ge(3)
    bits[long_zero.to_numpy()] |= flags["ZERO_RUN"]
    previous = demand.shift()
    jump = previous.gt(0) & demand.notna() & demand.sub(previous).abs().gt(JUMP_FRACTION * previous)
    bits[jump.to_numpy()] |= flags["JUMP"]
    bits[dst_boundary_mask(frame.timestamp_utc)] |= flags["DST_BOUNDARY"]
    frame["quality_flag"] = bits
    return frame.reset_index(drop=True)


def build_table(root, config):
    national = pd.read_parquet(root / "data/raw/neso/national_demand.parquet")
    stamps = utc_index(national.timestamp_utc).sort_values()
    expected = pd.date_range(stamps.min(), stamps.max(), freq="30min", tz="UTC").as_unit("ns")
    if not stamps.equals(expected):
        raise ValueError("National demand grid is not complete and unique")
    keys = ["zone_id", "timestamp_utc"]
    zone = pd.read_parquet(root / "data/raw/zone_demand.parquet")
    weather = pd.read_parquet(root / "data/raw/weather/weather.parquet")
    grid = pd.MultiIndex.from_product([config["zone_order"], stamps], names=keys)
    for name, source in [("zone demand", zone), ("weather", weather)]:
        source["timestamp_utc"] = utc_index(source.timestamp_utc)
        if source.duplicated(keys).any():
            raise ValueError(f"Duplicate keys in {name}")
        if len(source.set_index(keys).index.difference(grid)):
            raise ValueError(f"Unexpected zones or off-grid timestamps in {name}")
    if not zone.is_estimated.dropna().all():
        raise ValueError("Stage 4 source contains targets not labelled estimated")
    zone = zone.set_index(keys).reindex(grid).reset_index()
    # Newly inserted missing targets are estimates too; retain their feature rows.
    zone["is_estimated"] = True
    frame = zone.merge(weather, on=keys, how="left", validate="one_to_one")
    if frame[["temp_c", "wind_ms", "solar_wm2"]].isna().any().any():
        raise ValueError("Incomplete weather join; no weather is fabricated")
    parts = [fill_and_flag_zone(subset, config["quality_flags"])
             for _, subset in frame.groupby("zone_id", sort=False)]
    frame = pd.concat(parts, ignore_index=True).sort_values(keys).reset_index(drop=True)
    schema = arrow_schema(config)  # Built from the project's CANONICAL_SCHEMA dict.
    frame = frame[list(config["canonical_schema"])]
    return pa.Table.from_pandas(frame, schema=schema, preserve_index=False).replace_schema_metadata(None)


def choose_reference(root, explicit):
    if explicit is not None:
        return explicit
    for path in [root / "data/canonical/_fake.parquet", root / "_fake.parquet", root / "_fake(1).parquet"]:
        if path.is_file():
            return path
    return None


def decode_checker_output(output: bytes | None) -> str:
    """Decode after capture; tolerate logs from older Windows launchers."""
    if output is None:
        return ""
    try:
        return output.decode("utf-8")
    except UnicodeDecodeError:
        return output.decode("cp1252", errors="backslashreplace")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract-file", type=Path,
                        help="Optional contract JSON export; by default read schemas.py")
    parser.add_argument("--reference", type=Path, help="Optional fake Parquet; otherwise auto-detect")
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_contract(root, args.contract_file)
    reference = choose_reference(root, args.reference)
    table = build_table(root, config)
    report, stats = check_table(table, config, root, reference)
    destination = root / "data/canonical/real.parquet"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".parquet.tmp")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(destination)
    # Run the supplied team checker through its portable launcher.
    original = root / "scripts/check_parquet.py"
    original_code = None
    if original.is_file():
        launcher = root / "scripts/run_team_checker.py"
        if not launcher.is_file():
            raise FileNotFoundError(f"The team checker requires its portable launcher: {launcher}")
        checked = subprocess.run([sys.executable, "-I", str(launcher), str(destination), "--root", str(root)],
                                 cwd=root, capture_output=True)
        original_code = checked.returncode
        original_status = f"Original runbook checker exit code: {original_code}"
        original_output = decode_checker_output(checked.stdout) + decode_checker_output(checked.stderr)
    else:
        original_status = "Original runbook checker: NOT RUN (scripts/check_parquet.py is absent)."
        original_output = "The independent validator passed. The original runbook gate remains unverified."
    full_report = report + "\n" + original_status + "\n" + original_output.strip() + "\n"
    results = root / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "stage5_checks.txt").write_text(full_report, encoding="utf-8")
    inputs = [root / "data/raw/neso/national_demand.parquet", root / "data/raw/zone_demand.parquet",
              root / "data/raw/weather/weather.parquet"]
    metadata = {
        "contract": config, "checks": stats, "original_checker_return_code": original_code,
        "original_checker_status": original_status,
        "schema_matches_fake": reference is not None,
        "input_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        "output_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "gap_policy": "Only bounded runs of 1-3 missing half-hours are interpolated; 4+ remain null",
        "zero_run_policy": "Demand <= 1 MW for 3+ consecutive half-hours",
        "jump_policy": "Absolute change > 40% from a strictly positive preceding demand value",
        "weather_issue_time_kind": "contract proxy, not actual model initialization/publication time",
        "regional_demand_kind": "temperature-adjusted allocation of national outturn; not measured regional load",
    }
    (results / "canonical_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(full_report, end="")
    print(f"Wrote: {destination}")
    if original_code not in (None, 0):
        raise SystemExit(original_code)


if __name__ == "__main__":
    main()
