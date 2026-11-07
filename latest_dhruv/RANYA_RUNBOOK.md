# Ranya's Runbook

Stage by stage, with the prompt to paste at each one. Times are hours from when you start.

**Your job in one sentence:** turn three public data sources into one clean table that Eugene
trains on, plus the map shapes Leonard draws.

You own the thing everyone else's numbers depend on. Eugene can build his whole pipeline on the
synthetic stub, but the accuracy figure we put in front of judges comes from your table. Nothing
else in the project has that property.

Attach `RANYA_RUNBOOK.md`, `CONTRACT.md` and `schemas.py` to your AI session and leave them
attached. Every column name, zone ID and demand share comes from `schemas.py` — if your AI invents
a column called `temperature_c`, it guessed, and the guess is wrong.

| Stage | Hours | What | Gate |
|---|---|---|---|
| 0 | 0:00–0:20 | Setup | `check_parquet.py` passes on the stub |
| 1 | 0:20–1:30 | NESO national demand | 48 rows/day, UTC, no duplicates |
| 2 | 1:30–2:15 | Elexon generation by fuel | joins to demand on timestamp |
| 3 | 2:15–3:00 | Open-Meteo weather, 10 zones | `weather_issue_time_utc` populated |
| 4 | 3:00–3:45 | Split national demand into zones | shares match `schemas.DEMAND_SHARE` |
| 5 | 3:45–5:00 | Build the canonical table | **`check_parquet.py` says PASS** |
| 6 | 5:00–5:45 | Quality report | coverage per zone, gap list |
| 7 | 5:45–7:00 | Zone polygons as GeoJSON | renders on a map |
| 8 | 7:00–7:30 | Hand over | Eugene retrains, stubs regenerated |
| 9 | 14:00–19:00 | Map layer, paired with Leonard | |

---

## Stage 0 — Setup (20 min)

```bash
git pull
pip install requests pandas pyarrow geopandas shapely
python3 schemas.py                                      # "contract v1.0.0 OK"
python3 -I scripts/check_parquet.py data/canonical/_fake.parquet    # "PASS"
```

That last command is your gate at every later stage. It checks columns, types, zone IDs,
half-hour alignment, duplicates, per-zone gaps, flag consistency, and whether your demand split
actually matches the contract. Run it after every change.

Your target schema is `schemas.CANONICAL_SCHEMA`. Print it and keep it on screen:

```bash
python3 -c "import schemas, json; print(json.dumps(schemas.CANONICAL_SCHEMA, indent=2))"
```

---

## Stage 1 — NESO national demand (70 min)

This is the real electricity demand for Great Britain, half-hourly, going back years.

**Where it lives.** NESO's data portal runs on CKAN. Get the list of yearly files first, then
pull the ones you want:

```bash
# list every yearly resource and its id
curl -L -s "https://api.neso.energy/api/3/action/datapackage_show?id=historic-demand-data"
```

Each year is a separate resource. Pull one with either the datastore search endpoint or SQL:

```
https://api.neso.energy/api/3/action/datastore_search?resource_id=<id>&limit=100000
https://api.neso.energy/api/3/action/datastore_search_sql?sql=SELECT * from "<id>"
```

The 2024 resource id is `f6d02c0f-957b-48cb-82ee-09003f2ba759` if you want something to test
against immediately. Get 2024 and 2025 — two years is plenty, and more just slows everything down.

**The columns you need.** `SETTLEMENT_DATE`, `SETTLEMENT_PERIOD`, `ND`,
`FORECAST_ACTUAL_INDICATOR`, and as useful extras `EMBEDDED_WIND_GENERATION`,
`EMBEDDED_SOLAR_GENERATION`.

Use **`ND`** (National Demand), not `TSD`. ND is the sum of metered generation excluding station
load, pump storage pumping and interconnector exports — it's the number everyone means by "GB
demand".

**Three traps, in order of how much time they'll cost you.**

