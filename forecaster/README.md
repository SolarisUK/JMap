# JMap forecaster · Solaris

Code-only handoff for ten GB zones, 48 half-hour horizons and P10/P50/P90 demand forecasts. `train.py` defines the global LightGBM quantile models; `forecast.py` exposes `predict()` and `predict_all()`. `features.py`, `hybrid.py` and `calibration.py` implement the features, validation-selected routing and interval calibration. `schemas.py` v1.1.0 fixes names, ordering and shapes.

**No data, parquet files, fitted model weights or caches are included.** The JSON files contain frozen recipes, feature names and the accepted real-validation routing policy. `forecast_cache.py` is source code, not a prediction cache. Inference through `forecast.py` requires separately supplied trained model and calibration artifacts; the generated candidate directories are not automatically assembled into a serving model directory.

## Run the real-data evaluation

Use Python 3.12+ and `uv`. Work from this folder and supply the schema-compatible real dataset separately at `data/canonical/real.parquet`.

```sh
cd forecaster
uv sync --frozen
export EUGENE_FORECAST_DATA="$PWD/data/canonical/real.parquet"

uv run --no-sync python real_evaluation.py self-test
uv run --no-sync python real_phase2.py self-test
uv run --no-sync python real_walkforward.py self-test

uv run --no-sync python real_evaluation.py prepare
uv run --no-sync python real_evaluation.py fit
uv run --no-sync python real_evaluation.py select
uv run --no-sync python real_evaluation.py score --test-cadence-minutes 30
uv run --no-sync python real_phase2.py calibrate
```

The explicit 30-minute test cadence reproduces the full test cohort and bypasses the original run's dated automatic deadline rule. No training or evaluation runs just by extracting this archive.

The chronological split is:

| Partition | UTC dates, inclusive |
|---|---|
| Train | 7 March 2024–31 March 2025 |
| Validation | 1 April–30 June 2025 |
| Test | 1 July–31 December 2025 |

Training and validation targets crossing the next boundary are purged. Development issues use the frozen two-hour cadence. Real validation selects between persistence and two learned candidate families per horizon; the accepted route is persistence at h1–2 and LightGBM at h3–48. Model parameters and features are frozen.

`real_phase2.py` rolls the existing 48-hour calibration window through test, requiring at least 48 source rows. Only outcomes with `target_time <= issue_time - 30 minutes` enter the adjustment. P50, model weights and routing remain unchanged; only P10/P90 change. The saved audit checks source cutoffs.

Outputs are generated under `artifacts/real_once_20261108/` and `artifacts/real_phase2_20261108/`. Exclusive marker files prevent accidental repeated scoring. Use a fresh output workspace for an intentional reproduction; do not remove one-shot guards to tune against test results.

## Recorded real-data results

| Metric | Hybrid | Persistence | Weekly lag |
|---|---:|---:|---:|
| National P50 MAPE | **4.15%** | 7.37% | 7.80% |
| Overall P50 MAE, MW pooled over zones | **107.0** | 189.5 | 201.3 |

Final causal P10–P90 coverage: **78.66%**, nominal target 80%. Test cohort: **8,785** complete half-hourly issue times, ten zones and 48 horizons each. National MAPE sums the ten zones before computing percentage error. Zonal demand is estimated from national demand, so zone errors largely track national error.

## Optional walk-forward check

Run after causal calibration completes:

```sh
uv run --no-sync python real_walkforward.py prepare
uv run --no-sync python real_walkforward.py fit
uv run --no-sync python real_walkforward.py score
```

Each origin uses expanding history and the preceding three calendar months for validation. The identical July fit is reused. Windows are defined by issue time.

| Retrain origin | Issue window | Hybrid MAE, MW | Persistence MAE, MW | Issue times |
|---|---|---:|---:|---:|
| 1 July 2025 | July–August | 104.97 | 176.85 | 2,976 |
| 1 September 2025 | September–October | 102.11 | 201.23 | 2,928 |
| 1 November 2025 | November–December | 114.95 | 190.54 | 2,881 |
