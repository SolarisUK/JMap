"""Three global, direct multi-horizon LightGBM quantile models using shared time splits."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

import baseline
import features
import schemas as S

TRAIN_PARAMS = dict(objective="quantile", n_estimators=3000, learning_rate=0.05,
                    num_leaves=128, min_child_samples=50, subsample=0.8, subsample_freq=1,
                    colsample_bytree=0.8, reg_lambda=1.0, max_bin=255, n_jobs=-1)


def make_target_config(train_rows, target_mode="identity"):
    if target_mode == "identity":
        return {"target_mode": "identity", "zone_intercepts_mw": {}, "offset_priority": []}
    if target_mode not in ("weekly_residual", "last_known_residual", "persistence_residual", "log_persistence_residual"):
        raise ValueError(f"Unknown target mode: {target_mode}")
    medians = train_rows.groupby("zone_id", observed=True).demand_mw.median()
    return {"target_mode": target_mode,
            "zone_intercepts_mw": {str(zone): float(value) for zone, value in medians.items()},
            "offset_priority": (["last_known", "lag_1d", "lag_1w", "zone_intercepts_mw"]
                                if target_mode in ("last_known_residual", "persistence_residual", "log_persistence_residual") else
                                ["lag_1w", "lag_1d", "last_known", "zone_intercepts_mw"])}


def _targets(rows, config):
    offset = features.model_offset(rows, config)
    if config.get("target_mode") == "log_persistence_residual":
        return np.log(rows.demand_mw / offset)
    return rows.demand_mw - offset


def predictions(model, rows, config=None):
    """Convert saved-booster outputs into MW before any scoring or quantile sorting."""
    config = config or {"target_mode": "identity"}
    result = np.asarray(model.predict(rows[features.model_feature_names(config)], num_threads=1), dtype=float)
    return features.restore_prediction(result, rows, config)


def fit_model(alpha, train_rows, validation_rows, overrides=None, n_jobs=-1, early_stopping_rounds=100,
              target_config=None):
    """Fit one global quantile, shared by ordinary training and the Optuna sweep."""
    params = {**TRAIN_PARAMS, **(overrides or {}), "objective": "quantile", "alpha": alpha,
              "n_jobs": n_jobs, "random_state": 0, "verbosity": -1}
    target_config = target_config or make_target_config(train_rows)
    if target_config["target_mode"] != "identity":
        primary = ("_persistence_offset_mw" if target_config["target_mode"] in ("persistence_residual", "log_persistence_residual")
                   else target_config["offset_priority"][0])
        usable = np.isfinite(train_rows[primary])
        if target_config["target_mode"] == "log_persistence_residual":
            usable &= (train_rows[primary] > 0) & np.isfinite(train_rows.demand_mw) & (train_rows.demand_mw > 0)
            valid_eval = np.isfinite(validation_rows.demand_mw) & (validation_rows.demand_mw > 0)
            validation_rows = validation_rows.loc[valid_eval].copy()
        train_rows = train_rows.loc[usable].copy()
        if train_rows.empty:
            raise ValueError(f"Residual training requires finite {primary} history")
    model = lgb.LGBMRegressor(**params)
    names = features.model_feature_names(target_config)
    model.fit(train_rows[names], _targets(train_rows, target_config),
              eval_X=validation_rows[names], eval_y=_targets(validation_rows, target_config),
              categorical_feature=["zone_id"], eval_metric="quantile",
              callbacks=[lgb.early_stopping(early_stopping_rounds, verbose=False),
                         lgb.log_evaluation(period=200)])
    return model


def train_models(frame, out=Path(S.MODEL_DIR), overrides=None, n_jobs=-1,
                 data_path=None, baseline_path=None, early_stopping_rounds=100, target_mode="identity"):
    """Train and save all three boosters; raise if P50 fails its validation gate."""
    if not isinstance(frame.zone_id.dtype, pd.CategoricalDtype):
        raise ValueError("zone_id must retain its pandas category dtype")
    if "lag_1d_source_time" in frame:
        features.check_no_leakage(frame)
    train_rows, validation, test = baseline.time_split(frame)
    target_config = make_target_config(train_rows, target_mode)
    validation_scoring = baseline.scoring_rows(validation)
    baseline_mae = baseline.metrics(validation)["mae_mw"]
    if baseline_path is not None:
        recorded = json.loads(Path(baseline_path).read_text())["validation"]["mae_mw"]
        if not np.isclose(baseline_mae, recorded, rtol=1e-10, atol=1e-8):
            raise ValueError("Validation baseline differs from results/baseline.json; use the same feature table and split")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    models, iterations = {}, {}
    for alpha in S.QUANTILES:
        print(f"Training P{round(alpha * 100)} on {len(train_rows):,} rows, "
              f"validation {len(validation):,} rows, n_jobs={n_jobs}", flush=True)
        model = fit_model(alpha, train_rows, validation, overrides, n_jobs, early_stopping_rounds, target_config)
        model.booster_.save_model(str(out / f"lgbm_q{round(alpha * 100)}.txt"))
        models[alpha] = model
        iterations[str(alpha)] = model.best_iteration_
        print(f"P{round(alpha * 100)} best iteration: {model.best_iteration_}", flush=True)
    (out / "feature_names.json").write_text(json.dumps(features.model_feature_names(target_config), indent=2) + "\n")
    p50 = predictions(models[S.QUANTILES[1]], validation_scoring, target_config)
    validation_mae = baseline.metrics(validation_scoring, p50)["mae_mw"]
    provenance = {"synthetic": None, "source": "canonical provenance manifest unavailable"}
    if data_path is not None:
        data_path = Path(data_path)
        manifest = data_path.with_suffix(".manifest.json")
        if manifest.exists():
            provenance = json.loads(manifest.read_text())
            if provenance.get("sha256") != hashlib.sha256(data_path.read_bytes()).hexdigest():
                raise ValueError("Canonical data differs from its provenance manifest checksum")
    config = {
        "contract_version": S.CONTRACT_VERSION,
        **target_config,
        "data_path": str(Path(data_path).resolve()) if data_path else frame.attrs.get("data_path"),
        "input_provenance": provenance,
        "params": {**TRAIN_PARAMS, **(overrides or {}), "objective": "quantile", "n_jobs": n_jobs, "random_state": 0},
        "quantiles": list(S.QUANTILES), "early_stopping_rounds": early_stopping_rounds,
        "best_iterations": iterations,
        "date_ranges": baseline.split_ranges((train_rows, validation, test)),
        "split_info": train_rows.attrs["split_info"],
        "validation_mae_mw": validation_mae, "validation_baseline_mae_mw": baseline_mae,
        "validation_gate_passed": bool(validation_mae < baseline_mae),
        "fit_rows": int(np.isfinite(train_rows["_persistence_offset_mw" if target_mode in ("persistence_residual", "log_persistence_residual")
                                                else target_config["offset_priority"][0]]).sum()) if target_mode != "identity" else len(train_rows),
    }
    (out / "training_config.json").write_text(json.dumps(config, indent=2, allow_nan=False) + "\n")
    print(f"Validation P50 MAE: {validation_mae:.3f} MW | lag_1w baseline: {baseline_mae:.3f} MW", flush=True)
    if validation_mae >= baseline_mae:
        raise ValueError("Stage 5 gate failed: P50 cannot beat the validation baseline; inspect feature alignment before proceeding")
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, help="canonical parquet (inferred from cache when --features is used)")
    parser.add_argument("--features", type=Path, help="cached feature-table parquet")
    parser.add_argument("--out", type=Path, default=Path(S.MODEL_DIR))
    parser.add_argument("--baseline", type=Path, default=Path("results/baseline.json"))
    parser.add_argument("--n-jobs", type=int, default=-1)
    parser.add_argument("--patience", type=int, default=100, help="quantile validation early-stopping rounds")
    parser.add_argument("--target-mode", choices=("identity", "weekly_residual", "last_known_residual", "persistence_residual", "log_persistence_residual"), default="identity")
    parser.add_argument("--params", type=Path, help="JSON parameter overrides, e.g. Optuna best_params.json")
    args = parser.parse_args()
    if args.n_jobs == 0:
        parser.error("--n-jobs must be nonzero")
    if args.patience < 1:
        parser.error("--patience must be positive")
    frame, data_path = baseline.load_feature_table(args.data, args.features)
    overrides = json.loads(args.params.read_text()) if args.params else None
    train_models(frame, args.out, overrides, args.n_jobs, data_path, args.baseline, args.patience, args.target_mode)


if __name__ == "__main__":
    main()