1. **Settlement periods are in LOCAL time, not UTC.** Settlement period 1 runs 00:00–00:30
   *Europe/London*, and `SETTLEMENT_DATE` follows the clock change. So you cannot just do
   `date + period × 30min` and call it UTC. You must build the naive local timestamp, localise it
   to `Europe/London`, then convert to UTC. Get this wrong and every lag feature Eugene builds is
   silently shifted by an hour for half the year.

2. **Clock-change days don't have 48 periods.** The October day has 50, the March day has 46.
   Code that assumes 48 will either crash or quietly mangle those days. Flag them with
   `schemas.QF.DST_BOUNDARY`.

3. **Filter to `FORECAST_ACTUAL_INDICATOR == 'A'`.** Rows marked `F` are forecasts, not outturn.
   Training on them means training on someone else's predictions.

> Prompt:
>
> Attach `CONTRACT.md`, `schemas.py`.
>
> Write `pulls/pull_neso.py`. It downloads NESO historic demand for 2024 and 2025 from the CKAN
> API at `https://api.neso.energy/api/3/action/datastore_search_sql`, saves the raw JSON
> response to `data/raw/neso/<year>.json` **before parsing anything**, then produces a tidy
> DataFrame and writes it to `data/raw/neso/national_demand.parquet`.
>
> Output columns: `timestamp_utc` (tz-aware UTC, interval start), `national_demand_mw`,
> `embedded_wind_mw`, `embedded_solar_mw`, `dst_flag` (bool).
>
> The timestamp conversion is the critical part and I want it done exactly like this:
> settlement period 1 runs 00:00–00:30 in **Europe/London** local time, and `SETTLEMENT_DATE`
> follows the clock change. Build a naive local datetime as `SETTLEMENT_DATE` plus
> `(SETTLEMENT_PERIOD - 1) * 30 minutes`, localise it to `Europe/London` handling both the
> ambiguous hour in October and the non-existent hour in March, then convert to UTC. Do NOT
> treat settlement periods as UTC.
>
> Clock-change days have 46 or 50 periods, not 48. Set `dst_flag` True on those days instead of
> assuming 48.
>
> Filter to `FORECAST_ACTUAL_INDICATOR == 'A'`.
>
> Then print: total rows, the date range, the count of distinct timestamps, how many duplicate
> timestamps there are (should be zero), and the rows-per-day distribution (should be 48 for
> almost every day, with 46 and 50 on two days per year).
>
> Before writing the file, tell me how you're handling the ambiguous hour.

**Verify before moving on:**

```bash
python3 pulls/pull_neso.py
python3 -c "
import pandas as pd
df = pd.read_parquet('data/raw/neso/national_demand.parquet')
print('rows', len(df), '| dupes', df.timestamp_utc.duplicated().sum())
print(df.timestamp_utc.min(), '->', df.timestamp_utc.max())
print(df.groupby(df.timestamp_utc.dt.date).size().value_counts())
print('demand MW: min', df.national_demand_mw.min(), 'max', df.national_demand_mw.max())
"
```

Sanity check on the numbers: GB national demand runs roughly **18,000–48,000 MW**. If you're
seeing 2,000 or 500,000, something's wrong with units or parsing.

---

## Stage 2 — Elexon generation by fuel (45 min)

Half-hourly generation split by fuel type. No API key, no registration.

```
https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH?settlementDateFrom=2024-01-01&settlementDateTo=2024-01-31
```

Returns `{"data": [...]}` with one row per fuel type per settlement period:
`settlementDate`, `settlementPeriod`, `fuelType`, `generation` (MW).

Request a month at a time — a day is about 860 rows, so a year in one call will time out.

