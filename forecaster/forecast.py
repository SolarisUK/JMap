"""Public MW forecast interface. Boosters/history/calibration load once per process."""

from __future__ import annotations

from datetime import datetime as _datetime
from functools import lru_cache as _lru_cache
import hashlib as _hashlib
import json as _json
import os as _os
from pathlib import Path as _Path

import lightgbm as _lgb
import numpy as _np

import features as _features
import forecast_cache as _forecast_cache
import schemas as _S
from calibration import Calibrator as _Calibrator

__all__ = ("predict", "predict_all")
_ROOT = _Path(__file__).resolve().parent
_DIR = _Path(_os.environ.get("EUGENE_MODEL_DIR", str(_ROOT / _S.MODEL_DIR)))
_CONFIG = _json.loads((_DIR / "training_config.json").read_text())
_NAMES = _json.loads((_DIR / "feature_names.json").read_text())
if _NAMES != _features.model_feature_names(_CONFIG):
    raise ValueError("Forecast feature order differs from saved training order")
if _CONFIG.get("target_mode", "identity") not in ("identity", "weekly_residual", "last_known_residual", "persistence_residual", "log_persistence_residual"):
    raise ValueError("Unknown saved model target transform")
_BOOSTERS = tuple(_lgb.Booster(model_file=str(_DIR / f"lgbm_q{round(q * 100)}.txt")) for q in _S.QUANTILES)
_PREDICTORS = {_CONFIG.get("base_model_name", "model"): (_BOOSTERS, _CONFIG)}
for _model_name, _relative_dir in _CONFIG.get("hybrid_models", {}).items():
    if _relative_dir == ".":
        continue
    _model_dir = _DIR / _relative_dir
    _model_config = _json.loads((_model_dir / "training_config.json").read_text())
    if _json.loads((_model_dir / "feature_names.json").read_text()) != _features.model_feature_names(_model_config):
        raise ValueError("Hybrid component feature order differs from its saved contract")
    _PREDICTORS[_model_name] = (
        tuple(_lgb.Booster(model_file=str(_model_dir / f"lgbm_q{round(q * 100)}.txt")) for q in _S.QUANTILES),
        _model_config)
_CALIBRATION_INFO = _json.loads((_DIR / "calibration_manifest.json").read_text())
for _name, _expected in _CALIBRATION_INFO["model_fingerprints"].items():
    if _hashlib.sha256((_DIR / _name).read_bytes()).hexdigest() != _expected:
        raise ValueError("Calibration is stale after a model change; rerun evaluate.py")
_DATA_PATH = _Path(_CONFIG["data_path"])
if not _DATA_PATH.exists():
    _DATA_PATH = _ROOT / _S.CANONICAL_PATH / _DATA_PATH.name
_TRAINING_DATA_PATH = _DATA_PATH.resolve()
_DATA_PATH = _Path(_os.environ.get("EUGENE_FORECAST_DATA", str(_DATA_PATH)))
_DATA_CUTOFF = (_CONFIG["split_info"]["test_start"]
                if _CONFIG.get("evaluation_scope") == "validation_only" and _DATA_PATH.resolve() == _TRAINING_DATA_PATH else None)
_DATA = _features.load(_DATA_PATH, before=_DATA_CUTOFF)
_HYBRID = None
if _CONFIG.get("hybrid_policy"):
    import hybrid as _hybrid
    _HYBRID = _json.loads((_DIR / _CONFIG["hybrid_policy"]).read_text())
    _hybrid.validate_profile(_HYBRID)
if set(_DATA.zone_id.unique()) != set(_S.ZONE_ORDER):
    raise ValueError("Forecasting all zones requires canonical history for every schema zone")
_CALIBRATOR = _Calibrator(_DIR / "calibration.parquet", _CALIBRATION_INFO["trained_until"])
_hash = _hashlib.sha256()
for _path in (*(_DIR / f"lgbm_q{round(q * 100)}.txt" for q in _S.QUANTILES),
              _DIR / "feature_names.json", _DIR / "training_config.json",
              _DIR / "calibration_manifest.json", _DIR / "calibration.parquet", _DATA_PATH,
              *(_ROOT / name for name in ("features.py", "calibration.py", "forecast.py", "forecast_cache.py", "schemas.py", "uv.lock"))):
    _hash.update(_path.read_bytes())
if _HYBRID is not None:
    _hash.update((_DIR / _CONFIG["hybrid_policy"]).read_bytes())
    _hash.update((_ROOT / "hybrid.py").read_bytes())
    for _relative_dir in _CONFIG.get("hybrid_models", {}).values():
        if _relative_dir != ".":
            for _name in ("training_config.json", "feature_names.json", "lgbm_q10.txt", "lgbm_q50.txt", "lgbm_q90.txt"):
                _hash.update((_DIR / _relative_dir / _name).read_bytes())
_FINGERPRINT = _hash.hexdigest()
_DISK_CACHE, _CACHE_INDEX = _forecast_cache.load_cache(
    _DIR, _FINGERPRINT, [stamp.isoformat() for stamp in sorted(_DATA.timestamp_utc.unique())])


def _predict_rows(rows, num_threads=1):
    predictions = {name: _features.predict_quantiles(models, rows, config, threads=num_threads)
                   for name, (models, config) in _PREDICTORS.items()}
    base = predictions[_CONFIG.get("base_model_name", "model")]
    if _HYBRID is not None:
        if "model_by_horizon" in _HYBRID:
            base = _hybrid.route_models(rows, predictions, _HYBRID["model_by_horizon"])
        base = _hybrid.apply_hybrid(rows, base, _HYBRID)
    result = _CALIBRATOR.apply(rows, base)
    if not _np.isfinite(result).all():
        raise ValueError("Forecaster produced nonfinite MW values")
    return result


@_lru_cache(maxsize=2048)
def _for_time(issue_iso):
    if _DATA_CUTOFF is not None and _features._issue_time(issue_iso) + (_S.FORECAST_HORIZON - 1) * _features.STEP >= _features._issue_time(_DATA_CUTOFF):
        raise ValueError("Forecast would enter the reserved test period")
    if issue_iso in _CACHE_INDEX:
        return _DISK_CACHE[_CACHE_INDEX[issue_iso]]
    rows = _features.for_issue(None, issue_iso, data=_DATA)
    result = _predict_rows(rows).reshape(_S.N_ZONES, _S.FORECAST_HORIZON, len(_S.QUANTILES))
    result.setflags(write=False)
    return result


def predict(zone_id: str, issue_time_utc: _datetime) -> list[list[float]]:
    """48 MW rows of [P10, P50, P90], starting at issue_time_utc."""
    if zone_id not in _S.ZONE_INDEX:
        raise ValueError(f"Unknown zone_id {zone_id!r}")
    issue = _features._issue_time(issue_time_utc)
    return _for_time(issue.isoformat())[_S.ZONE_INDEX[zone_id]].tolist()


def predict_all(issue_time_utc: _datetime) -> list[list[list[float]]]:
    """N_ZONES × 48 × 3 MW values, in schemas.ZONE_ORDER order."""
    issue = _features._issue_time(issue_time_utc)
    return _for_time(issue.isoformat()).tolist()
