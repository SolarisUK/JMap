# Leonard's Spec — Every Endpoint, Every Field

**For:** Leonard. **Written by:** Dhruv. **Depends on:** `schemas.py`.

Every field of every endpoint, with real example payloads in `stubs/`. Those stubs were generated
**by the running simulator**, not written by hand, so their shapes are identical to what the real
API will return. Build the whole dashboard against them and the hour-10 swap is a config change.

```bash
python3 scripts/make_api_stubs.py     # regenerate any time
ls stubs/
```

Import your constants — never retype them:

```python
import schemas as S
S.ZONE_ORDER       # ('NSCO','SSCO','NORT','YORK','WALE','MIDL','EAST','SWES','LOND','SOUT')
S.EDGE_ORDER       # 14 corridor ids
S.FUEL_ORDER       # 8 fuels, the order of every per-fuel array
S.STRATEGIES       # ('none','optimiser','agents') -- scoreboard keys, do not rename
S.INCIDENT_TYPES   # the five incident types
```

`stubs/reference.json` holds all of those as JSON if you'd rather not import Python.

---

## Endpoint summary

| Method | Path | Stub file | Used by |
|---|---|---|---|
| `GET` | `/zones` | `zones.json` | map polygons |
| `GET` | `/edges` | `edges.json` | map corridor lines |
| `GET` | `/state?t=` | `state_calm.json`, `state_incident.json` | map colours, scoreboard tiles |
| `GET` | `/state/series?scenario=&strategy=` | `state_series.json` | the time slider |
| `GET` | `/forecast/{zone_id}?issue_time=` | `forecast_LOND.json` | the forecast chart |
| `GET` | `/scenarios` | `scenarios.json` | scenario picker |
| `POST` | `/incident` | `incident_response.json` | the incident buttons |
| `GET` | `/compare?scenario=` | `compare.json` | the closing scoreboard |
| `GET` | `/reference` | `reference.json` | enumerations, colour keys |

---

## `GET /zones`

GeoJSON `FeatureCollection`, one feature per zone.

| Field | Type | Notes |
|---|---|---|
| `properties.zone_id` | string | one of `S.ZONE_ORDER`. **Join key for everything.** |
| `properties.name` | string | display name, e.g. "South & South East England" |
| `properties.demand_share` | float | 0–1, sums to 1.00 across zones |
| `properties.storage_mwh` | float | battery energy capacity |
| `properties.dr_mw` | float | demand response available |
| `geometry` | Polygon | **placeholder boxes right now** |

The geometry is a box around each zone's centroid. Ranya replaces it with real service-area
polygons around hour 8. **The properties are final** — build against those and the swap changes
nothing in your code.

---

## `GET /edges`

Static topology, so you can draw the corridors before any simulation runs.

| Field | Type | Notes |
|---|---|---|
| `edge_id` | string | e.g. `"SSCO-NORT"` |
| `from`, `to` | string | zone ids. **Positive flow runs from → to.** |
| `limit_mw` | float | total thermal limit across all circuits |
| `circuits` | int | 1 or 2 |
| `from_lat`, `from_lon`, `to_lat`, `to_lon` | float | endpoints for drawing the line |

`SSCO-NORT` is the Scotland–England boundary and the centrepiece of the demo. Consider drawing it
thicker than the rest.

---

## `GET /state?t=<iso8601>`

One half-hour snapshot. The single most important endpoint — it drives the map.

Top level:

| Field | Type |
|---|---|
| `timestamp_utc` | ISO 8601 string, UTC |
| `zones` | object keyed by `zone_id` |
| `edges` | object keyed by `edge_id` |
| `totals` | object, episode cumulative |
| `incidents` | array, currently active |

### `zones[zone_id]`

| Field | Unit | Notes |
|---|---|---|
| `demand_mw` | MW | after any demand-spike incident |
| `generation_mw` | MW | all fuels plus storage net output |
| `unserved_mw` | MW | **demand not met. Colour this red.** |
| `cost_gbp` | £ | this half-hour only, not cumulative |
| `carbon_t` | tCO2 | this half-hour only |
| `curtailed_mw` | MW | renewables thrown away |
| `storage_soc` | 0–1 | state of charge |
| `dr_called_mw` | MW | demand response actually called |

A zone generating far less than its demand is **normal**, not an error — it's importing. `LOND`
does this constantly. Don't colour by `generation_mw - demand_mw` and call it a problem; colour by
`unserved_mw`.

### `edges[edge_id]`

| Field | Unit | Notes |
|---|---|---|
| `flow_mw` | MW | **signed.** Positive = from → to. Negative = reverse |
| `limit_mw` | MW | current limit, already reduced by any trip |
| `loading_frac` | ratio | `abs(flow) / limit`. **Can exceed 1.0** |
| `tripped` | bool | limit currently below nameplate |

`loading_frac > 1.0` is a real, expected state — physics doesn't respect thermal limits, operators
have to redispatch. It is the thing the agents are trying to prevent, so it deserves a distinct
colour from a healthy line. Suggested bands: under 0.75 green, 0.75–1.0 amber, over 1.0 red,
`tripped` dashed or grey.

A fully tripped line reports `limit_mw: 0`, `flow_mw: 0`, `loading_frac: 0`. It is not carrying
power and not overloaded — it's gone. Render it as absent, not as healthy.

### `totals`

Cumulative over the episode so far: `unserved_mwh`, `cost_gbp`, `carbon_t`, `curtailed_mwh`.
These are your live KPI tiles. `cost_gbp` includes unserved energy valued at £6,000/MWh, which is
why it moves so sharply during an incident.

---

## `GET /state/series?scenario=<name>&strategy=<none|optimiser|agents>`

