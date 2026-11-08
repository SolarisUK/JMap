"""Direct multi-horizon features with explicit demand and weather provenance."""

from __future__ import annotations

import argparse
from pathlib import Path

import holidays
import numpy as np
import pandas as pd

import schemas as S

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = ROOT / S.CANONICAL_PATH / "_fake.parquet"
STEP = pd.Timedelta(days=1) / S.HALF_HOURS_PER_DAY
LAGS = {"lag_1d": 1, "lag_2d": 2, "lag_1w": 7, "lag_2w": 14}
FEATURE_NAMES = [
    *LAGS, "same_hh_mean_3w", "last_known", "last_known_2", "last_known_3",
    "roll_mean_2h", "roll_mean_24h", "roll_std_24h", "roll_mean_7d", "recent_vs_week",
    "hh_of_day", "dow", "is_weekend", "month", "is_bank_holiday", "is_dst_change_day",
    "tod_sin", "tod_cos", "doy_sin", "doy_cos", "temp_c", "wind_ms", "solar_wm2",
    "hdd", "cdd", "temp_roll_24h", "temp_delta_24h", "h", "zone_id",
]


def load(path=DEFAULT_DATA, *, before=None):
    filters = [("timestamp_utc", "<", pd.Timestamp(before))] if before is not None else None
    data = pd.read_parquet(path, filters=filters)
    return _prepare(data)


def _prepare(data):
    S.validate_canonical_columns(data.columns)
    data = data.loc[:, list(S.CANONICAL_COLUMNS)].copy()
    unknown = set(data.zone_id.unique()) - set(S.ZONE_ORDER)
    if unknown:
        raise ValueError(f"Unknown zone IDs: {unknown}")
    for name in ("timestamp_utc", "weather_issue_time_utc"):
        if not isinstance(data[name].dtype, pd.DatetimeTZDtype):
            raise ValueError(f"{name} must be timezone-aware")
        data[name] = data[name].dt.tz_convert("UTC")
    if data.timestamp_utc.isna().any() or (data.timestamp_utc != data.timestamp_utc.dt.floor("30min")).any():
        raise ValueError("timestamp_utc must contain non-null half-hour interval starts")
    if data.duplicated(["zone_id", "timestamp_utc"]).any():
        raise ValueError("Canonical rows must be unique by zone_id and timestamp_utc")
    if data.empty:
        raise ValueError("Canonical history is empty")
    return data.sort_values(["zone_id", "timestamp_utc"]).reset_index(drop=True)


def _issue_time(value):
    issue = pd.Timestamp(value)
    if issue.tzinfo is None:
        raise ValueError("issue_time must be timezone-aware")
    issue = issue.tz_convert("UTC")
    if issue != issue.floor("30min"):
        raise ValueError("issue_time must be aligned to a half-hour")
    return issue


def _source_time(times, present):
    return pd.to_datetime(np.where(present, pd.DatetimeIndex(times).as_unit("ns").asi8, pd.NaT.value), utc=True)


