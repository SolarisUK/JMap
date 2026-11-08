"""One-shot calendar-split real-data evaluation of the frozen forecaster recipe."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

import baseline
from calibration import Calibrator
import features
import hybrid
import schemas as S
import train

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data/canonical/real.parquet"
OUT = ROOT / "artifacts/real_once_20261108"
START = pd.Timestamp("2024-03-07T00:00Z")
VAL = pd.Timestamp("2025-04-01T00:00Z")
TEST = pd.Timestamp("2025-07-01T00:00Z")
END = pd.Timestamp("2026-01-01T00:00Z")
CHART = pd.Timestamp("2025-12-14T00:00Z")


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def grids(data, start, end, cadence):
    times = pd.DatetimeIndex(data.timestamp_utc.unique()).sort_values()
    return times[(times >= start) & (times < end)
                 & ((times.hour * 60 + times.minute) % cadence == 0)]


def development_split(rows):
    good = ((rows.quality_flag & S.QF_UNSCORABLE) == 0) & np.isfinite(rows.demand_mw)
    fit = rows.loc[good & (rows.issue_time >= START) & (rows.issue_time < VAL)
                   & (rows.target_time < VAL)].copy()
    val = rows.loc[good & (rows.issue_time >= VAL) & (rows.issue_time < TEST)
                   & (rows.target_time < TEST)].copy()
    assert len(fit) and len(val)
    return fit, val


def metrics(rows, values):
    """Matched pooled-zone MAE and MAPE of national sums, never zone MAPE."""
    common = np.asarray(baseline._scoring_mask(rows)) & np.isfinite(rows._persistence_offset_mw)
    common &= np.isfinite(values).all(axis=1)
    selected = rows.loc[common].copy()
    q = values[common]
    if selected.empty:
        raise ValueError("No common test cohort")
    predictions = {"hybrid": q[:, 1], "persistence": selected._persistence_offset_mw.to_numpy(),
                   "weekly": selected.lag_1w.to_numpy()}
    actual = selected.demand_mw.to_numpy()
    hs = selected.h.to_numpy()
    report = {"mae_by_horizon_mw": {}, "overall_mae_mw": {}, "national_mape_pct": {}}
    for name, pred in predictions.items():
        errors = np.abs(actual - pred)
        report["overall_mae_mw"][name] = float(errors.mean())
        report["mae_by_horizon_mw"][name] = {str(h): float(errors[hs == h].mean())
                                                    for h in baseline.HORIZONS}
        selected[name] = pred
    grouped = selected.groupby(["issue_time", "h", "target_time"], observed=True)
    counts = grouped.zone_id.nunique()
    totals = grouped[["demand_mw", *predictions]].sum()
    totals = totals.loc[(counts == S.N_ZONES) & (totals.demand_mw > 0)]
    if totals.empty:
        raise ValueError("No complete ten-zone national sums")
    for name in predictions:
        report["national_mape_pct"][name] = float(
            (np.abs(totals[name] - totals.demand_mw) / totals.demand_mw).mean() * 100)
    report.update(coverage_80_pct=float(((actual >= q[:, 0]) & (actual <= q[:, 2])).mean() * 100),
                  scored_issue_times=int(selected.issue_time.nunique()), scored_zone_horizon_rows=len(selected),
                  complete_national_issue_horizon_rows=len(totals),
                  national_issue_times=int(totals.index.get_level_values("issue_time").nunique()))
    saved = rows.copy()
    saved[["p10", "p50", "p90"]] = values
    saved["scored_common"] = common
    return report, saved


def self_test():
    rows = pd.DataFrame({"zone_id": pd.Categorical(list(S.ZONE_ORDER), categories=S.ZONE_ORDER),
        "issue_time": [TEST] * S.N_ZONES, "target_time": [TEST] * S.N_ZONES,
        "h": [1] * S.N_ZONES, "quality_flag": [S.QF.OK] * S.N_ZONES,
        "demand_mw": [100.] * S.N_ZONES, "lag_1w": [100.] * S.N_ZONES,
        "_persistence_offset_mw": [100.] * S.N_ZONES})
    q = np.tile([50., 100., 150.], (S.N_ZONES, 1))
    q[0, 1] += 10; q[1, 1] -= 10
    # Opposite zone errors cancel in the national sum but not in pooled MAE.
    for h in baseline.HORIZONS:
        rows.h = h
        rows.target_time = rows.issue_time + (h - 1) * features.STEP
        # Metrics normally sees all horizons; replicate a complete tiny cohort.
    tiny = pd.concat([rows.assign(h=h, target_time=TEST+(h-1)*features.STEP)
                      for h in baseline.HORIZONS], ignore_index=True)
    result, _ = metrics(tiny, np.tile(q, (len(baseline.HORIZONS), 1)))
    assert result["national_mape_pct"]["hybrid"] == 0
    assert result["overall_mae_mw"]["hybrid"] == 2
    check = pd.DataFrame({"issue_time": [VAL-features.STEP, VAL-features.STEP, VAL, TEST-features.STEP],
        "target_time": [VAL-features.STEP, VAL, VAL, TEST], "demand_mw": [1.] * 4,
        "quality_flag": [S.QF.OK] * 4})
    fit, val = development_split(check)
    assert len(fit) == len(val) == 1
    print("SELF CHECK PASS: boundary purging and national-sum MAPE", flush=True)


def prepare():
    OUT.mkdir(parents=True, exist_ok=False)
    os.environ["EUGENE_FORECAST_DATA"] = str(DATA)
    sources = ["train.py", "features.py", "hybrid.py", "calibration.py", "baseline.py", "forecast.py", "schemas.py", "real_evaluation.py"]
    plan = {"created_at": stamp(), "data_path": str(DATA), "data_sha256": sha(DATA),
        "github_blob_sha": "0b611bd676af2182bc347f7c609c2ef40ee419c2", "train_start": START.isoformat(),
        "validation_start": VAL.isoformat(), "test_start": TEST.isoformat(), "end_exclusive": END.isoformat(),
        "development_cadence_minutes": 120, "source_sha256": {n: sha(ROOT/n) for n in sources},
        "test_scoring_passes": 0, "calibration": "frozen rolling48h; validation corpus only; no test outcomes",
        "estimated_zonal_demand": True}
    write(OUT/"run_plan.json", plan)
    data = features.load(DATA, before=TEST)
    assert data.timestamp_utc.max() < TEST
    t0 = time.monotonic()
    issues = grids(data, START, TEST, 120)
    rows = features._build_rows(data, issues)
    features.check_no_leakage(rows)
    fit, val = development_split(rows)
    # Persist exactly the frozen booster inputs and causal transform metadata.
    keep = list(dict.fromkeys(features.FEATURE_NAMES + ["log_recent_ratio", "_persistence_offset_mw",
        "demand_mw", "issue_time", "target_time", "quality_flag"]))
    fit[keep].to_parquet(OUT/"train.parquet", index=False)
    val[keep].to_parquet(OUT/"validation.parquet", index=False)
    plan.update(training_rows=len(fit), validation_rows=len(val),
                development_feature_seconds=time.monotonic()-t0,
                training_issue_times=int(fit.issue_time.nunique()), validation_issue_times=int(val.issue_time.nunique()))
    for name, source in (("last_known", ROOT/"models/training_config.json"),
                         ("relative", ROOT/"models/relative/training_config.json")):
        frozen = json.loads(source.read_text())
        config = {**train.make_target_config(fit, frozen["target_mode"]), "params": frozen["params"],
            "early_stopping_rounds": frozen["early_stopping_rounds"], "data_path": str(DATA),
            "contract_version": S.CONTRACT_VERSION, "input_provenance": {"synthetic": False, "sha256": plan["data_sha256"]},
            "split_info": {"validation_start": VAL.isoformat(), "test_start": TEST.isoformat(), "end_exclusive": END.isoformat()},
            "evaluation_scope": "real_calendar_one_shot", "frozen_source_sha256": sha(source)}
        directory = OUT/"candidates"/name
        directory.mkdir(parents=True)
        write(directory/"training_config.json", config)
        write(directory/"feature_names.json", features.model_feature_names(config))
    write(OUT/"run_plan.json", plan)
    print(json.dumps(plan), flush=True)


def fit_one(item):
    name, alpha = item
    directory = OUT/"candidates"/name
    config = json.loads((directory/"training_config.json").read_text())
    fit, val = pd.read_parquet(OUT/"train.parquet"), pd.read_parquet(OUT/"validation.parquet")
    t0 = time.monotonic()
    print(f"FIT START {name} P{round(alpha*100)} {stamp()}", flush=True)
    model = train.fit_model(alpha, fit, val, overrides=config["params"], n_jobs=config["params"]["n_jobs"],
                            early_stopping_rounds=config["early_stopping_rounds"], target_config=config)
    model.booster_.save_model(str(directory/f"lgbm_q{round(alpha*100)}.txt"))
    result = {"candidate": name, "quantile": alpha, "best_iteration": int(model.best_iteration_),
              "seconds": time.monotonic()-t0, "completed_at": stamp()}
    write(directory/f"fit_q{round(alpha*100)}.json", result)
    print("FIT DONE " + json.dumps(result), flush=True)
    return result


def fit_all():
    jobs = [(name, alpha) for name in ("last_known", "relative") for alpha in S.QUANTILES]
    with ProcessPoolExecutor(max_workers=6, mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(pool.map(fit_one, jobs))
    write(OUT/"fits.json", results)


def predict(rows):
    predictions = {}
    for name in ("last_known", "relative"):
        directory = OUT/"candidates"/name
        config = json.loads((directory/"training_config.json").read_text())
        models = tuple(lgb.Booster(model_file=str(directory/f"lgbm_q{round(q*100)}.txt")) for q in S.QUANTILES)
        predictions[name] = features.predict_quantiles(models, rows, config, threads=8)
    return predictions


def select():
    val = pd.read_parquet(OUT/"validation.parquet")
    t0 = time.monotonic()
    predictions = predict(val)
    seconds = time.monotonic()-t0
    reference = val._persistence_offset_mw.to_numpy(dtype=float)
    model_map, best = hybrid.select_models(val, predictions, reference)
    profile = hybrid.select_horizons(val, best, reference)
    profile.update(model_by_horizon=model_map, data_sha256=sha(DATA), learned_model_candidates=["last_known", "relative"])
    raw = hybrid.apply_hybrid(val, best, profile)
    corpus = val[["zone_id", "issue_time", "target_time", "h", "demand_mw", "quality_flag"]].copy()
    corpus[["q10", "q50", "q90"]] = raw
    calibrator = Calibrator(corpus, VAL)
    calibrator.save(OUT/"calibration.parquet")
    profile["validation_prediction_seconds"] = seconds
    profile["validation_rows"] = len(val)
    write(OUT/"hybrid_policy.json", profile)
    print("ROUTING FROZEN " + json.dumps({h:c["source"] for h,c in profile["horizons"].items()}), flush=True)
    print(f"Validation inference {seconds:.2f} seconds for {len(val)} rows", flush=True)


def score(cadence):
    profile = json.loads((OUT/"hybrid_policy.json").read_text())
    clock = pd.read_parquet(DATA, columns=["timestamp_utc"])
    full = grids(clock, TEST, END, 30)
    latest = clock.timestamp_utc.max() - (S.FORECAST_HORIZON-1)*features.STEP
    full = full[full <= latest]
    estimate = profile["validation_prediction_seconds"] * (len(full)*S.N_ZONES*S.FORECAST_HORIZON/profile["validation_rows"]) * 2 + 90
    if cadence == 0:
        deadline = pd.Timestamp("2026-11-08T09:30Z")
        cadence = 360 if pd.Timestamp.now(tz="UTC") + pd.Timedelta(seconds=estimate) >= deadline else 30
    issues = full[(full.hour*60+full.minute) % cadence == 0]
    started = {"started_at": stamp(), "cadence_minutes": cadence, "planned_issue_times": len(issues),
               "estimated_full_test_seconds": estimate, "model_profile_sha256": sha(OUT/"hybrid_policy.json")}
    with (OUT/"test_started.json").open("x") as handle:
        json.dump(started, handle, indent=2)
    print("ONE-SHOT TEST START " + json.dumps(started), flush=True)
    data = features.load(DATA)
    rows = features._build_rows(data, issues)
    assert (rows.issue_time >= TEST).all() and (rows.target_time < END).all()
    features.check_no_leakage(rows)
    predictions = predict(rows)
    best = hybrid.route_models(rows, predictions, profile["model_by_horizon"])
    raw = hybrid.apply_hybrid(rows, best, profile)
    calibrator = Calibrator(OUT/"calibration.parquet", VAL)
    values = calibrator.apply(rows, raw)
    np.testing.assert_array_equal(values[:, 1], raw[:, 1])
    report, saved = metrics(rows, values)
    saved[["zone_id", "issue_time", "target_time", "h", "demand_mw", "quality_flag", "lag_1w",
           "_persistence_offset_mw", "p10", "p50", "p90", "scored_common"]].to_parquet(OUT/"test_predictions.parquet", index=False)
    chart = saved.loc[(saved.zone_id == "LOND") & (saved.issue_time == CHART)].sort_values("h")
    if len(chart) != S.FORECAST_HORIZON:
        # Chart-only inference is explicitly requested and never changes test selection.
        chart = features._build_rows(data, [CHART], "LOND")
        features.check_no_leakage(chart)
        cp = predict(chart)
        cb = hybrid.apply_hybrid(chart, hybrid.route_models(chart, cp, profile["model_by_horizon"]), profile)
        chart[["p10", "p50", "p90"]] = calibrator.apply(chart, cb)
    assert len(chart) == S.FORECAST_HORIZON
    chart = chart.rename(columns={"target_time": "timestamp_utc", "demand_mw": "actual_mw"})
    chart[["timestamp_utc", "p10", "p50", "p90", "actual_mw"]].to_csv(OUT/"LOND_2025-12-14T0000Z.csv", index=False)
    report.update(started, completed_at=stamp(), data_sha256=sha(DATA), test_scoring_passes=1,
        routing={h:c["source"] for h,c in profile["horizons"].items()},
        split_ranges={"train": [START.isoformat(), VAL.isoformat()], "validation": [VAL.isoformat(), TEST.isoformat()],
                      "test": [TEST.isoformat(), END.isoformat()]}, end_boundaries="exclusive; targets purged at split boundary",
        calibration="Frozen 48h rolling rule, validation corpus only; corrections expire after first two test days",
        chart_csv=str(OUT/"LOND_2025-12-14T0000Z.csv"))
    write(OUT/"test_results.json", report)
    print("FINAL REAL TEST " + json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["self-test", "prepare", "fit", "select", "score"])
    parser.add_argument("--test-cadence-minutes", type=int, choices=[0,30,360], default=0)
    args = parser.parse_args()
    os.environ["EUGENE_FORECAST_DATA"] = str(DATA)
    if args.phase == "self-test": self_test()
    elif args.phase == "prepare": prepare()
    elif args.phase == "fit": fit_all()
    elif args.phase == "select": select()
    else: score(args.test_cadence_minutes)
