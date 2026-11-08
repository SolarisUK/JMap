"""Three predeclared expanding-history windows using the frozen forecast recipe."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

import baseline
import features
import hybrid
import real_evaluation as first
import schemas as S
import train

PHASE1 = first.OUT
OUT = first.ROOT / "artifacts/real_phase2_20261108/walkforward"
ORIGINS = tuple(pd.Timestamp(s) for s in ("2025-07-01T00:00Z", "2025-09-01T00:00Z", "2025-11-01T00:00Z"))


def folder(origin):
    return OUT / origin.strftime("%Y-%m-%d")


def fold_split(rows, origin):
    validation_start = origin - pd.DateOffset(months=3)
    good = ((rows.quality_flag & S.QF_UNSCORABLE) == 0) & np.isfinite(rows.demand_mw)
    fit = rows.loc[good & (rows.issue_time >= first.START) & (rows.issue_time < validation_start)
                   & (rows.target_time < validation_start)].copy()
    val = rows.loc[good & (rows.issue_time >= validation_start) & (rows.issue_time < origin)
                   & (rows.target_time < origin)].copy()
    assert len(fit) and len(val)
    assert fit.target_time.max() < validation_start and val.target_time.max() < origin
    return fit, val


def self_test():
    origin = ORIGINS[1]
    val_start = pd.Timestamp("2025-06-01T00:00Z")
    rows = pd.DataFrame({"issue_time": [val_start-features.STEP, val_start-features.STEP, val_start, origin-features.STEP],
        "target_time": [val_start-features.STEP, val_start, val_start, origin],
        "demand_mw": [1.] * 4, "quality_flag": [S.QF.OK] * 4})
    fit, val = fold_split(rows, origin)
    assert len(fit) == len(val) == 1
    print("WALK-FORWARD BOUNDARY SELF CHECK PASS", flush=True)


def prepare():
    if not (OUT.parent/"test_results_causal.json").exists():
        raise RuntimeError("Phase 2(a) must complete first")
    OUT.mkdir(parents=True, exist_ok=False)
    first.write(OUT/"run_plan.json", {"created_at": first.stamp(), "origins": [s.isoformat() for s in ORIGINS],
        "protocol": "Expanding train, preceding3calendar-month validation; issue-time evaluation windows",
        "features_and_hyperparameters": "frozen", "development_cadence_minutes": 120,
        "test_cadence_minutes": 30, "july_model": "reuse identical phase1 fit and routing",
        "data_sha256": first.sha(first.DATA), "source_sha256": first.sha(Path(__file__))})
    keep = list(dict.fromkeys(features.FEATURE_NAMES + ["log_recent_ratio", "_persistence_offset_mw",
        "demand_mw", "issue_time", "target_time", "quality_flag"]))
    for origin in ORIGINS[1:]:
        path = folder(origin)
        path.mkdir()
        data = features.load(first.DATA, before=origin)
        assert data.timestamp_utc.max() < origin
        issues = first.grids(data, first.START, origin, 120)
        rows = features._build_rows(data, issues)
        features.check_no_leakage(rows)
        fit, val = fold_split(rows, origin)
        fit[keep].to_parquet(path/"train.parquet", index=False)
        val[keep].to_parquet(path/"validation.parquet", index=False)
        validation_start = origin-pd.DateOffset(months=3)
        for name in ("last_known", "relative"):
            frozen_path = PHASE1/"candidates"/name/"training_config.json"
            frozen = json.loads(frozen_path.read_text())
            config = {**train.make_target_config(fit, frozen["target_mode"]), "params": frozen["params"],
                "early_stopping_rounds": frozen["early_stopping_rounds"], "data_path": str(first.DATA),
                "contract_version": S.CONTRACT_VERSION, "input_provenance": frozen["input_provenance"],
                "split_info": {"train_start": first.START.isoformat(), "validation_start": validation_start.isoformat(),
                               "test_start": origin.isoformat()}, "evaluation_scope": "walk_forward_frozen_recipe",
                "training_rows": len(fit), "validation_rows": len(val), "frozen_source_sha256": first.sha(frozen_path)}
            destination = path/"candidates"/name
            destination.mkdir(parents=True)
            first.write(destination/"training_config.json", config)
            first.write(destination/"feature_names.json", features.model_feature_names(config))
        print(f"FOLD PREPARED {origin.date()} train={len(fit)} val={len(val)}", flush=True)


def fit_worker(job):
    origin, name, q = job
    first.OUT = folder(pd.Timestamp(origin))
    result = first.fit_one((name, q))
    result["origin"] = origin
    return result


def fit_all():
    jobs = [(origin.isoformat(), name, q) for origin in ORIGINS[1:]
            for name in ("last_known", "relative") for q in S.QUANTILES]
    with ProcessPoolExecutor(max_workers=6, mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(pool.map(fit_worker, jobs))
    first.write(OUT/"fits.json", results)


def predict(path, rows):
    predictions = {}
    for name in ("last_known", "relative"):
        directory = path/"candidates"/name
        config = json.loads((directory/"training_config.json").read_text())
        boosters = tuple(lgb.Booster(model_file=str(directory/f"lgbm_q{round(q*100)}.txt")) for q in S.QUANTILES)
        predictions[name] = features.predict_quantiles(boosters, rows, config, threads=8)
    return predictions


def score():
    reports = []
    for i, origin in enumerate(ORIGINS):
        end = ORIGINS[i+1] if i+1 < len(ORIGINS) else first.END
        path = folder(origin)
        path.mkdir(parents=True, exist_ok=True)
        if i == 0:
            profile = json.loads((PHASE1/"hybrid_policy.json").read_text())
        else:
            val = pd.read_parquet(path/"validation.parquet")
            predictions = predict(path, val)
            mapping, best = hybrid.select_models(val, predictions, val._persistence_offset_mw.to_numpy(dtype=float))
            profile = hybrid.select_horizons(val, best, val._persistence_offset_mw.to_numpy(dtype=float))
            profile["model_by_horizon"] = mapping
        first.write(path/"hybrid_policy.json", profile)
        with (path/"score_started.json").open("x") as stream:
            json.dump({"started_at": first.stamp(), "origin": origin.isoformat(), "end_exclusive": end.isoformat()}, stream)
        if i == 0:
            rows = pd.read_parquet(PHASE1/"test_predictions.parquet", filters=[("issue_time", ">=", origin), ("issue_time", "<", end)])
            values = rows[["p10", "p50", "p90"]].to_numpy(dtype=float)
        else:
            data = features.load(first.DATA)
            issues = first.grids(data, origin, end, 30)
            latest = data.timestamp_utc.max()-(S.FORECAST_HORIZON-1)*features.STEP
            issues = issues[issues <= latest]
            rows = features._build_rows(data, issues)
            features.check_no_leakage(rows)
            predictions = predict(path, rows)
            values = hybrid.apply_hybrid(rows, hybrid.route_models(rows, predictions, profile["model_by_horizon"]), profile)
        report, saved = first.metrics(rows, values)
        report.update(origin=origin.isoformat(), issue_end_exclusive=end.isoformat(), completed_at=first.stamp(),
            reused_july_fit=(i == 0), test_scoring_passes=1,
            routing={h:c["source"] for h,c in profile["horizons"].items()},
            validation_start=(origin-pd.DateOffset(months=3)).isoformat())
        saved[["zone_id", "issue_time", "target_time", "h", "demand_mw", "lag_1w", "_persistence_offset_mw", "p50", "scored_common"]].to_parquet(path/"predictions.parquet", index=False)
        first.write(path/"results.json", report)
        reports.append(report)
        first.write(OUT/"results.json", reports)
        print("WINDOW COMPLETE " + json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["self-test", "prepare", "fit", "score"])
    args = parser.parse_args()
    os.environ["EUGENE_FORECAST_DATA"] = str(first.DATA)
    if args.phase == "self-test": self_test()
    elif args.phase == "prepare": prepare()
    elif args.phase == "fit": fit_all()
    else: score()