def _zone_rows(group, issues):
    zone = group.zone_id.iloc[0]
    group = group.set_index("timestamp_utc").sort_index()
    # A missing interval remains missing; row positions never stand in for timestamps.
    index = pd.date_range(group.index.min(), group.index.max(), freq=STEP, tz="UTC")
    group = group.reindex(index)
    n = len(issues) * S.FORECAST_HORIZON
    issue = pd.DatetimeIndex(np.repeat(pd.DatetimeIndex(issues).as_unit("ns").asi8, S.FORECAST_HORIZON), tz="UTC")
    h = np.tile(np.arange(1, S.FORECAST_HORIZON + 1), len(issues))
    target = issue + (h - 1) * STEP
    out = pd.DataFrame({"zone_id": zone, "issue_time": issue, "h": h, "target_time": target})

    def take(column, times):
        return group[column].reindex(times).to_numpy()

    def demand_feature(name, times, values=None):
        values = take("demand_mw", times) if values is None else values
        out[name] = values
        out[f"{name}_source_time"] = _source_time(times, pd.notna(values))

    for name, days in LAGS.items():
        demand_feature(name, target - pd.Timedelta(days=days))
    third_week = take("demand_mw", target - pd.Timedelta(days=21))
    mean_3w = np.mean(np.column_stack([out.lag_1w, out.lag_2w, third_week]), axis=1)
    demand_feature("same_hh_mean_3w", target - pd.Timedelta(days=7), mean_3w)
    for steps, name in enumerate(("last_known", "last_known_2", "last_known_3"), start=1):
        demand_feature(name, issue - steps * STEP)

    # Private target-transform metadata; the specified booster inputs stay unchanged.
    demand_feature("_issue_week_anchor", issue - STEP - pd.Timedelta(days=7))
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        scaled_week = out.lag_1w * out.last_known / out._issue_week_anchor.replace(0, np.nan)
    valid_reference = np.isfinite(out[["lag_1w", "last_known", "_issue_week_anchor"]]).all(axis=1)
    scaled_week = scaled_week.where(valid_reference & np.isfinite(scaled_week))
    demand_feature("_persistence_offset_mw", issue - STEP, scaled_week.to_numpy())
    valid_ratio = np.isfinite(out.last_known) & np.isfinite(out._issue_week_anchor) & (out.last_known > 0) & (out._issue_week_anchor > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        log_ratio = np.log(out.last_known / out._issue_week_anchor)
    demand_feature("log_recent_ratio", issue - STEP, log_ratio.where(valid_ratio & np.isfinite(log_ratio)).to_numpy())

    demand = group["demand_mw"]
    for name, window, operation in (("roll_mean_2h", 4, "mean"),
                                    ("roll_mean_24h", 48, "mean"),
                                    ("roll_std_24h", 48, "std"),
                                    ("roll_mean_7d", 336, "mean")):
        rolling = getattr(demand.rolling(window, min_periods=1), operation)()
        values = rolling.reindex(issue - STEP).to_numpy()
        demand_feature(name, issue - STEP, values)
    ratio = out.roll_mean_24h / out.roll_mean_7d.replace(0, np.nan)
    demand_feature("recent_vs_week", issue - STEP, ratio.to_numpy())

    local = target.tz_convert(S.DISPLAY_TZ)
    hh = local.hour * 2 + local.minute // 30
    out["hh_of_day"], out["dow"], out["month"] = hh, local.day_of_week, local.month
    out["is_weekend"] = local.day_of_week >= 5
    gb_holidays = holidays.country_holidays("GB", years=sorted(set(local.year)))
    out["is_bank_holiday"] = [date in gb_holidays for date in local.date]
    flags = group.quality_flag.reindex(target).fillna(0).astype("uint8").to_numpy()
    out["is_dst_change_day"] = (flags & S.QF.DST_BOUNDARY) != 0
    out["tod_sin"], out["tod_cos"] = np.sin(2 * np.pi * hh / 48), np.cos(2 * np.pi * hh / 48)
    out["doy_sin"] = np.sin(2 * np.pi * local.day_of_year / 365)
    out["doy_cos"] = np.cos(2 * np.pi * local.day_of_year / 365)

    # Weather is usable only when its forecast vintage was available at this issue.
    vintages = pd.DatetimeIndex(group.weather_issue_time_utc.reindex(target))
    eligible = vintages.notna() & (vintages <= issue)
    for name in ("temp_c", "wind_ms", "solar_wm2"):
        values = take(name, target).astype(float)
        good = eligible & np.isfinite(values)
        out[name] = np.where(good, values, np.nan)
        out[f"{name}_source_issue_time"] = _source_time(vintages, good)
    out["hdd"] = np.maximum(0, 15.5 - out.temp_c)
    out["cdd"] = np.maximum(0, out.temp_c - 20)
    for name in ("hdd", "cdd"):
        out[f"{name}_source_issue_time"] = out.temp_c_source_issue_time

    # Gather the entire thermal-history window before masking by each row's issue time.
    positions = group.index.get_indexer(target)
    offsets = np.arange(S.HALF_HOURS_PER_DAY)
    windows = positions[:, None] - offsets[None, :]
    in_range = (positions[:, None] >= 0) & (windows >= 0)
    clipped = np.clip(windows, 0, len(group) - 1)
    weather_times = pd.DatetimeIndex(group.weather_issue_time_utc).as_unit("ns").asi8
    window_vintages = weather_times[clipped]
    temperatures = group.temp_c.to_numpy(dtype=float)[clipped]
    good = in_range & (window_vintages != pd.NaT.value) & (window_vintages <= issue.asi8[:, None]) & np.isfinite(temperatures)
    complete = good.all(axis=1)
    out["temp_roll_24h"] = np.where(complete, np.mean(temperatures, axis=1), np.nan)
    out["temp_roll_24h_source_issue_time"] = pd.to_datetime(
        np.where(complete, window_vintages.max(axis=1), pd.NaT.value), utc=True)
    old_time = target - pd.Timedelta(days=1)
    old_vintage = pd.DatetimeIndex(group.weather_issue_time_utc.reindex(old_time))
    old_temp = take("temp_c", old_time).astype(float)
    good_delta = eligible & old_vintage.notna() & (old_vintage <= issue) & np.isfinite(old_temp) & out.temp_c.notna().to_numpy()
    out["temp_delta_24h"] = np.where(good_delta, out.temp_c - old_temp, np.nan)
    out["temp_delta_24h_source_issue_time"] = pd.to_datetime(
        np.where(good_delta, np.maximum(vintages.as_unit("ns").asi8, old_vintage.as_unit("ns").asi8), pd.NaT.value), utc=True)
    weather_cols = [c for c in out if c.endswith("_source_issue_time")]
    out["weather_source_issue_time"] = out[weather_cols].max(axis=1)
    out["demand_mw"] = take("demand_mw", target)
    out["quality_flag"] = flags
    assert len(out) == n
    return out


def _build_rows(data, issues, zone_id=None):
    if zone_id is not None and zone_id not in S.ZONE_INDEX:
        raise ValueError(f"Unknown zone_id {zone_id!r}")
    zones = S.ZONE_ORDER if zone_id is None else (zone_id,)
    frames = []
    for zone in zones:
        group = data.loc[data.zone_id == zone]
        if group.empty:
            if zone_id is not None:
                raise ValueError(f"No canonical history for {zone}")
            continue
        frames.append(_zone_rows(group, issues))
    result = pd.concat(frames, ignore_index=True)
    result["zone_id"] = pd.Categorical(result.zone_id, categories=S.ZONE_ORDER)
    return result


def for_issue(zone_id, issue_time, data=None):
    """Inference rows include all horizons, even when future targets are unscorable/absent."""
    issue = _issue_time(issue_time)
    data = load() if data is None else _prepare(data)
    return _build_rows(data, [issue], zone_id)


def build(path=DEFAULT_DATA, dense=False, recent_dense=False):
    data = load(path)
    times = pd.DatetimeIndex(data.timestamp_utc.unique()).sort_values()
    # A complete forecast window must lie in the supplied target history.
    end = times.max() - (S.FORECAST_HORIZON - 1) * STEP
    hours = 2 if dense else 6
    selected = (times.minute == 0) & (times.hour % hours == 0)
    if recent_dense:
        selected |= times >= times.max() - pd.Timedelta(days=60)
    issues = times[selected & (times <= end)]
    rows = _build_rows(data, issues)
    scorable = ((rows.quality_flag & S.QF_UNSCORABLE) == 0) & rows.demand_mw.notna()
    rows = rows.loc[scorable].reset_index(drop=True)
    rows.attrs["data_path"] = str(Path(path).resolve())
    check_no_leakage(rows)
    return rows


def demand_offset(rows, zone_intercepts_mw, priority=None):
    """Finite weekly/daily/latest-demand offset, then a saved training-only zone median.

    Intercepts are fitted by the training caller and persisted with the boosters;
    this helper never reads target labels or recomputes an intercept from history.
    """
    priority = tuple(priority or ("lag_1w", "lag_1d", "last_known", "zone_intercepts_mw"))
    if len(priority) != 4 or priority[-1] != "zone_intercepts_mw" or set(priority[:-1]) != {"lag_1w", "lag_1d", "last_known"}:
        raise ValueError("Demand offset must use only the three causal references and training intercepts")
    zones = rows["zone_id"].astype(object)
    intercepts = {}
    for zone in pd.unique(zones):
        if zone not in S.ZONE_INDEX:
            raise ValueError(f"Unknown zone_id {zone!r} in demand offset")
        try:
            value = float(zone_intercepts_mw[zone])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Missing or invalid training intercept for {zone}") from error
        if not np.isfinite(value):
            raise ValueError(f"Training intercept for {zone} must be finite")
        intercepts[zone] = value
    offset = zones.map(intercepts).to_numpy(dtype=float)
    # Higher-priority finite sources overwrite the fallback; zero is a valid demand.
    for name in reversed(priority[:-1]):
        values = rows[name].to_numpy(dtype=float, na_value=np.nan)
        offset = np.where(np.isfinite(values), values, offset)
    return pd.Series(offset, index=rows.index, name="demand_offset_mw", dtype="float64")


def model_offset(rows, config):
    """Inverse target transform shared by fitting, evaluation and serving."""
    mode = config.get("target_mode", "identity")
    if mode == "identity":
        return pd.Series(0.0, index=rows.index, dtype="float64")
    if mode not in ("weekly_residual", "last_known_residual", "persistence_residual", "log_persistence_residual"):
        raise ValueError(f"Unknown saved target transform: {mode}")
    default = (["last_known", "lag_1d", "lag_1w", "zone_intercepts_mw"]
               if mode in ("last_known_residual", "persistence_residual", "log_persistence_residual") else
               ["lag_1w", "lag_1d", "last_known", "zone_intercepts_mw"])
    fallback_rows = rows
    if mode == "log_persistence_residual":
        fallback_rows = rows.assign(**{name: rows[name].where(rows[name] > 0) for name in default[:-1]})
    offset = demand_offset(fallback_rows, config["zone_intercepts_mw"], config.get("offset_priority", default))
    if mode in ("persistence_residual", "log_persistence_residual"):
        values = rows["_persistence_offset_mw"].to_numpy(dtype=float)
        usable = np.isfinite(values) & ((values > 0) if mode == "log_persistence_residual" else True)
        offset = pd.Series(np.where(usable, values, offset), index=rows.index, dtype="float64")
    if mode == "log_persistence_residual" and (offset <= 0).any():
        raise ValueError("Relative forecasts require positive saved training intercepts")
    return offset


def model_feature_names(config):
    """Old boosters retain their exact input contract; relative mode adds one causal ratio."""
    return [*FEATURE_NAMES, "log_recent_ratio"] if config.get("target_mode") == "log_persistence_residual" else list(FEATURE_NAMES)


def restore_prediction(raw, rows, config):
    """Invert a saved target transform identically in training, evaluation and serving."""
    offset = model_offset(rows, config).to_numpy()
    raw = np.asarray(raw, dtype=float)
    if config.get("target_mode") == "log_persistence_residual":
        with np.errstate(over="raise", invalid="raise"):
            return offset * np.exp(raw)
    return raw + offset


def predict_quantiles(models, rows, config, *, threads=1):
    names = model_feature_names(config)
    return np.sort(np.column_stack([
        restore_prediction(model.predict(rows[names], num_threads=threads), rows, config)
        for model in models]), axis=1)


def check_no_leakage(df):
    """Assert source cutoffs and forecast row alignment, naming the offending row."""
    if not pd.api.types.is_numeric_dtype(df.h.dtype) or pd.api.types.is_bool_dtype(df.h.dtype):
        raise AssertionError(f"horizon must contain integers from 1 to {S.FORECAST_HORIZON} half-hours")
    horizons = df.h.to_numpy(dtype=float, na_value=np.nan)
    bad = ~np.isfinite(horizons) | (horizons != np.floor(horizons)) | (horizons < 1) | (horizons > S.FORECAST_HORIZON)
    if bad.any():
        raise AssertionError(f"horizon alignment leak: {df.loc[bad].iloc[0].to_dict()}")
    cutoff = df.issue_time - STEP
    expected = df.issue_time + (df.h - 1) * STEP
    bad = df.target_time != expected
    if bad.any():
        raise AssertionError(f"target alignment leak: {df.loc[bad].iloc[0].to_dict()}")
    demand_names = FEATURE_NAMES[:FEATURE_NAMES.index("hh_of_day")]
    if "_persistence_offset_mw" in df:
        demand_names = [*demand_names, "_issue_week_anchor", "_persistence_offset_mw"]
    if "log_recent_ratio" in df:
        demand_names = [*demand_names, "log_recent_ratio"]
    weather_names = ("temp_c", "wind_ms", "solar_wm2", "hdd", "cdd", "temp_roll_24h", "temp_delta_24h")
    sources = {**{name: f"{name}_source_time" for name in demand_names},
               **{name: f"{name}_source_issue_time" for name in weather_names}}
    for feature, source in sources.items():
        if source not in df:
            raise AssertionError(f"Missing source provenance column {source}")
        bad = np.isfinite(df[feature].to_numpy(dtype=float)) & df[source].isna()
        if bad.any():
            raise AssertionError(f"Missing source provenance in {source}: {df.loc[bad].iloc[0].to_dict()}")
    if "weather_source_issue_time" not in df:
        raise AssertionError("Missing source provenance column weather_source_issue_time")
    bad = np.isfinite(df[list(weather_names)].to_numpy(dtype=float)).any(axis=1) & df.weather_source_issue_time.isna()
    if bad.any():
        raise AssertionError(f"Missing source provenance in weather_source_issue_time: {df.loc[bad].iloc[0].to_dict()}")
    for name in df:
        if not df[name].notna().any():
            continue
        if name.endswith("_source_time"):
            bad = df[name].notna() & (df[name] > cutoff)
        elif name.endswith("_source_issue_time"):
            bad = df[name].notna() & (df[name] > df.issue_time)
        else:
            continue
        if bad.any():
            raise AssertionError(f"source leakage in {name}: {df.loc[bad].iloc[0].to_dict()}")
    for name, days in LAGS.items():
        source = df[f"{name}_source_time"]
        bad = source.notna() & (source != df.target_time - pd.Timedelta(days=days))
        if bad.any():
            raise AssertionError(f"source alignment leak in {name}: {df.loc[bad].iloc[0].to_dict()}")
    if "_persistence_offset_mw" in df:
        for name, expected_time in (
            ("_issue_week_anchor", cutoff - pd.Timedelta(days=7)),
            ("_persistence_offset_mw", cutoff),
        ):
            source = df[f"{name}_source_time"]
            bad = source.notna() & (source != expected_time)
            if bad.any():
                raise AssertionError(f"source alignment leak in {name}: {df.loc[bad].iloc[0].to_dict()}")
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            expected_offset = df.lag_1w * df.last_known / df._issue_week_anchor.replace(0, np.nan)
        valid_reference = np.isfinite(df[["lag_1w", "last_known", "_issue_week_anchor"]]).all(axis=1)
        actual = df._persistence_offset_mw.to_numpy(dtype=float)
        bad = np.isfinite(actual) & (~valid_reference | ~np.isfinite(expected_offset) | ~np.isclose(actual, expected_offset))
        if bad.any():
            raise AssertionError(f"persistence offset source mismatch: {df.loc[bad].iloc[0].to_dict()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--dense", action="store_true")
    parser.add_argument("--recent-dense", action="store_true", help="also issue every half-hour over the last 60 days (spec 1.6)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    frame = build(args.data, args.dense, args.recent_dense)
    print(frame.shape)
    print(frame.columns.tolist())
    print(frame.groupby("h").size().head())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(args.output, index=False)
