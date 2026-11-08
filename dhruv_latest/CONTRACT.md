# Grid Project — Interface Contract v1.0.0

**Owner:** Dhruv. **Frozen at hour 2.** Changes after that need all four of us to agree out loud.

Everything in here is also in `schemas.py`, which is pure standard library — `import schemas` works
with nothing installed. Where this document and `schemas.py` disagree, `schemas.py` wins.

---

## 0. The rules

1. **Build against fake data from hour 0.** Ranya commits `data/canonical/_fake.parquet` in the
   schema below within 30 minutes. Everyone else starts immediately.
2. **Cross boundaries as files, never imports.** Eugene saves models to `models/`. Dhruv and
   Leonard load from `models/`. Nobody imports anybody else's training or simulation code.
3. **UTC everywhere internally.** Convert to Europe/London only for display labels. The UK had a
   25-hour day on 25 October 2026; index by local time and lag features break silently.
4. **One branch each, merge when it runs.** `dhruv/`, `eugene/`, `ranya/`, `leonard/`.
5. **MW for power, MWh for energy, £ for money, tCO2 for carbon.** No kW anywhere.

---

## 1. Zones

Ten zones. The IDs are literal and final — they key every table, file and API response.

| ID | Name | Demand share | Notes |
|---|---|---|---|
| `NSCO` | North Scotland | 4% | Wind-heavy, exports south |
| `SSCO` | South Scotland | 7% | Wind + nuclear, exports south |
| `NORT` | North England | 13% | North West + North East merged |
| `YORK` | Yorkshire | 8% | Biomass-heavy |
| `WALE` | Wales | 6% | North + South Wales merged |
| `MIDL` | Midlands | 17% | East + West Midlands merged; **slack bus** |
| `EAST` | East England | 10% | Offshore wind + interconnectors |
| `SWES` | South West England | 8% | Solar-heavy |
| `LOND` | London | 13% | Almost pure demand sink |
| `SOUT` | South & South East England | 14% | Interconnector-heavy |

Demand shares are rough estimates, not yet checked against DESNZ subnational consumption statistics; they sum to 1.00. Ranya multiplies national
half-hourly demand by these to get estimated zone demand.

**`MIDL` is the slack bus** for the power flow. Don't change this without telling Dhruv.

---

## 2. Transmission edges

Fourteen edges. `limit_mw` is the total thermal limit across all circuits on that corridor.

| Edge ID | From | To | Limit MW | Circuits |
|---|---|---|---|---|
| `NSCO-SSCO` | NSCO | SSCO | 3200 | 2 |
| `SSCO-NORT` | SSCO | NORT | 6000 | 2 |
| `NORT-YORK` | NORT | YORK | 5000 | 2 |
| `NORT-WALE` | NORT | WALE | 2500 | 1 |
| `YORK-MIDL` | YORK | MIDL | 6000 | 2 |
| `YORK-EAST` | YORK | EAST | 3000 | 1 |
| `WALE-MIDL` | WALE | MIDL | 3000 | 2 |
| `WALE-SWES` | WALE | SWES | 2000 | 1 |
| `MIDL-EAST` | MIDL | EAST | 4000 | 2 |
| `MIDL-LOND` | MIDL | LOND | 5000 | 2 |
| `MIDL-SWES` | MIDL | SWES | 3000 | 1 |
| `EAST-LOND` | EAST | LOND | 4500 | 2 |
| `LOND-SOUT` | LOND | SOUT | 5000 | 2 |
| `SWES-SOUT` | SWES | SOUT | 2500 | 1 |

`SSCO-NORT` is the Scotland–England boundary (B6). It is the demo. Tripping one of its two
circuits halves the limit to 3000 MW, which on a windy evening peak forces Scottish wind
curtailment and a shortfall in the south. That is the scenario the agents have to solve.

Sign convention: positive flow runs **from** → **to**.

---

## 3. Fuels

| Fuel | £/MWh | tCO2/MWh | Dispatchable |
|---|---|---|---|
| `NUCLEAR` | 10 | 0.00 | no |
| `CCGT` | 75 | 0.37 | yes |
| `OCGT` | 180 | 0.55 | yes |
| `WIND` | 0 | 0.00 | no (curtailable) |
| `SOLAR` | 0 | 0.00 | no (curtailable) |
| `HYDRO` | 5 | 0.00 | yes |
| `BIOMASS` | 110 | 0.12 | yes |
| `IMPORT` | 90 | 0.25 | yes |

Fuel order in every vector is the order of this table. `schemas.FUEL_ORDER` is the definitive list.

---

## 4. The canonical table

One row per `(zone_id, timestamp_utc)`. Written by Ranya, read by everyone.

**Path:** `data/canonical/year=YYYY/month=MM/part.parquet`