All 48 half-hours of one episode in a single response. Build the time slider against this and it
works with no backend at all.

```
{ "scenario": "b6_trip_windy_peak",
  "strategy": "optimiser",
  "frames": [ { "timestamp_utc", "zones", "edges", "incidents" }, ... ] }
```

Frames carry a reduced zone payload — `demand_mw`, `generation_mw`, `unserved_mw`, `storage_soc` —
and a reduced edge payload: `flow_mw`, `loading_frac`, `tripped`. Call `/state` when you need the
full detail for one moment.

**Fetch two series, one with `strategy=none` and one with `strategy=agents`, and show them side by
side.** That split-screen is the demo: the same incident, with and without the response. It is far
more convincing than any number on a slide.

---

## `GET /forecast/{zone_id}?issue_time=<iso8601>`

| Field | Type | Notes |
|---|---|---|
| `zone_id` | string | |
| `issue_time_utc` | ISO 8601 | |
| `unit` | string | always `"MW"` |
| `quantiles` | array | always `["p10","p50","p90"]` |
| `timestamps_utc` | array[48] | the half-hour each row refers to |
| `forecast` | array[48][3] | `[p10, p50, p90]` per row |
| `explanation` | array[3] | short English strings from SHAP |

Row `i` is the half-hour starting at `issue_time + i × 30min`. Plot `p50` as a line with `p10`–`p90`
as a shaded band; the band widens with horizon, which is what makes it look like a real forecast.

`explanation` comes from Eugene's SHAP output and reads as English, not feature names —
"colder than usual for the time of year". Put it under the chart. It's a cheap, strong judge hook.

---

## `GET /scenarios`

`{"scenarios": [{"name", "description"}]}` — three entries, names from `S.SCENARIOS`.

---

## `POST /incident`

Body is an incident object:

| Field | Type | Notes |
|---|---|---|
| `type` | string | one of `S.INCIDENT_TYPES` |
| `target` | string | `edge_id` for `line_trip`, otherwise `zone_id` |
| `start_step` | int | 0–47 |
| `duration_steps` | int | ≥ 1 |
| `magnitude` | float | meaning depends on type, below |

| Type | `magnitude` means |
|---|---|
| `line_trip` | fraction of circuits lost, 0–1 |
| `generator_outage` | fraction of that zone's dispatchable capacity lost |
| `wind_lull` | multiplier on wind output, 0–1 |
| `demand_spike` | multiplier on demand, ≥ 1 |
| `interconnector_loss` | fraction of `IMPORT` capacity lost |

Returns `{"ok": true, "incident_id": "...", "incident": {...}}`.

For the buttons, three presets are enough: "Trip Scotland–England boundary"
(`line_trip`, `SSCO-NORT`, magnitude 1.0), "Cold snap" (`demand_spike`, 1.18, all zones),
"Nuclear outage" (`generator_outage`, `EAST`, 0.9).

---

## `GET /compare?scenario=<name>`

The closing scoreboard.

```
{ "scenario": "b6_trip_windy_peak",
  "strategies": {
    "none":      {"unserved_mwh", "cost_gbp", "carbon_t", "curtailed_mwh"},
    "optimiser": {...},
    "agents":    {...} } }
```

The three strategy keys are fixed — `S.STRATEGIES`. Don't rename them in your UI layer; the eval
loop writes them.

**Current real numbers** for `b6_trip_windy_peak`, from the stub:

| Strategy | Unserved MWh | Cost £ | Curtailed MWh |
|---|---|---|---|
| none | 55,564 | 349,734,951 | 55,564 |
| optimiser | 2,289 | 34,547,151 | 41,330 |
| agents | *placeholder* | | |

That 96% reduction in unserved energy is the headline of the whole project. Make it the biggest
thing on the screen.

**Two honesty requirements.** The stub currently copies the optimiser's numbers into `agents`
and sets `"agents_is_placeholder": true` so the scoreboard renders before the policy is trained.
If that flag is present, label the agents column "not yet trained" rather than showing the
optimiser's figures as if they were the policy's. And if Eugene's policy ends up behind the
optimiser, we show the optimiser as the result and say so — don't build a UI that can only tell a
winning story.

---

## What to build in what order

| Hours | Build | Against |
|---|---|---|
| 0–2 | FastAPI serving the nine stub files from disk | `stubs/` |
| 2–5 | GB map, zones from `/zones`, corridors from `/edges`, coloured from `/state` | stubs |
| 5–7 | Time slider over `/state/series`, KPI tiles from `totals` | stubs |
| 7–9 | Forecast chart with the P10–P90 band, explanation text under it | stubs |
| 9–10 | Incident buttons and the scenario picker | stubs |
| 10–12 | Point the same calls at the real backend | real |
| 12–15 | Split screen: `strategy=none` beside `strategy=agents` | real |
| 15–18 | Scoreboard, three scripted scenarios, polish | real |
| 18–19 | **Record the backup video** | real |

That hour-18 video is not optional. Hackathon demos fail live constantly, and a recording is the
difference between a story and an apology.

---

## Five things that will cost you time

1. **Colouring zones by `generation_mw - demand_mw`.** Importing zones look broken. Colour by
   `unserved_mw`.
2. **Treating `loading_frac > 1.0` as a bug.** It's the expected state the agents fight, and it
   needs its own colour.
3. **Rendering a fully tripped line as healthy** because `loading_frac` is 0. Check `tripped`.
4. **Hardcoding zone ids or fuel order.** Import from `schemas.py` or read `reference.json`.
   `S.FUEL_ORDER` is the order of every per-fuel array in the system.
5. **Assuming `flow_mw` is positive.** It's signed relative to the edge's `from`→`to` direction.
   Arrow direction on the map comes from the sign.
