"""Stage 6: write a compact quality report and a daily coverage heatmap.

Run from JMap: python data_pipeline/quality_report.py
Chart dependency: python -m pip install matplotlib
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_canonical_contract import load_contract, utc_index
from data_window import (INTERPOLATION_CAVEAT, NATIONAL_DEMAND_MAX_MW,
                         NATIONAL_DEMAND_MIN_MW, WEATHER_CAVEAT, WINDOW_REASON,
                         require_window_grid)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def missing_runs(stamps, values, zone):
    """List target gaps longer than two hours, with exclusive end times."""
    missing = pd.isna(values)
    edges = np.diff(np.r_[False, missing, False].astype(np.int8))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return [{"zone_id": zone, "start_utc": stamps[a].isoformat(),
             "end_utc_exclusive": (stamps[b - 1] + pd.Timedelta(minutes=30)).isoformat(),
             "missing_half_hours": int(b-a), "duration_hours": float((b-a)/2)}
            for a, b in zip(starts, ends) if b-a > 4]


def summarize(frame, demand, config):
    flags = config["quality_flags"]
    order = config["zone_order"]
    stamps = require_window_grid(utc_index(demand.timestamp_utc).sort_values(), "National demand reference")
    frame = frame.copy()
    frame["timestamp_utc"] = utc_index(frame.timestamp_utc)
    if frame.duplicated(["zone_id", "timestamp_utc"]).any() or set(frame.zone_id) != set(order):
        raise ValueError("Duplicate keys or unexpected canonical zones")
    days = pd.date_range(stamps.min().floor("D"), stamps.max().floor("D"), freq="D", tz="UTC").as_unit("ns")
    coverage = np.zeros((len(order), len(days)), dtype=np.int64)
    per_zone, gaps = [], []
    total_demand = frame.demand_mw.astype("float64").sum()
    for i, zone in enumerate(order):
        source = frame.loc[frame.zone_id.eq(zone)].sort_values("timestamp_utc")
        require_window_grid(source.timestamp_utc, zone)
        indexed = source.set_index("timestamp_utc").reindex(stamps)
        valid = indexed.demand_mw.notna()
        bits = indexed.quality_flag.fillna(flags["MISSING"]).to_numpy(dtype=np.uint8)
        scorable = valid.to_numpy() & ((bits & (flags["MISSING"] | flags["INTERPOLATED"])) == 0)
        original = valid.to_numpy() & ((bits & flags["INTERPOLATED"]) == 0)
        daily = valid.astype(int).groupby(stamps.floor("D")).sum().reindex(days, fill_value=0)
        coverage[i] = daily.to_numpy()
        actual = float(source.demand_mw.astype("float64").sum() / total_demand)
        baseline = config["demand_share"][zone]
        per_zone.append({"zone_id": zone, "rows": len(source), "expected_rows": len(stamps),
                         "valid_targets": int(valid.sum()), "coverage_pct": float(100*valid.mean()),
                         "original_targets": int(original.sum()), "scorable_targets": int(scorable.sum()),
                         "estimated_share": actual, "contract_share": baseline,
                         "share_difference_pp": 100*(actual-baseline)})
        gaps.extend(missing_runs(stamps, indexed.demand_mw.to_numpy(), zone))
    bits = frame.quality_flag.to_numpy(dtype=np.uint8)
    counts = {name: int(np.count_nonzero(bits & value)) if value else int(np.count_nonzero(bits == 0))
              for name, value in flags.items()}
    national = demand.national_demand_mw.astype("float64")
    stats = {
        "rows": len(frame), "zones": len(order), "utc_days": len(days),
        "start_utc": stamps.min().isoformat(), "last_interval_start_utc": stamps.max().isoformat(),
        "expected_rows": len(stamps)*len(order), "per_zone": per_zone,
        "target_coverage_pct": 100*sum(z["valid_targets"] for z in per_zone)/(len(stamps)*len(order)),
        "scorable_targets": sum(z["scorable_targets"] for z in per_zone),
        "flag_counts": counts, "gaps_over_two_hours": gaps,
        "null_counts": {name: int(value) for name, value in frame.isna().sum().items()},
        "estimated_rows": int(frame.is_estimated.sum()),
        "national_demand_mw": {"min": float(national.min()), "mean": float(national.mean()),
                               "max": float(national.max()),
                               "expected_min_mw": NATIONAL_DEMAND_MIN_MW,
                               "expected_max_mw": NATIONAL_DEMAND_MAX_MW,
                               "below_12000": int(national.lt(NATIONAL_DEMAND_MIN_MW).sum()),
                               "above_50000": int(national.gt(NATIONAL_DEMAND_MAX_MW).sum())},
    }
    return stats, coverage, days


def render_report(stats, metadata):
    n = stats["national_demand_mw"]
    lines = [
        "# Data quality: GB regional demand, 2024-2025", "",
        "Regional demand is estimated from national demand and temperature, rather than measured at regional meters.", "",
        WEATHER_CAVEAT, "",
        "The regional target uses temperature in its formula, so regional model scores do not test independent regional measurements.", "",
        WINDOW_REASON, "",
        f"**Scope:** {stats['rows']:,} rows; {stats['zones']} zones; {stats['utc_days']} UTC days; "
        f"{stats['start_utc']} to {stats['last_interval_start_utc']} (half-hour starts). "
        f"All {stats['estimated_rows']:,} rows are marked estimated.", "",
        "| Zone | Rows | Target coverage | Estimated share | Contract share | Difference (pp) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in stats["per_zone"]:
        lines.append(f"| {r['zone_id']} | {r['rows']:,} | {r['coverage_pct']:.2f}% | "
                     f"{100*r['estimated_share']:.3f}% | {100*r['contract_share']:.3f}% | {r['share_difference_pp']:+.3f} |")
    lines += ["", "Coverage = non-null targets / expected UTC half-hours, including any flagged fills. "
              f"{stats['scorable_targets']:,} rows are eligible under the contract's MISSING/INTERPOLATED scoring rule. "
              "Shares use total demand, equivalent to MWh shares for equal half-hours.", "",
              "| Quality flag | Rows |", "|---|---:|"]
    for name in ["OK", "MISSING", "INTERPOLATED", "ZERO_RUN", "JUMP", "DST_BOUNDARY"]:
        lines.append(f"| {name} | {stats['flag_counts'][name]:,} |")
    lines += ["", "OK means a zero flag; other flag counts are bitwise and can overlap. "
              "DST flags cover full 46/50-period local days. All UTC days have 48 periods.", "",
              "**Target gaps longer than two hours:**"]
    gaps = stats["gaps_over_two_hours"]
    if gaps:
        lines += ["", "| Zone | Start UTC | End UTC (exclusive) | Missing half-hours | Hours |",
                  "|---|---|---|---:|---:|"]
        for g in gaps:
            lines.append(f"| {g['zone_id']} | {g['start_utc']} | {g['end_utc_exclusive']} | "
                         f"{g['missing_half_hours']} | {g['duration_hours']:g} |")
    else:
        lines[-1] += " None."
    lines += ["", f"**National demand:** min **{n['min']:,.0f} MW**, mean **{n['mean']:,.2f} MW**, "
              f"max **{n['max']:,.0f} MW**, versus the expected {NATIONAL_DEMAND_MIN_MW:,}-{NATIONAL_DEMAND_MAX_MW:,} MW sanity range. "
              f"{n['below_12000']:,} half-hours fall below that range and {n['above_50000']:,} above; "
              "the original outturn values are retained.", "",
              "**Validation:** independent and supplied team checkers passed; this report verifies the recorded "
              "output and input file hashes. Float32 rounding leaves a maximum national-total difference of "
              f"{metadata['checks']['conservation_max_error_mw']:.8f} MW "
              f"(tolerance {metadata['checks']['conservation_tolerance_mw']:g} MW). "
              f"Null values across the canonical table: {sum(stats['null_counts'].values()):,}.", "",
              "**Window consistency:** `data/canonical/national_demand.parquet` and "
              "`data/canonical/generation_by_fuel.parquet` each contain "
              f"{stats['per_zone'][0]['expected_rows']:,} matching half-hour timestamps. "
              "Full NESO and Elexon files under `data/raw` are unchanged; the canonical builder trims copies. "
              "Unpublished fuel values remain null.", "",
              "**Sources:** NESO ND outturn and Open-Meteo Previous Runs previous_day1 output at contract zone centroids. "
              "Regional allocation uses contract shares and 1.5% per degree below 15.5 C, renormalised per half-hour. "
              "Supporting generation limitations are recorded in `stage2_checks.txt`.", "",
              "**Weather resampling:** " + INTERPOLATION_CAVEAT + " "
              "Solar is a preceding-hour source mean, interpolated as an approximate feature. "
              "Routine weather resampling does not set the target INTERPOLATED flag.", "",
              "[Daily target-coverage heatmap](data_coverage.png). Full figures and the validated file hash: "
              "`data_quality_summary.json`.", ""]
    return "\n".join(lines)


def render_heatmap(path, coverage, days, config, stats, sha):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        raise SystemExit("Install the chart dependency first: python -m pip install matplotlib")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig = plt.figure(figsize=(15, 5.2), facecolor="white")
    ax = fig.add_axes([0.10, 0.27, 0.76, 0.48])
    image = ax.imshow(coverage, aspect="auto", interpolation="nearest", cmap="YlGn", vmin=0, vmax=48)
    ax.set_yticks(np.arange(len(config["zone_order"])), config["zone_order"])
    months = [(i, d) for i, d in enumerate(days) if d.day == 1]
    shown = [(i, d) for i, d in months if d.month % 2 == 1]
    ax.set_xticks([i for i, _ in shown], [d.strftime("%b %Y") for _, d in shown])
    ax.tick_params(axis="both", length=0, labelsize=9, pad=8)
    for i, d in months:
        ax.axvline(i-.5, color="white", lw=1.3 if d.month == 1 else .35, alpha=.8)
    for i in np.arange(len(config["zone_order"])-1)+.5:
        ax.axhline(i, color="white", lw=.6)
    for spine in ax.spines.values():
        spine.set_visible(False)
    cax = fig.add_axes([.89, .27, .014, .48])
    bar = fig.colorbar(image, cax=cax, ticks=[0,12,24,36,48])
    bar.outline.set_visible(False)
    bar.ax.tick_params(length=0, labelsize=9)
    bar.set_label("Non-null half-hours per UTC day", labelpad=10)
    fig.text(.10, .93, "Regional demand data coverage", fontsize=21, weight="bold", color="#172d36")
    fig.text(.10, .865, f"{days.min():%d %b %Y} - {days.max():%d %b %Y}  |  "
             f"{stats['zones']} zones x {stats['utc_days']} UTC days  |  "
             f"{stats['target_coverage_pct']:.2f}% target availability", color="#53656f", fontsize=11)
    fig.text(.10, .13, "Counts show target availability, including flagged fills. Regional demand is estimated.",
             color="#53656f", fontsize=10)
    fig.text(.10, .075, "UTC days always contain 48 half-hours; local clock changes do not create gaps in this view.",
             color="#53656f", fontsize=10)
    fig.savefig(path, dpi=160, facecolor="white", metadata={"Title": "Daily canonical target coverage",
                "Description": "Source canonical Parquet SHA256: "+sha})
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract-file", type=Path, help="Optional exported contract; default reads schemas.py")
    args = parser.parse_args()
    root = args.root.resolve()
    config = load_contract(root, args.contract_file)
    path = root / "data/canonical/real.parquet"
    metadata = json.loads((root / "results/canonical_metadata.json").read_text(encoding="utf-8"))
    sha = file_hash(path)
    if metadata.get("original_checker_return_code") != 0 or metadata.get("output_sha256") != sha:
        raise ValueError("Run build_canonical.py successfully before reporting on this file")
    for name, expected in metadata["input_sha256"].items():
        if file_hash(root / name) != expected:
            raise ValueError(f"Source changed after validation: {name}; rerun build_canonical.py")
    for name, recorded in metadata["supporting_canonical"].items():
        supporting = root / "data/canonical" / name
        if file_hash(supporting) != recorded["sha256"]:
            raise ValueError(f"Supporting canonical file changed: {name}; rerun build_canonical.py")
        require_window_grid(pd.read_parquet(supporting, columns=["timestamp_utc"]).timestamp_utc, name)
    frame = pq.read_table(path).to_pandas()
    demand = pd.read_parquet(root / "data/canonical/national_demand.parquet")
    stats, coverage, days = summarize(frame, demand, config)
    stats["canonical_sha256"] = sha
    stats["recorded_team_checker_exit_code"] = 0
    stats["window_reason"] = WINDOW_REASON
    stats["weather_caveat"] = WEATHER_CAVEAT
    stats["interpolation_caveat"] = INTERPOLATION_CAVEAT
    stats["supporting_canonical"] = metadata["supporting_canonical"]
    results = root / "results"
    render_heatmap(results / "data_coverage.png", coverage, days, config, stats, sha)
    (results / "data_quality.md").write_text(render_report(stats, metadata), encoding="utf-8")
    (results / "data_quality_summary.json").write_text(json.dumps(stats, indent=2)+"\n", encoding="utf-8")
    print("Stage 6 quality report: COMPLETE")
    print(f"Rows: {stats['rows']:,}; zones: {stats['zones']}; target coverage: {stats['target_coverage_pct']:.2f}%")
    print(f"Target gaps longer than two hours: {len(stats['gaps_over_two_hours'])}")
    for name in ["data_quality.md", "data_coverage.png", "data_quality_summary.json"]:
        print(f"Wrote: {results / name}")


if __name__ == "__main__":
    main()
