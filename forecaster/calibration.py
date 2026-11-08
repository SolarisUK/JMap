"""Causal rolling empirical tail expansion for a fixed demand forecaster.

This is prequential calibration: earlier completed out-of-sample targets may
calibrate later forecasts. It is not a formal implementation of adaptive
conformal inference. The 48-hour window and 48-row warmup are fixed in advance.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

import schemas as S

WINDOW_HOURS = 48
MIN_ROWS = 48
STEP = pd.Timedelta(days=1) / S.HALF_HOURS_PER_DAY
_QUANTILE_COLUMNS = ("q10", "q50", "q90")


def _utc(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("Calibration timestamps must be non-null and timezone-aware")
    return stamp.tz_convert("UTC").as_unit("ns")


def _times(series):
    if not isinstance(series.dtype, pd.DatetimeTZDtype) or series.isna().any():
        raise ValueError("Calibration timestamps must be non-null and timezone-aware")
    return series.dt.tz_convert("UTC").dt.as_unit("ns")


class Calibrator:
    def __init__(self, corpus, trained_until=None):
        """Load a dataframe/parquet of base forecasts and their observed targets.

        ``trained_until`` is the inclusive lower bound for eligible forecast
        origins, normally the validation-window start recorded by the trainer.
        The caller must supply predictions from the same fixed model being served.
        """
        data = pd.read_parquet(corpus) if isinstance(corpus, (str, Path)) else corpus.copy()
        stored = data.attrs.get("calibration", {})
        if trained_until is None:
            trained_until = stored.get("trained_until")
        if trained_until is None:
            raise ValueError("A model training boundary is required for calibration")
        self.trained_until = _utc(trained_until)
        if stored and _utc(stored["trained_until"]) != self.trained_until:
            raise ValueError("Calibration artifact has a different model training boundary")
        required = {"zone_id", "issue_time", "target_time", "h", "demand_mw", *_QUANTILE_COLUMNS}
        missing = required - set(data.columns)
        if missing:
            raise ValueError(f"Calibration corpus is missing columns: {sorted(missing)}")
        data["issue_time"] = _times(data.issue_time)
        data["target_time"] = _times(data.target_time)
        unknown = set(data.zone_id.unique()) - set(S.ZONE_ORDER)
        if unknown:
            raise ValueError(f"Unknown calibration zone IDs: {unknown}")
        if not data.h.between(1, S.FORECAST_HORIZON).all() or not (
            data.target_time == data.issue_time + (data.h - 1) * STEP
        ).all():
            raise ValueError("Calibration corpus has invalid horizon/target alignment")
        flags = (data.quality_flag.fillna(S.QF.MISSING).astype("uint8")
                 if "quality_flag" in data else pd.Series(S.QF.OK, index=data.index))
        eligible = ((data.issue_time >= self.trained_until)
                    & ((flags & S.QF_UNSCORABLE) == 0)
                    & np.isfinite(data.demand_mw.to_numpy(dtype=float, na_value=np.nan)))
        data = data.loc[eligible].copy()
        quantiles = data.loc[:, list(_QUANTILE_COLUMNS)].to_numpy(dtype=float)
        if not np.isfinite(quantiles).all():
            raise ValueError("Calibration base quantiles must be finite on eligible source rows")
        if (np.diff(quantiles, axis=1) < 0).any():
            raise ValueError("Calibration base quantiles must be ordered")
        self._rows = data.sort_values(["zone_id", "target_time", "issue_time"]).reset_index(drop=True)
        self._zones = {}
        for zone, group in self._rows.groupby("zone_id", observed=True):
            self._zones[zone] = {
                "target": pd.DatetimeIndex(group.target_time).as_unit("ns").asi8,
                "issue": pd.DatetimeIndex(group.issue_time).as_unit("ns").asi8,
                "lower_error": (group.demand_mw - group.q10).to_numpy(dtype=float),
                "upper_error": (group.demand_mw - group.q90).to_numpy(dtype=float),
            }

    def save(self, path):
        """Persist the eligible corpus and its fixed calibration rule."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self._rows.copy()
        data.attrs["calibration"] = {
            "method": "rolling_empirical_tail_expansion", "window_hours": WINDOW_HOURS,
            "minimum_rows": MIN_ROWS, "trained_until": self.trained_until.isoformat(),
        }
        data.to_parquet(path, index=False)

    @lru_cache(maxsize=8192)
    def _adjustment(self, zone, issue_ns):
        cutoff = issue_ns - STEP.value
        earliest = cutoff - pd.Timedelta(hours=WINDOW_HOURS).value
        group = self._zones.get(zone)
        lower, upper, count = 0.0, 0.0, 0
        first_target = last_target = last_issue = pd.NaT
        if group is not None:
            left = int(np.searchsorted(group["target"], earliest, side="left"))
            right = int(np.searchsorted(group["target"], cutoff, side="right"))
            count = right - left
            if count:
                first_target = pd.Timestamp(int(group["target"][left]), tz="UTC")
                last_target = pd.Timestamp(int(group["target"][right - 1]), tz="UTC")
                last_issue = pd.Timestamp(int(group["issue"][left:right].max()), tz="UTC")
            if count >= MIN_ROWS:
                lower = min(0.0, float(np.quantile(group["lower_error"][left:right], S.QUANTILES[0])))
                upper = max(0.0, float(np.quantile(group["upper_error"][left:right], S.QUANTILES[2])))
        return {
            "calibration_rows": count, "calibration_active": count >= MIN_ROWS,
            "calibration_lower_mw": lower, "calibration_upper_mw": upper,
            "calibration_source_target_time_min": first_target,
            "calibration_source_target_time_max": last_target,
            "calibration_source_issue_time_max": last_issue,
            "calibration_cutoff": pd.Timestamp(cutoff, tz="UTC"),
            "calibration_trained_until": self.trained_until,
        }

    def apply(self, rows, basequantiles, *, return_provenance=False):
        """Expand P10/P90 using only targets completed before each row's issue."""
        values = np.asarray(basequantiles, dtype=float)
        if values.shape != (len(rows), len(S.QUANTILES)):
            raise ValueError("Base quantiles must have shape (forecast rows, 3)")
        if not np.isfinite(values).all() or (np.diff(values, axis=1) < 0).any():
            raise ValueError("Base quantiles must be finite and ordered")
        issues = _times(rows.issue_time)
        zones = rows.zone_id.astype(object).to_numpy()
        if any(zone not in S.ZONE_INDEX for zone in zones):
            raise ValueError("Unknown zone ID in calibration request")
        result = values.copy()
        provenance = []
        for i, (zone, issue_ns) in enumerate(zip(zones, pd.DatetimeIndex(issues).asi8)):
            adjustment = self._adjustment(zone, int(issue_ns))
            result[i, 0] += adjustment["calibration_lower_mw"]
            result[i, 2] += adjustment["calibration_upper_mw"]
            if return_provenance:
                provenance.append(adjustment)
        if not return_provenance:
            return result
        detail = pd.DataFrame(provenance, index=rows.index)
        for column in detail:
            if "_time_" in column or column in ("calibration_cutoff", "calibration_trained_until"):
                detail[column] = pd.to_datetime(detail[column], utc=True)
        return result, detail