| Column | Type | Notes |
|---|---|---|
| `zone_id` | `string` | One of the ten IDs above |
| `timestamp_utc` | `timestamp[us, tz=UTC]` | Half-hour interval **start** |
| `demand_mw` | `float32` | Estimated zone demand |
| `temp_c` | `float32` | 2 m air temperature |
| `wind_ms` | `float32` | 100 m wind speed |
| `solar_wm2` | `float32` | Shortwave radiation |
| `weather_issue_time_utc` | `timestamp[us, tz=UTC]` | When this weather was **forecast**. Null = observed. |
| `quality_flag` | `uint8` | Bitfield, see below |
| `is_estimated` | `bool` | True for zone demand split from national |

`weather_issue_time_utc` is not optional. Training on observed weather instead of what was
forecast at the time inflates accuracy and judges will ask. Ranya pulls Open-Meteo's
historical-forecast endpoint for exactly this reason.

**Quality flags** (bitfield, combine with OR):

| Bit | Value | Meaning |
|---|---|---|
| — | 0 | OK |
| 0 | 1 | `MISSING` — target absent, do not score |
| 1 | 2 | `INTERPOLATED` — filled for features only, do not score |
| 2 | 4 | `ZERO_RUN` — suspicious run of zeros |
| 3 | 8 | `JUMP` — implausible step change |
| 4 | 16 | `DST_BOUNDARY` — clock-change day, 46 or 50 periods |

Rows with bit 0 or bit 1 set are excluded from scoring. They stay in the table for features.

---

## 5. The forecaster

Eugene writes these files. Nobody imports his training code.

**Files:**

```
models/lgbm_q10.txt         LightGBM booster, alpha=0.1
models/lgbm_q50.txt         LightGBM booster, alpha=0.5
models/lgbm_q90.txt         LightGBM booster, alpha=0.9
models/feature_names.json   ordered list of feature column names
models/metadata.json        training window, MAE/WAPE by horizon, baseline MAE
```

**The function.** Eugene also ships `forecast.py` exposing exactly:

```python
def predict(zone_id: str, issue_time_utc: datetime) -> list[list[float]]:
    """Returns 48 rows of [p10, p50, p90] in MW, for the 48 half-hours
    starting at issue_time_utc. Row 0 is the half-hour beginning at issue_time_utc."""

def predict_all(issue_time_utc: datetime) -> list[list[list[float]]]:
    """Returns 10 x 48 x 3, zones in schemas.ZONE_ORDER order."""
```

Return plain nested lists, not numpy arrays. That keeps it JSON-serialisable for Leonard with no
conversion step.

**`metadata.json` must contain** `baseline_mae_mw` (the same-half-hour-last-week number) alongside
the model's own MAE. The comparison is the result we present.

---

## 6. The simulator

Dhruv writes this. Gymnasium-compatible.

```python
env.reset(seed=None, options=None) -> (obs, info)
env.step(action)                   -> (obs, reward, terminated, truncated, info)
```

- `obs` is shape `(10, 52)` — one row per zone, in `ZONE_ORDER`.
- `action` is shape `(10, 11)`, every element in `[-1, 1]`.
- One step is one half-hour.
- An episode is 48 steps (one day).

**Observation layout per zone (52 values).** Index constants live in `schemas.py` as `OBS_*`.

| Index | Contents |
|---|---|
| 0–1 | sin, cos of time of day |
| 2 | is_weekend |
| 3 | demand now, normalised |
| 4–7 | P50 forecast at +1, +2, +4, +8 half-hours |
| 8–9 | P90 forecast at +1, +4 half-hours |
| 10–17 | available capacity by fuel (8 values, `FUEL_ORDER`) |
| 18–25 | current output by fuel (8 values) |
| 26 | storage state of charge, 0–1 |
| 27 | storage power available, normalised |
| 28 | demand response available, normalised |
| 29 | unserved MW last step, normalised |
| 30 | own net position (generation − demand), normalised |
| 31–35 | signed flow / limit on each adjacent edge (padded to 5) |
| 36–40 | headroom fraction on each adjacent edge |
| 41–45 | tripped flag per adjacent edge |
| 46–50 | neighbour net position, normalised |
| 51 | national margin, normalised |

`MAX_DEGREE = 5`, because `MIDL` is the transmission hub with five adjacent corridors. Every other
zone has three or fewer and is zero-padded. Adjacent edges appear in `schemas.ADJACENT[zone_id]`
order, which is `EDGE_ORDER` order — not geographic, so don't assume north-to-south.

**Action layout per zone (11 values), all `[-1, 1]`.** Index constants are `ACT_*`.

| Index | Contents |
|---|---|
| 0–7 | dispatch delta per fuel, as a fraction of available capacity |
| 8 | storage power: −1 full charge, +1 full discharge |
| 9 | demand response call, mapped to 0–1 |
| 10 | renewable curtailment, mapped to 0–1 |

Non-dispatchable fuels ignore their dispatch element. The slot stays in the vector so the shape
is fixed.

**Reward** is the cost of running the grid, in pounds (contract v1.1.0):

```
reward = -(cost_gbp + penalty_gbp) / REWARD_SCALE_GBP        per half-hour step
```

