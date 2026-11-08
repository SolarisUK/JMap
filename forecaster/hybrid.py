"""Validation-selected horizon routing between persistence and fitted models.

Selection receives validation rows from the caller's isolated development split.
Inference uses the frozen routing profile and causal persistence metadata only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import baseline
import schemas as S


def _validate_model_map(model_by_horizon, available=None):
    expected = {str(h) for h in range(1, S.FORECAST_HORIZON + 1)}
    if not isinstance(model_by_horizon, dict) or set(model_by_horizon) != expected:
        raise ValueError(f"Model routing must contain exactly horizons 1..{S.FORECAST_HORIZON}")
    for horizon, name in model_by_horizon.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Invalid model name at horizon {horizon}")
        if available is not None and name not in available:
            raise ValueError(f"Unknown model {name!r} at horizon {horizon}")


def validate_profile(profile):
    """Reject incomplete or ambiguous routing before forecasting any horizon."""
    expected = {str(h) for h in range(1, S.FORECAST_HORIZON + 1)}
    if not isinstance(profile, dict) or profile.get("selection_split") != "validation":
        raise ValueError("Hybrid profile must identify validation-only selection")
    choices = profile.get("horizons")
    if not isinstance(choices, dict) or set(choices) != expected:
        raise ValueError(f"Hybrid profile must contain exactly horizons 1..{S.FORECAST_HORIZON}")
    for horizon, choice in choices.items():
        if not isinstance(choice, dict) or choice.get("source") not in ("persistence", "model"):
            raise ValueError(f"Invalid hybrid source at horizon {horizon}")
    if "model_by_horizon" in profile:
        _validate_model_map(profile["model_by_horizon"])
    return profile


def _horizons(rows):
    if not pd.api.types.is_numeric_dtype(rows.h.dtype) or pd.api.types.is_bool_dtype(rows.h.dtype):
        raise ValueError("Hybrid horizons must be numeric integers")
    values = rows.h.to_numpy(dtype=float, na_value=np.nan)
    valid = (np.isfinite(values) & (values == np.floor(values))
             & (values >= 1) & (values <= S.FORECAST_HORIZON))
    if not valid.all():
        raise ValueError(f"Hybrid horizons must be integers from 1 to {S.FORECAST_HORIZON}")
    return values.astype(int)


def _quantiles(rows, values):
    result = np.asarray(values, dtype=float)
    if result.shape != (len(rows), len(S.QUANTILES)):
        raise ValueError("Hybrid quantiles must have one row of three predictions per input row")
    if not np.isfinite(result).all() or (np.diff(result, axis=1) < 0).any():
        raise ValueError("Hybrid model quantiles must be finite and ordered")
    return result


def _model_predictions(rows, predictions):
    if not isinstance(predictions, dict) or not predictions:
        raise ValueError("At least one named model prediction is required")
    result = {}
    for name, values in predictions.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Model prediction names must be nonempty strings")
        result[name] = _quantiles(rows, values)
    return result


def route_models(rows, predictions, model_by_horizon):
    """Stitch frozen model intervals by horizon without accessing target labels."""
    values = _model_predictions(rows, predictions)
    _validate_model_map(model_by_horizon, available=values)
    horizons = _horizons(rows)
    route = np.asarray([model_by_horizon[str(h)]
                        for h in range(1, S.FORECAST_HORIZON + 1)], dtype=object)
    names = route[horizons - 1]
    result = np.empty((len(rows), len(S.QUANTILES)), dtype=float)
    for name, quantiles in values.items():
        mask = names == name
        result[mask] = quantiles[mask]
    return result


def select_models(rows, predictions, persistence_reference):
    """Select a frozen learned model per horizon on the common validation cohort.

    Equal MAEs keep prediction-dictionary insertion order. The reference defines
    the same eligible rows used by subsequent persistence/model selection.
    """
    values = _model_predictions(rows, predictions)
    horizons = _horizons(rows)
    reference = np.asarray(persistence_reference, dtype=float)
    if reference.shape != (len(rows),):
        raise ValueError("Persistence reference must have one value per validation row")
    common = np.asarray(baseline._scoring_mask(rows), dtype=bool) & np.isfinite(reference)
    observed = rows.demand_mw.to_numpy(dtype=float)
    model_by_horizon = {}
    for horizon in range(1, S.FORECAST_HORIZON + 1):
        mask = common & (horizons == horizon)
        if not mask.any():
            raise ValueError(f"No common validation rows at horizon {horizon}")
        model_by_horizon[str(horizon)] = min(
            values, key=lambda name: np.abs(observed[mask] - values[name][mask, 1]).mean())
    return model_by_horizon, route_models(rows, values, model_by_horizon)


def select_horizons(rows, model_quantiles, persistence_reference):
    """Freeze the lower-MAE source per horizon on identical validation rows.

    Ties select persistence. Missing references and quality exclusions remove the
    row from both comparisons, never from just one side of the selection.
    """
    values = _quantiles(rows, model_quantiles)
    horizons = _horizons(rows)
    reference = np.asarray(persistence_reference, dtype=float)
    if reference.shape != (len(rows),):
        raise ValueError("Persistence reference must have one value per validation row")
    common = np.asarray(baseline._scoring_mask(rows), dtype=bool) & np.isfinite(reference)
    observed = rows.demand_mw.to_numpy(dtype=float)
    choices = {}
    for horizon in range(1, S.FORECAST_HORIZON + 1):
        mask = common & (horizons == horizon)
        if not mask.any():
            raise ValueError(f"No common validation rows at horizon {horizon}")
        model_mae = float(np.abs(observed[mask] - values[mask, 1]).mean())
        persistence_mae = float(np.abs(observed[mask] - reference[mask]).mean())
        choices[str(horizon)] = {
            "source": "persistence" if persistence_mae <= model_mae else "model",
            "model_mae_mw": model_mae,
            "persistence_mae_mw": persistence_mae,
            "rows": int(mask.sum()),
        }
    profile = {
        "selection_split": "validation",
        "selection_rule": "lowest validation MAE per horizon; ties choose persistence",
        "missing_persistence_fallback": "model",
        "comparison_rows": int(common.sum()),
        "horizons": choices,
    }
    return validate_profile(profile)


def apply_hybrid(rows, ordered_model_quantiles, profile):
    """Route medians without labels and keep model interval widths around them."""
    validate_profile(profile)
    values = _quantiles(rows, ordered_model_quantiles)
    horizons = _horizons(rows)
    if "_persistence_offset_mw" not in rows:
        raise ValueError("Hybrid inference requires causal persistence metadata")
    reference = rows._persistence_offset_mw.to_numpy(dtype=float, na_value=np.nan)
    route = np.asarray([profile["horizons"][str(h)]["source"] == "persistence"
                        for h in range(1, S.FORECAST_HORIZON + 1)])
    use_persistence = route[horizons - 1] & np.isfinite(reference)
    median = np.where(use_persistence, reference, values[:, 1])
    with np.errstate(over="ignore", invalid="ignore"):
        result = values + (median - values[:, 1])[:, None]
    # Preserve the selected value exactly rather than through subtraction/addition.
    result[:, 1] = median
    if not np.isfinite(result).all() or (np.diff(result, axis=1) < 0).any():
        raise ValueError("Hybrid interval recentering produced nonfinite or crossed quantiles")
    return result