> Prompt:
>
> Write `pulls/pull_elexon.py`. It pulls the FUELHH dataset from
> `https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH` in one-month windows across 2024 and
> 2025, saving each raw response to `data/raw/elexon/<year>-<month>.json` before parsing.
>
> Then pivot it so there is one row per settlement period and one column per fuel type, and
> write `data/raw/elexon/generation_by_fuel.parquet` with a `timestamp_utc` column built using
> **exactly the same settlement-period-to-UTC conversion as `pulls/pull_neso.py`** — import that
> function, do not write a second copy. Two different conversions is how the join silently
> produces half the rows it should.
>
> Add a `wind_total_mw` column summing the wind fuel types, and `solar_mw` if present.
>
> Be polite to the API: a 0.5 second pause between calls, and retry a failed request up to three
> times with backoff. Print the fuel types you actually found rather than assuming a list.

**Verify:**

```bash
python3 -c "
import pandas as pd
d = pd.read_parquet('data/raw/neso/national_demand.parquet')
g = pd.read_parquet('data/raw/elexon/generation_by_fuel.parquet')
j = d.merge(g, on='timestamp_utc', how='inner')
print('demand rows', len(d), '| generation rows', len(g), '| joined', len(j))
print('join rate: %.1f%%' % (100*len(j)/len(d)))
"
```

**The join rate should be above 95%.** If it's near 50%, the two scripts are converting
settlement periods differently. If it's near 0%, one of them is tz-naive and the other isn't.

---

## Stage 3 — Weather for 10 zones (45 min)

Each zone's centroid is already in `schemas.ZONES` as `lat` and `lon`. You need temperature, wind
speed and solar radiation for each.

**Use the historical forecast API, not the archive.**

```
https://historical-forecast-api.open-meteo.com/v1/forecast
    ?latitude=51.5&longitude=-0.1
    &start_date=2024-01-01&end_date=2025-12-31
    &hourly=temperature_2m,wind_speed_100m,shortwave_radiation
```

Why this matters: the archive endpoint (`archive-api.open-meteo.com/v1/archive`) gives ERA5
reanalysis — the weather as it *actually turned out*, reconstructed later. The historical forecast
endpoint gives archived output from the short-range forecast models — roughly what was *predicted*
at the time. Training on reanalysis makes Eugene's model look better than it will ever be in
operation, because in operation you only ever have a forecast. That's the single biggest
credibility hole in a project like this, and judges who know the domain ask about it.

Set `weather_issue_time_utc` to the forecast issue time. The historical forecast API doesn't let
you pick an exact issue time, so use the convention Dhruv's stub uses: the 06:00 UTC run of the
previous day. Note the approximation in your quality report; don't pretend it's exact.

> Prompt:
>
> Write `pulls/pull_weather.py`. For each of the 10 zones in `schemas.ZONES`, pull hourly
> `temperature_2m`, `wind_speed_100m` and `shortwave_radiation` from
> `https://historical-forecast-api.open-meteo.com/v1/forecast` for the zone's `lat`/`lon` over
> the same date range as the demand data. Save each raw response to
> `data/raw/weather/<zone_id>.json` before parsing.
>
> Open-Meteo returns hourly data but we need half-hourly, so resample: interpolate temperature
> and wind linearly, and interpolate solar radiation linearly too but clamp negatives to zero.
>
> Write `data/raw/weather/weather.parquet` with columns `zone_id`, `timestamp_utc`, `temp_c`,
> `wind_ms`, `solar_wm2`, `weather_issue_time_utc`. Set the issue time to the 06:00 UTC run of
> the day before each timestamp.
>
> Use the historical forecast endpoint, NOT `archive-api.open-meteo.com`. The archive gives
> reanalysis — the weather as it actually turned out — and training on that leaks future
> information.
>
> Then print per zone: row count, temperature min/max/mean, and the maximum solar radiation
> between 23:00 and 03:00 UTC.

**Verify:** that last number should be **zero or very close**. Solar radiation in the middle of
the night means your timestamps are shifted.

---

## Stage 4 — Split national demand into zones (45 min)

