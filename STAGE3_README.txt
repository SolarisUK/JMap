Stage 3: weather for all 10 zones, 2024-2025

Extract this ZIP into C:\Users\ranya\JMap. Keep pulls, data and results directly
inside JMap, beside the project's schemas.py and the earlier stage files.

At a fresh PowerShell prompt inside JMap, run:

    python .\pulls\pull_weather.py --offline

Expected: Stage 3 weather checks: PASS, 10 zones, 350,880 rows, 100% demand/weather
timestamp coverage per zone, no duplicate keys, missing half-hours or nulls.
PASS covers format and coverage. It does not certify historical forecast timing.

This offline command reads your schemas.py for zone IDs and coordinates,
verifies the cached responses match those coordinates and your demand dates,
checks their hashes, and rebuilds weather.parquet. It makes no network calls.
The preparatory download used the coordinates printed from schemas.py in your
supplied PowerShell history. Your current schemas.py remains authoritative.

Files
-----
pulls/pull_weather.py
data/raw/weather/weather.parquet
data/raw/weather/<zone_id>.json             Original API response bytes
data/raw/weather/<zone_id>.source.json      Request coordinates, units, URL, hash
data/raw/weather/provenance.json            Data conventions and limitations
results/stage3_checks.txt

Output columns and Arrow types
-----------------------------
zone_id                        string
timestamp_utc                  timestamp[us, tz=UTC]
temp_c                         float32
wind_ms                        float32
solar_wm2                      float32
weather_issue_time_utc          timestamp[us, tz=UTC]

Source: Open-Meteo Historical Forecast API, default best_match model selection.
Wind speed is explicitly requested in m/s at 100 m; temperature is 2 m Celsius.
No ERA5 reanalysis, observations or synthetic weather have been substituted.

Hourly values are linearly interpolated to half-hours. The response includes
the following UTC day to bracket the last half-hour, so no edge extrapolation
or forward filling is needed. Missing hourly source data causes an error.
Solar is clamped to zero if negative. No values required that clamp in this
download. Solar maxima between 23:00 and 03:00 UTC are zero in all ten zones.

Forecast timing limitation
-------------------------
The runbook's previous-day 06:00 UTC issue time is a PROXY. It is filled in
weather_issue_time_utc to follow the agreed file format and convention.

Open-Meteo's Historical Forecast API stitches the first hours of successive
model runs into a time series. It does not return the exact forecast run that
would have been available at the proxy time. Assigning an earlier timestamp
does not make these values a true day-ahead forecast and does not remove
forecast-vintage leakage. Do not describe evaluation with this data as a
leakage-free operational day-ahead backtest.

For a backtest with known historical forecast runs, use Single Runs archives
and account for both model initialization and publication/availability times.
The distinction is documented in Open-Meteo's current API documentation.

Other limits
------------
Each zone is represented by one centroid/grid cell. This is not a weighted
weather average over the region. The default model selection may vary over
time and by variable. The raw responses and source metadata preserve what
was returned.

shortwave_radiation is a preceding-hour mean. Following the runbook, the script
interpolates at the source time labels. The result is an approximate feature,
not an exact half-hour interval-average solar irradiance.

Half-hour interpolation of weather is routine feature resampling; it does not
mean the demand target was filled. The canonical INTERPOLATED quality bit is
for filled targets and should not automatically be set on all these rows.

Refreshing
----------
Run without --offline to download any absent responses. Existing cached files
are reused. If coordinates or dates change, the script stops instead of using
stale data. Move the affected zone's .json and .source.json files aside before
downloading replacements. Keep pulls/pull_neso.py: it supplies the shared HTTP
session with retries.

The project's scripts/check_parquet.py is still needed at Stage 5. This is
the Stage 3 weather intermediate, not the final nine-column canonical file.
Next: Stage 4, estimated zone demand; then Stage 5, build real.parquet.

Attribution and documentation
-----------------------------
Weather data by Open-Meteo and its underlying weather-service providers.
https://open-meteo.com/en/docs/historical-forecast-api
https://open-meteo.com/en/docs/single-runs-api
https://open-meteo.com/en/docs/previous-runs-api
https://open-meteo.com/en/terms
