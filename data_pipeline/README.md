# Real-data pipeline

Download and build code used for `data/canonical/real.parquet`. The canonical
window is **7 March 2024–31 December 2025**, inclusive: 31,920 UTC half-hours
per zone, 319,200 rows across ten zones. Column names and types come from the
repository's `schemas.py`.

## Sources

- **NESO historic demand:** [datastore API](https://api.neso.energy/api/3/action/datastore_search_sql),
  annual 2024/2025 outturn resources. Use `ND`; convert local settlement periods
  to UTC with the shared conversion in `pull_neso.py`, including clock changes.
  The national-demand sanity range is 12,000–50,000 MW.
- **Elexon FUELHH:** [generation-by-fuel API](https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH),
  fetched in seven-day windows. Preserve published MW values, signed flows and
  missing fuel cells. `wind_total_mw` excludes embedded wind; absent solar is
  not invented as zero. Generation is a separate supporting table.
- **Open-Meteo [Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api):**
  `https://previous-runs-api.open-meteo.com/v1/forecast`, at each contract zone's
  centroid, using `temperature_2m_previous_day1`,
  `wind_speed_100m_previous_day1` and `shortwave_radiation_previous_day1`.
  Wind is requested in m/s. Interpolate hourly values to half-hours and clamp
  negative solar to zero. Raw response bytes are saved before parsing.

The window starts on 7 March because these Previous Runs variables have
incomplete earlier coverage. Full NESO/Elexon inputs remain under `data/raw`;
the canonical builder writes trimmed copies under `data/canonical`.

## Estimated zonal demand

For each half-hour, compute `weight[z] = share[z] * (1 + 0.015 * max(15.5 - temp_c[z], 0))`,
using shares from `schemas.DEMAND_SHARE`. Normalise the weights and multiply
by national ND, conserving the national total. All targets are labelled
`is_estimated=True`: these are allocated estimates, not regional meter readings.
The intermediate keeps float64 demand; the canonical table uses float32.

## Rebuild

Run from **`dhruv_latest/`**, which holds the project contract (`schemas.py`) and the
`data/` folder, in a Python environment with `numpy pandas pyarrow requests matplotlib tzdata`
installed. Run each command separately and stop on failure:

```bash
cd dhruv_latest
python ../data_pipeline/pull_neso.py
python ../data_pipeline/pull_elexon.py
python ../data_pipeline/pull_weather.py
python ../data_pipeline/build_zone_demand.py
python ../data_pipeline/build_canonical.py
python ../data_pipeline/quality_report.py
python -I ../data_pipeline/check_parquet.py data/canonical/real.parquet
```

Add `--offline` to the three download commands to reuse saved responses.
The weather script archives legacy caches as `weather_OLD_DO_NOT_USE` and
compares temperatures when that archive exists; clean builds explicitly report
that the old-weather comparison is unavailable. Missing source hours fail.
Only bounded missing demand runs of 1–3 half-hours are filled and flagged.
Outputs and reports go to `data/` and `results/`; this folder contains code only.

`weather_issue_time_utc` follows the requested `timestamp_utc - 24h` convention.
Previous-day offsets describe hourly source forecasts, not exact publication
times or a single fixed-origin forecast run. Half-hour interpolation also uses
the following hour's forecast. See the generated quality report for those
timing limits and the estimated-target caveat before interpreting model scores.