Great Britain's real regional demand only exists inside the distribution companies' data, and
every one publishes it differently. We can't stitch that together today. So we estimate: take
national demand and divide it by each zone's share of annual consumption.

Those shares are **already in the contract**, from DESNZ subnational electricity consumption
statistics:

```python
import schemas as S
S.DEMAND_SHARE    # {'NSCO': 0.04, 'SSCO': 0.07, ..., 'SOUT': 0.14}  sums to 1.00
```

> Prompt:
>
> Write `pulls/build_zone_demand.py`. Read `data/raw/neso/national_demand.parquet` and produce
> one row per zone per timestamp, where `demand_mw` is national demand times that zone's
> `schemas.DEMAND_SHARE`, with a temperature adjustment: zones colder than the national average
> at that timestamp get proportionally more, using a heating sensitivity of 1.5% extra demand
> per degree below 15.5°C. Renormalise after the adjustment so the zone totals still sum to
> national demand exactly.
>
> Set `is_estimated` True on every row — this is a split, not a measurement.
>
> Write `data/raw/zone_demand.parquet`. Print each zone's share of total demand next to
> `schemas.DEMAND_SHARE` so I can see they match within a percentage point.

**Say "estimated regional demand", never "measured".** Label it that way in the quality report and
tell Leonard to label it on the dashboard. It's a real limitation, it's the honest framing, and
judges respect it far more than a silent fudge.

---

## Stage 5 — Build the canonical table (75 min)

This is your main deliverable. Everything joins here.

> Prompt:
>
> Attach `schemas.py`, `scripts/check_parquet.py`.
>
> Write `pulls/build_canonical.py`. Join `data/raw/zone_demand.parquet` and
> `data/raw/weather/weather.parquet` on `(zone_id, timestamp_utc)` and write
> `data/canonical/real.parquet` with **exactly** the columns, order and dtypes in
> `schemas.CANONICAL_SCHEMA`. Build the pyarrow schema programmatically from that dict rather
> than hand-writing types.
>
> Quality flags, as a `uint8` bitfield using the constants in `schemas.QF`, combined with OR:
> - `MISSING` where `demand_mw` is null
> - `INTERPOLATED` where a gap under 2 hours was filled
> - `ZERO_RUN` where demand is zero or near-zero for 3+ consecutive half-hours
> - `JUMP` where demand changes more than 40% between consecutive half-hours
> - `DST_BOUNDARY` on clock-change days
>
> Gaps under 2 hours: interpolate and flag `INTERPOLATED`. Gaps over 2 hours: leave the target
> null and flag `MISSING`, but keep the row so its weather is still available as a feature
> source.
>
> Sort by `(zone_id, timestamp_utc)` before writing.
>
> Then run `scripts/check_parquet.py` against the output and print its result.

**Gate — do not move on until this says PASS:**

```bash
python3 pulls/build_canonical.py
python3 -I scripts/check_parquet.py data/canonical/real.parquet
```

If it reports problems, fix them. It is the same validator Dhruv and Eugene will run, so
anything it catches now is something you'd otherwise hear about at hour 12.

---

## Stage 6 — Quality report (45 min)

> Prompt:
>
> Write `pulls/quality_report.py` producing `results/data_quality.md`: a one-page report with
> total rows, date range, rows and coverage percentage per zone, a table of every gap longer
> than 2 hours, the count of each quality flag, the national demand min/max/mean against the
> expected 18,000–48,000 MW range, and each zone's share of total demand next to the contract
> value.
>
> At the top, three plain-sentence caveats: that zone demand is estimated from national demand
> rather than measured, that weather is archived short-range forecast rather than true
> issue-time forecast, and anything else you found that a reader should know.
>
> Also save `results/data_coverage.png`: a heatmap of zone against day, coloured by how many
> half-hours are present.

That report is worth real credit. "Here is what's wrong with our data and how we handled it" is
a stronger answer than a dashboard that implies the data is perfect.

---

