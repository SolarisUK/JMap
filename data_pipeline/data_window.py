"""Approved modelling window and shared provenance text.

Full NESO/Elexon source files stay in data/raw; filter copies in memory.
"""

import pandas as pd


WINDOW_START = pd.Timestamp("2024-03-07T00:00:00Z")
WINDOW_END_EXCLUSIVE = pd.Timestamp("2026-01-01T00:00:00Z")
NATIONAL_DEMAND_MIN_MW = 12_000
NATIONAL_DEMAND_MAX_MW = 50_000
WINDOW_REASON = (
    "Window starts 2024-03-07 because the Open-Meteo Previous Runs API "
    "(previous_day1) has incomplete coverage before then: temperature from "
    "2024-02-04, wind and solar from 2024-03-06."
)
WEATHER_CAVEAT = (
    "Weather is a day-ahead forecast from the Open-Meteo Previous Runs API "
    "(previous_day1 variables, at least 24h lead time). weather_issue_time_utc "
    "is timestamp minus 24h, an upper bound on the issue time."
)
INTERPOLATION_CAVEAT = (
    "The 24h lead applies to hourly source values. At :30, linear interpolation "
    "also uses the next hour's forecast, whose issue-time upper bound is 30 minutes "
    "later than the saved row's bound. The saved time follows the requested "
    "convention; it is not an exact publication time. This fixed-offset series "
    "does not reconstruct a single forecast run for a fixed-origin backtest."
)


def window_index():
    return pd.date_range(WINDOW_START, WINDOW_END_EXCLUSIVE, freq="30min",
                         inclusive="left").as_unit("ns")


def trim_to_window(frame):
    stamps = pd.DatetimeIndex(frame.timestamp_utc)
    if stamps.tz is None or str(stamps.tz) != "UTC" or stamps.hasnans:
        raise ValueError("Window filtering requires non-null UTC timestamps")
    keep = (stamps >= WINDOW_START) & (stamps < WINDOW_END_EXCLUSIVE)
    return frame.loc[keep].copy()


def require_window_grid(values, label):
    stamps = pd.DatetimeIndex(values).as_unit("ns")
    if not stamps.equals(window_index()):
        raise ValueError(f"{label} must cover the approved window exactly, with no gaps or duplicates")
    return stamps
