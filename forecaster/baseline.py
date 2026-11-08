"""Same-half-hour-last-week baseline and the shared, fixed-duration chronological split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import features
import schemas as S

HORIZONS = (1, 4, 12, 24, 48)


def time_split(df):
    """Return train/validation/test with 14-day holdouts measured by issue_time.

    The exclusive end is the last issue plus one nanosecond. Earlier split labels
    reaching the next issue window are purged so no fitting label enters a holdout.
    Insufficient history is an error; the windows are never silently shortened.
    """
    if df.empty:
        raise ValueError("Cannot split an empty feature table")
    for name in ("issue_time", "target_time"):
        if not isinstance(df[name].dtype, pd.DatetimeTZDtype) or df[name].isna().any():
            raise ValueError(f"{name} must contain timezone-aware, non-null timestamps")
    end = df.issue_time.max() + pd.Timedelta(nanoseconds=1)
    test_start = end - pd.Timedelta(days=14)
    validation_start = end - pd.Timedelta(days=28)
    masks = (df.issue_time < validation_start,
             (df.issue_time >= validation_start) & (df.issue_time < test_start),
             df.issue_time >= test_start)
    cutoffs = (validation_start, test_start, None)
    names = ("train", "validation", "test")
    parts, purged = [], {}
    for name, mask, cutoff in zip(names, masks, cutoffs):
        safe = mask & (df.target_time < cutoff) if cutoff is not None else mask
        purged[name] = int(mask.sum() - safe.sum())
        order = ["issue_time", "h"] if "h" in df else ["issue_time"]
        part = df.loc[safe].sort_values(order).copy()
        if part.empty:
            raise ValueError(f"Insufficient history: {name} is empty after the fixed 14-day test, "
                             "14-day validation, and target-overlap purge. More than 28 days "
                             "of issue times are required; supply a longer canonical history.")
        parts.append(part)
    info = {"end_exclusive": end.isoformat(), "test_start": test_start.isoformat(),
            "validation_start": validation_start.isoformat(), "purged_rows": purged}
    for part in parts:
        part.attrs["split_info"] = info
    return tuple(parts)


def _scoring_mask(df):
    return (np.isfinite(df.demand_mw.to_numpy(dtype=float))
            & np.isfinite(df.lag_1w.to_numpy(dtype=float))
            & ((df.quality_flag.fillna(S.QF.MISSING).astype("uint8") & S.QF_UNSCORABLE) == 0))


def scoring_rows(df):
    """Rows usable for both the weekly baseline and model evaluation."""
    return df.loc[_scoring_mask(df)].copy()


def metrics(df, predictions=None):
    """MAE/WAPE on shared scorable rows, defaulting to lag_1w as the prediction."""
    prediction = np.asarray(df.lag_1w if predictions is None else predictions, dtype=float)
    if prediction.shape != (len(df),):
        raise ValueError("predictions must have one value for each feature row")
    mask = _scoring_mask(df)
    if not mask.any():
        raise ValueError("No scorable targets with finite lag_1w baseline values")
    if not np.isfinite(prediction[mask]).all():
        raise ValueError("Model predictions must be finite on every shared scoring row")
    y, pred = df.loc[mask, "demand_mw"].to_numpy(dtype=float), prediction[mask]
    denominator = float(np.abs(y).sum())
    if denominator == 0:
        raise ValueError("WAPE is undefined when total observed demand is zero")
    errors = np.abs(y - pred)
    horizons = df.loc[mask, "h"].to_numpy()
    return {"mae_mw": float(errors.mean()), "wape": float(errors.sum() / denominator),
            "mae_by_horizon": {str(h): float(errors[horizons == h].mean()) if (horizons == h).any() else None
                               for h in HORIZONS}, "rows": len(y)}


def split_ranges(parts):
    return {name: {"issue_start": part.issue_time.min().isoformat(),
                   "issue_end": part.issue_time.max().isoformat(),
                   "target_start": part.target_time.min().isoformat(),
                   "target_end": part.target_time.max().isoformat(), "rows": len(part)}
            for name, part in zip(("train", "validation", "test"), parts)}


def load_feature_table(data_path=None, feature_path=None):
    """Resolve a cache's canonical source instead of silently relabelling its provenance."""
    if feature_path is None:
        data_path = Path(data_path or features.DEFAULT_DATA)
        return features.build(data_path), data_path
    frame = pd.read_parquet(feature_path)
    recorded = frame.attrs.get("data_path")
    if data_path is not None and recorded is not None and Path(data_path).resolve() != Path(recorded).resolve():
        raise ValueError("Explicit --data conflicts with the cached features' data_path provenance")
    if data_path is None and recorded is None:
        raise ValueError("Cached features have no data_path provenance; specify --data")
    return frame, Path(data_path or recorded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, help="canonical parquet (inferred from cache when --features is used)")
    parser.add_argument("--features", type=Path, help="previously built feature-table parquet")
    parser.add_argument("--out", type=Path, default=Path("results/baseline.json"))
    args = parser.parse_args()
    frame, data_path = load_feature_table(args.data, args.features)
    parts = time_split(frame)
    _, validation, test = parts
    test_metrics, validation_metrics = metrics(test), metrics(validation)
    result = {"baseline": "lag_1w", **test_metrics, "baseline_mae_mw": test_metrics["mae_mw"],
              "validation": validation_metrics, "test": test_metrics,
              "date_ranges": split_ranges(parts), "split_info": test.attrs["split_info"],
              "data_path": str(data_path.resolve()),
              "feature_path": str(args.features.resolve()) if args.features else None}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print("Same half-hour last week (lag_1w)")
    print(f"{'split':12s} {'MAE MW':>12s} {'WAPE':>12s} {'rows':>10s}")
    for name, values in (("validation", validation_metrics), ("test", test_metrics)):
        print(f"{name:12s} {values['mae_mw']:12.3f} {values['wape']:12.4%} {values['rows']:10d}")
    for h, value in test_metrics["mae_by_horizon"].items():
        print(f"test h={h:>2s}: {value:.3f} MW" if value is not None else f"test h={h}: no rows")
    print("Purged rows:", test.attrs["split_info"]["purged_rows"])


if __name__ == "__main__":
    main()
