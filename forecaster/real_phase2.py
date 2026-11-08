"""Causal interval update and frozen-recipe expanding-window checks."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

import baseline
from calibration import Calibrator
import features
import hybrid
import real_evaluation as first
import schemas as S
import train

ROOT = first.ROOT
OUT = ROOT / "artifacts/real_phase2_20261108"
RAW_COLS = ["zone_id", "issue_time", "target_time", "h", "demand_mw", "quality_flag"]


def adjustments(calibrator, unique):
    result, audit = calibrator.apply(unique, np.zeros((len(unique), len(S.QUANTILES))),
                                     return_provenance=True)
    cutoff = unique.issue_time - features.STEP
    assert not (audit.calibration_source_target_time_max > cutoff).any()
    assert not (audit.calibration_source_issue_time_max > cutoff).any()
    return result, audit


def calibration_check():
    issue = pd.Timestamp("2025-07-01T12:00Z")
    # An extreme outcome at issue time is not complete and cannot change the tails.
    corpus = pd.DataFrame({"zone_id": [S.ZONE_ORDER[0]] * 50,
        "issue_time": [issue-pd.Timedelta(days=1)] * 48 + [issue] * 2,
        "target_time": [issue-pd.Timedelta(days=1)] * 48 + [issue] * 2,
        "h": [1] * 50, "demand_mw": [50.] * 48 + [1e12] * 2,
        "quality_flag": [S.QF.OK] * 50, "q10": [90.] * 50,
        "q50": [100.] * 50, "q90": [110.] * 50})
    cal = Calibrator(corpus, "2025-06-01T00:00Z")
    unique = pd.DataFrame({"zone_id": [S.ZONE_ORDER[0]], "issue_time": [issue]})
    values, audit = adjustments(cal, unique)
    assert values.tolist() == [[-40., 0., 0.]]
    assert int(audit.calibration_rows.iloc[0]) == 48
    print("CAUSAL SELF CHECK PASS", flush=True)


def calibrate():
    OUT.mkdir(parents=True, exist_ok=True)
    fingerprints = {str(p.relative_to(first.OUT)): first.sha(p)
                    for p in (first.OUT/"candidates").rglob("*") if p.is_file()}
    fingerprints["hybrid_policy.json"] = first.sha(first.OUT/"hybrid_policy.json")
    with (OUT/"calibration_started.json").open("x") as handle:
        json.dump({"started_at": first.stamp(), "frozen_fingerprints": fingerprints}, handle, indent=2)
    rows = pd.read_parquet(first.OUT/"test_predictions.parquet")
    old = rows[["p10", "p50", "p90"]].to_numpy(dtype=float)
    unique = rows[["zone_id", "issue_time"]].drop_duplicates().reset_index(drop=True)
    unique_keys = pd.MultiIndex.from_frame(unique)
    indexes = unique_keys.get_indexer(pd.MultiIndex.from_frame(rows[["zone_id", "issue_time"]]))
    assert (indexes >= 0).all()
    old_calibrator = Calibrator(first.OUT/"calibration.parquet", first.VAL)
    old_shift, _ = adjustments(old_calibrator, unique)
    raw = old - old_shift[indexes]
    np.testing.assert_array_equal(raw[:, 1], old[:, 1])
    assert (np.diff(raw, axis=1) >= 0).all()
    test_corpus = rows[RAW_COLS].copy()
    test_corpus[["q10", "q50", "q90"]] = raw
    corpus = pd.concat([pd.read_parquet(first.OUT/"calibration.parquet"), test_corpus], ignore_index=True)
    cal = Calibrator(corpus, first.VAL)
    shift, audit = adjustments(cal, unique)
    updated = raw + shift[indexes]
    np.testing.assert_array_equal(updated[:, 1], old[:, 1])
    assert (np.diff(updated, axis=1) >= 0).all()
    report, _ = first.metrics(rows, updated)
    previous = json.loads((first.OUT/"test_results.json").read_text())
    for key in ("mae_by_horizon_mw", "overall_mae_mw", "national_mape_pct"):
        assert report[key] == previous[key], f"Median metric changed: {key}"
    after = {str(p.relative_to(first.OUT)): first.sha(p)
             for p in (first.OUT/"candidates").rglob("*") if p.is_file()}
    after["hybrid_policy.json"] = first.sha(first.OUT/"hybrid_policy.json")
    assert fingerprints == after
    audit = pd.concat([unique, audit], axis=1)
    audit.to_parquet(OUT/"calibration_audit.parquet", index=False)
    rows[["p10", "p50", "p90"]] = updated
    rows.to_parquet(OUT/"test_predictions_causal.parquet", index=False)
    report.update(completed_at=first.stamp(), phase2_test_scoring_passes=1,
        calibration="Frozen 48h/min48 empirical tails; validation and matured test outcomes",
        future_target_sources=0, future_issue_sources=0, model_routing_unchanged=True, median_bit_exact=True)
    first.write(OUT/"test_results_causal.json", report)
    print("PHASE2 A COMPLETE " + json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["self-test", "calibrate"])
    args = parser.parse_args()
    os.environ["EUGENE_FORECAST_DATA"] = str(first.DATA)
    if args.phase == "self-test": calibration_check()
    else: calibrate()