## Stage 7 — Zone polygons (75 min)

Leonard's map currently draws placeholder boxes. Replace them with real shapes.

Simplest route that works: the 14 regions used by the Carbon Intensity API map closely onto GB
electricity geography, and `schemas.ZONE_ORDER` has 10 zones built by merging them. Alternatively
use ONS region boundaries and merge to the same 10.

> Prompt:
>
> Write `pulls/build_geo.py` producing `data/geo/zones.geojson`: a GeoJSON FeatureCollection
> with one Polygon or MultiPolygon per zone in `schemas.ZONE_ORDER`.
>
> Each feature's `properties` must carry exactly `zone_id`, `name`, `demand_share`,
> `storage_mwh` and `dr_mw`, read from `schemas.ZONES`. Leonard's dashboard already reads those
> keys, so they can't change.
>
> Get the geometry by downloading GB region boundaries and dissolving them into the 10 zones
> with geopandas. Write down the mapping from source regions to our zones as a dict in the file
> so it's reviewable. Simplify the geometry with a tolerance that keeps the file under 2 MB —
> a browser rendering 50,000 coordinate pairs will crawl.
>
> Then print each zone's area and centroid, and assert all 10 zones are present with valid,
> non-empty geometry.

**Verify by looking at it.** Paste the file into [geojson.io](https://geojson.io) and check it
looks like Britain. A polygon in the wrong hemisphere is obvious by eye and invisible in a test.

---

## Stage 8 — Hand over (30 min)

```bash
# Eugene retrains on real data
#   -> tell him data/canonical/real.parquet is ready and passes the validator

# Leonard gets real map shapes
python3 scripts/make_api_stubs.py      # picks up data/geo/zones.geojson
#   -> tell him /zones now returns real polygons, properties unchanged

git add data/canonical/real.parquet data/geo/zones.geojson pulls/ results/ stubs/
git commit -m "Real NESO + Elexon + Open-Meteo data, zone polygons, quality report"
git push
```

Message them both. Eugene needs to rerun `train.py` and `evaluate.py` — every number he has so
far came from synthetic data and none of it goes on a slide.

---

## Things not to do

1. **Don't treat settlement periods as UTC.** They're `Europe/London` local and follow the clock
   change. This is the single most expensive mistake available to you.
2. **Don't write the conversion twice.** One function, imported by both pull scripts.
3. **Don't use `archive-api.open-meteo.com`.** That's reanalysis and it leaks.
4. **Don't assume 48 periods per day.** Two days a year have 46 and 50.
5. **Don't include `FORECAST_ACTUAL_INDICATOR == 'F'` rows.**
6. **Don't parse before saving the raw response.** When a parse turns out wrong at hour 10 you
   want the original bytes, not another download.
7. **Don't silently interpolate everything.** Flag what you filled. Eugene excludes flagged rows
   from scoring, and he can't if you didn't mark them.
8. **Don't call the zone demand "measured".** It's estimated from a national total.
9. **Don't hardcode zone IDs or column names.** Import from `schemas.py`.
10. **Don't use `TSD` where the contract wants demand.** Use `ND`.

## One known data issue

NESO's 2026 historic demand page carries a notice that they've moved to a new forecast system and
Scottish transfer data is missing. You don't need that column, but if your AI starts using it,
stop it. Prefer 2024 and 2025 anyway: complete years, and two years is plenty of history.

## When to stop and talk to Dhruv

- The demand/generation join rate is below 95%.
- `check_parquet.py` reports problems you can't fix in 20 minutes.
- Solar radiation isn't zero at night.
- National demand is outside 18,000–48,000 MW.
- Region boundaries won't dissolve into our 10 zones.

Each of these has a fallback, and the fallback for the last one is that Leonard keeps the
placeholder boxes. The dashboard works either way — don't burn three hours on map geometry while
the canonical table is unfinished. **The table is your deliverable. The polygons are a bonus.**
