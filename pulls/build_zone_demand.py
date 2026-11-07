"""Stage 4: estimate zone demand from national outturn and zone temperature.

Run from JMap: python pulls/build_zone_demand.py
No network requests. Regional demand is estimated, not measured.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


HEATING_BASE_C = 15.5
HEATING_SENSITIVITY = 0.015
CONSERVATION_ATOL_MW = 1e-8
SHARE_ATOL = 0.01  # One percentage point of national demand.
OUTPUT_SCHEMA = pa.schema([
    ("zone_id", pa.string()),
    ("timestamp_utc", pa.timestamp("us", tz="UTC")),
    # Keep precision here; Stage 5 casts the canonical demand column to float32.
    ("demand_mw", pa.float64()),
    ("is_estimated", pa.bool_()),
])


def load_contract(root: Path, snapshot: Path | None):
    if snapshot is not None:
        config = json.loads(snapshot.read_text(encoding="utf-8"))
        order, demand_share = config["zone_order"], config["demand_share"]
    else:
        spec = importlib.util.spec_from_file_location("_zone_demand_contract", root / "schemas.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        order, demand_share = list(module.ZONE_ORDER), dict(module.DEMAND_SHARE)
    if not order or len(set(order)) != len(order) or set(order) != set(demand_share):
        raise ValueError("Invalid contract zone IDs or demand-share keys")
    shares = np.array([demand_share[z] for z in order], dtype=np.float64)
    if not np.isfinite(shares).all() or (shares <= 0).any():
        raise ValueError("Contract shares must be finite and positive")
    if not np.isclose(shares.sum(), 1.0, rtol=0, atol=1e-12):
        raise ValueError(f"Contract shares sum to {shares.sum()}, expected 1")
    return order, shares


def utc_index(values) -> pd.DatetimeIndex:
    stamps = pd.DatetimeIndex(values)
    if stamps.tz is None or str(stamps.tz) != "UTC" or stamps.hasnans:
        raise ValueError("Expected non-null UTC timestamps")
    # Keep internal operations consistent across pandas timestamp precisions.
    return stamps.as_unit("ns")


def load_inputs(root: Path, order: list):
    demand = pd.read_parquet(root / "data/raw/neso/national_demand.parquet")
    demand["timestamp_utc"] = utc_index(demand.timestamp_utc)
    demand = demand.sort_values("timestamp_utc").reset_index(drop=True)
    stamps = utc_index(demand.timestamp_utc)
    expected = pd.date_range(stamps.min(), stamps.max(), freq="30min", tz="UTC").as_unit("ns")
    if not stamps.equals(expected):
        raise ValueError("National demand must have a unique, complete half-hour UTC grid")
    national = demand.national_demand_mw.to_numpy(dtype=np.float64)
    if not np.isfinite(national).all() or (national <= 0).any():
        raise ValueError("National demand must be finite and positive")
    weather = pd.read_parquet(root / "data/raw/weather/weather.parquet")
    weather["timestamp_utc"] = utc_index(weather.timestamp_utc)
    if weather.duplicated(["zone_id", "timestamp_utc"]).any():
        raise ValueError("Duplicate zone/weather timestamp keys")
    if set(weather.zone_id) != set(order) or len(weather) != len(stamps) * len(order):
        raise ValueError("Weather coverage does not match the contract zones and demand grid")
    temperatures = weather.pivot(index="timestamp_utc", columns="zone_id", values="temp_c")
    temperatures = temperatures.reindex(index=stamps, columns=order).to_numpy(dtype=np.float64)
    if not np.isfinite(temperatures).all():
        raise ValueError("Missing or non-finite zone temperature at a demand timestamp")
    return stamps, national, temperatures


def allocate(national: np.ndarray, temperatures: np.ndarray, shares: np.ndarray):
    """Apply heating weights, then conserve the national total at each timestamp."""
    if temperatures.shape != (len(national), len(shares)):
        raise ValueError("Temperature matrix shape does not match demand and zones")
    heating_degrees = np.maximum(HEATING_BASE_C - temperatures, 0)
    weights = shares[None, :] * (1 + HEATING_SENSITIVITY * heating_degrees)
    allocation = national[:, None] * (weights / weights.sum(axis=1, keepdims=True))
    # Put floating-point rounding residue in the largest-share zone.
    allocation[:, int(np.argmax(shares))] += national - allocation.sum(axis=1)
    return allocation


def build_frame(stamps, allocation, order):
    frame = pd.DataFrame({
        "zone_id": np.tile(order, len(stamps)),
        "timestamp_utc": stamps.repeat(len(order)),
        "demand_mw": allocation.ravel(),
        "is_estimated": np.ones(allocation.size, dtype=bool),
    })
    return frame.sort_values(["zone_id", "timestamp_utc"]).reset_index(drop=True)


def validate(frame, stamps, national, order, shares):
    if frame.isna().any().any() or frame.duplicated(["zone_id", "timestamp_utc"]).any():
        raise ValueError("Null values or duplicate zone/time keys")
    if len(frame) != len(stamps) * len(order) or set(frame.zone_id) != set(order):
        raise ValueError("Unexpected zone demand coverage")
    if not frame.is_estimated.all():
        raise ValueError("Every allocated demand row must be marked estimated")
    if not np.isfinite(frame.demand_mw).all() or frame.demand_mw.le(0).any():
        raise ValueError("Invalid estimated demand")
    for zone in order:
        subset = frame.loc[frame.zone_id.eq(zone), "timestamp_utc"]
        if not utc_index(subset).equals(stamps):
            raise ValueError(f"Incomplete timestamp coverage for {zone}")
    totals = frame.groupby("timestamp_utc").demand_mw.sum().reindex(stamps).to_numpy()
    error = float(np.abs(totals - national).max())
    if not np.allclose(totals, national, rtol=0, atol=CONSERVATION_ATOL_MW):
        raise ValueError(f"Zone totals do not conserve national demand: max error {error} MW")
    actual = (frame.groupby("zone_id").demand_mw.sum()
              .reindex(order).to_numpy() / national.sum())
    if not np.allclose(actual, shares, rtol=0, atol=SHARE_ATOL):
        raise ValueError("Temperature-adjusted total shares differ by over one percentage point")
    comparison = [{"zone_id": z, "contract_share": float(b), "estimated_share": float(a),
                   "difference_percentage_points": float(100 * (a - b))}
                  for z, b, a in zip(order, shares, actual)]
    lines = [
        "Stage 4 estimated zone-demand checks: PASS",
        f"Zones: {len(order)}; rows per zone: {len(stamps):,}; total rows: {len(frame):,}",
        f"UTC interval starts: {stamps.min()} -> {stamps.max()}",
        "Duplicates: 0; missing half-hours: 0; null values: 0",
        "is_estimated: True on every row",
        f"National demand conservation: PASS (maximum difference {error:.3g} MW; tolerance {CONSERVATION_ATOL_MW:g} MW)",
        f"Heating factor: 1 + {HEATING_SENSITIVITY:g} * max({HEATING_BASE_C:g} - temp_c, 0)",
        "Multiply each contract share by its heating factor, then renormalise each half-hour.",
        "zone | contract share % | estimated share % | difference percentage points",
    ]
    lines += [f"{r['zone_id']} | {100*r['contract_share']:.3f} | {100*r['estimated_share']:.3f} | "
              f"{r['difference_percentage_points']:+.3f}" for r in comparison]
    lines += [
        "All total-demand shares are within one percentage point of the contract.",
        "Shares use total energy over the data window (each UTC interval is 0.5 h).",
        "These are ESTIMATED REGIONAL DEMAND targets, not measured regional load.",
        "The heating sensitivity and base shares are assumptions, not a model fitted to regional meters.",
        "Regional targets depend on the temperature feature used in this allocation.",
        "Regional prediction accuracy will measure this constructed allocation, not independent regional ground truth.",
        "Stage 3's approximate forecast-issue timing remains a limitation.",
        "This intermediate retains float64 MW for conservation; Stage 5 writes canonical float32 MW.",
        "The nine-column canonical file and its validation follow in Stage 5.",
    ]
    return "\n".join(lines), error, comparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract-file", type=Path,
                        help="Optional exported zone_order/demand_share JSON; default reads schemas.py")
    args = parser.parse_args()
    root = args.root.resolve()
    order, shares = load_contract(root, args.contract_file)
    stamps, national, temperatures = load_inputs(root, order)
    frame = build_frame(stamps, allocate(national, temperatures, shares), order)
    table = pa.Table.from_pandas(frame, schema=OUTPUT_SCHEMA, preserve_index=False)
    # Validate the typed data that will actually be written.
    report, max_error, comparison = validate(table.to_pandas(), stamps, national, order, shares)
    path = root / "data/raw/zone_demand.parquet"
    temporary = path.with_suffix(".parquet.tmp")
    pq.write_table(table, temporary, compression="zstd")
    temporary.replace(path)
    results = root / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "stage4_checks.txt").write_text(report + "\n", encoding="utf-8")
    inputs = [root / "data/raw/neso/national_demand.parquet",
              root / "data/raw/weather/weather.parquet"]
    provenance = {
        "label": "estimated regional demand",
        "zone_order": order, "demand_share": dict(zip(order, shares.tolist())),
        "heating_base_c": HEATING_BASE_C, "heating_sensitivity_per_degree": HEATING_SENSITIVITY,
        "method": "share * (1 + sensitivity * max(base_c - temp_c, 0)), normalised per half-hour",
        "maximum_conservation_error_mw": max_error, "share_comparison": comparison,
        "input_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        "regional_targets_are_independent_measurements": False,
        "intermediate_demand_type": "float64", "canonical_demand_type_at_stage5": "float32",
    }
    (results / "stage4_allocation.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(report)
    print(f"Wrote: {path}")


if __name__ == "__main__":
    main()