| Term | Price | Kind |
|---|---|---|
| Fuel | each fuel's £/MWh (section 3) | cost |
| Carbon | £67/t: UK ETS (~£49, 2026 reference price) + Carbon Price Support (£18) | cost |
| Unserved energy | £6,000/MWh: the administrative VoLL in the Balancing and Settlement Code (consumer-survey VoLL is ~£17,000) | cost |
| Deliberate curtailment | £70/MWh, typical wind turn-down bid (2017 data; dated) | cost |
| Demand response | £300/MWh (`PRICE_DR_GBP_PER_MWH`, assumption) | cost |
| Spill (surplus with nowhere to go) | £1,000/MWh | penalty |
| Line overload | £1,000 per MW over limit, per half-hour | penalty |

`cost_gbp` is money that would really be paid. `penalty_gbp` prices things a real grid can't
sustain and which have no market price. Per MW per half-hour the ordering is:
redispatch (≤ ~£260, worst line, using real flow factors) < line overload (£1,000) < blackout (£3,000), and
deliberate curtailment (£35) < uncontrolled spill (£500). Fuel costs in section 3 are illustrative and
fuel-only; carbon is added on top. Every value lives in `schemas.py`; never hardcode them.

v1.0.0 used unit-less weights. They let a policy score well by running every plant flat out and
spilling a quarter of national demand, so they were replaced.

**`info` dict** on every step, so Leonard can render without recomputing:

```python
{
  "timestamp_utc": str,            # ISO 8601
  "zones": {zone_id: {"demand_mw", "generation_mw", "unserved_mw",
                      "cost_gbp", "carbon_t", "curtailed_mw",
                      "storage_soc", "dr_called_mw"}},
  "edges": {edge_id: {"flow_mw", "limit_mw", "loading_frac", "tripped"}},
  "totals": {"unserved_mwh", "cost_gbp", "penalty_gbp", "carbon_t", "curtailed_mwh"},
  "incidents": [ {...} ],          # active incidents, schema in section 7
}
```

---

## 7. Incidents

```python
{
  "type": "line_trip" | "generator_outage" | "wind_lull" | "demand_spike" | "interconnector_loss",
  "target": str,        # edge_id for line_trip, else zone_id
  "start_step": int,    # 0-47
  "duration_steps": int,
  "magnitude": float,   # see below
}
```

`magnitude` by type:

- `line_trip` — fraction of circuits lost, 0–1. 0.5 on a two-circuit edge halves the limit.
- `generator_outage` — fraction of that zone's dispatchable capacity lost.
- `wind_lull` — multiplier on wind output, 0–1.
- `demand_spike` — multiplier on demand, ≥ 1.
- `interconnector_loss` — fraction of `IMPORT` capacity lost.

---

## 8. The API

Leonard writes this. FastAPI. Stub responses from hour 0, real ones from hour 10.

| Method | Path | Returns |
|---|---|---|
| `GET` | `/zones` | GeoJSON FeatureCollection, `properties.zone_id` on every feature |
| `GET` | `/forecast/{zone_id}?issue_time=<iso>` | `{"zone_id", "issue_time_utc", "forecast": [[p10,p50,p90] x 48]}` |
| `GET` | `/state?t=<iso>` | the `info` dict from section 6 |
| `POST` | `/incident` | body is an incident from section 7; returns `{"ok": true, "incident_id": str}` |
| `GET` | `/compare?scenario=<name>` | see below |
| `GET` | `/scenarios` | `[{"name", "description"}]` |

`/compare` response:

```json
{
  "scenario": "b6_trip_windy_peak",
  "strategies": {
    "none":      {"unserved_mwh": 0, "cost_gbp": 0, "carbon_t": 0, "curtailed_mwh": 0},
    "optimiser": {"unserved_mwh": 0, "cost_gbp": 0, "carbon_t": 0, "curtailed_mwh": 0},
    "agents":    {"unserved_mwh": 0, "cost_gbp": 0, "carbon_t": 0, "curtailed_mwh": 0}
  }
}
```

Those three strategy keys are fixed. They are the scoreboard on the closing slide.

---

## 9. Directory layout

```
data/raw/<source>/           untouched API responses, saved before parsing
data/canonical/year=/month=/ the table in section 4
data/geo/zones.geojson       ten zone polygons, properties.zone_id
models/                      section 5
policies/                    PPO checkpoints, ppo_final.zip
scenarios/<name>.json        list of incidents + a start timestamp
results/compare.json         the /compare payload, written by the batch runner
```

---

## 10. Scenarios

Three, as files in `scenarios/`, not clicked live during the demo.

| Name | What happens |
|---|---|
| `b6_trip_windy_peak` | The whole `SSCO-NORT` boundary trips at step 34 (17:00) on a high-wind winter evening. A single circuit was not enough: with Scotland still connected, a network-blind dispatch sheds no load at all and there is no saving to demonstrate. |
| `cold_snap` | `demand_spike` 1.18 across all zones for 12 steps from step 30 |
| `nuclear_outage_low_wind` | `generator_outage` 0.9 in `EAST` plus `wind_lull` 0.25 nationally |

---

## Changelog

- **v1.0.0** — hour 0, Dhruv. Initial freeze.
- **v1.1.0** — reward rewritten as system cost in pounds; `totals` gains `penalty_gbp`.
