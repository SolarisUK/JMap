# JMap

**Stress-testing Great Britain's grid in worlds that haven't happened yet.**
Team Solaris · 4 builders · 24 hours · Warwick hackathon, theme *New Worlds*

| B6 outage on a real winter evening (14 Dec 2025, 17:00) | No response | **JMap optimiser** |
|---|---:|---:|
| Unserved demand | 63,917 MWh | **0 MWh** |
| Operating cost | £388.5M | **£17.4M (−96%)** |
| Line overloads | 105,886 MW-steps | **0** |

| Forecaster, real test set (Jul–Dec 2025, 8,785 forecasts, scored once) | |
|---|---:|
| National demand error (P50 MAPE) | **4.15%** vs 7.37% persistence |
| P10–P90 coverage | **78.7%** (target 80%) |

## Inspiration

Britain's grid is entering a new world. Coal is gone: the last coal plant, Ratcliffe-on-Soar, closed in 2024. Wind and solar now do the heavy lifting, but they are driven by the weather and often far from where people live, with much of the wind in Scotland and most of the demand in the south. Demand is rising again as heat pumps, electric vehicles and data centres come onto the grid, and since the 2022 gas crisis, energy security has become a geopolitical question, not just an engineering one.

Having enough electricity doesn't always mean you can get it to the right place. That led us to the B6 transmission boundary between Scotland and England, and a question recorded history can't answer: what happens if it is lost on a windy winter evening? For us, *New Worlds* meant exploring exactly those scenarios: take a real day, introduce a failure that never happened, and measure how different decisions change the outcome.

## What it does

- **Forecasts** demand for 10 GB zones, 48 half-hours ahead, as P10 / P50 / P90.
- **Simulates** the network with DC power flow over 14 transmission corridors, 8 generation types and battery storage. It injects line trips, plant outages, wind lulls and demand spikes, including the grid splitting into islands.
- **Responds** with a receding-horizon linear programme that re-dispatches generation, uses storage and calls demand response within every line limit, at about 13 ms per decision.
- **Shows it** in a dashboard that plays the same incident side by side: a network-blind baseline vs our optimiser. Alongside it: every GB generating site from the DESNZ registers, live Elexon interconnector flows, and local-authority energy statistics.

## B6 is the demo case; any scenario runs on demand

We chose a full B6 outage as the showcase because it is the clearest example of supply being in the wrong place: Scotland is cut off with spare wind, while England and Wales run short. But nothing about it is hard-coded. A scenario is a small JSON file (`dhruv_latest/scenarios/`): pick any real day from 7 Mar 2024 – 31 Dec 2025 and any incident, then one command reruns the simulator and optimiser and refreshes the dashboard, within minutes on a laptop. The B6 start date itself was picked by a script that searched the real data for the windiest, highest-demand winter evening.

## Results (real data)

| Scenario | No response: unserved | Optimiser: unserved | No response: cost + penalties | Optimiser: cost + penalties |
|---|---:|---:|---:|---:|
| B6 full outage, 14 Dec 2025 | 63,917 MWh | **0 MWh** | £593.7M | **£17.4M** |
| Cold snap +18% demand, 10 Jan 2025 | 10,592 MWh | **3,052 MWh (−71%)** | £139.4M | **£96.0M** |
| Eastern plant outage + low wind, 9 Nov 2024 | 0 MWh | 0 MWh | £50.0M | **£49.5M** |
| Random real days (mean of 8) | 0 MWh, 14,484 MW-steps overload | **0 MWh, 0 overload** | £46.3M | **£29.8M** |

In the cold snap there isn't enough capacity to serve everyone, so some shedding is unavoidable; the optimiser sheds the minimum. We also gave the optimiser a *perfect* demand forecast: cost improved by under 0.5%, because this model has no ramp or start-up constraints. Forecasting earns its value in day-ahead unit commitment, the next layer we would add.

**Forecast accuracy.** Chronological split: train 7 Mar 2024 – 31 Mar 2025, validation Apr – Jun 2025, test Jul – Dec 2025, scored once. Routing chosen on real validation: persistence for h1–2, LightGBM for h3–48.

| Horizon | Hybrid P50 MAE (MW) | Persistence | Weekly lag |
|---|---:|---:|---:|
| h1 | 36.0 | 36.0 | 201.5 |
| h4 | 80.6 | 94.7 | 201.5 |
| h12 | 106.7 | 184.7 | 201.5 |
| h24 | 114.4 | 212.5 | 201.4 |
| h48 | 112.6 | 206.1 | 201.0 |
| **Overall** | **107.0** | 189.5 | 201.3 |

National P50 MAPE **4.15%** (persistence 7.37%, weekly 7.80%). Coverage **78.7%**, with intervals recalibrated causally on completed outcomes only (68% with static calibration).

| Walk-forward retrain | Window | Hybrid MAE (MW) | Persistence MAE (MW) |
|---|---|---:|---:|
| 1 Jul 2025 | Jul–Aug | 105.0 | 176.9 |
| 1 Sep 2025 | Sep–Oct | 102.1 | 201.2 |
| 1 Nov 2025 | Nov–Dec | 115.0 | 190.5 |

## How we built it

- **A contract first.** `dhruv_latest/schemas.py` (v1.1.0) fixed zones, edges, fuels, units, the observation `(10, 52)` and action `(10, 11)` shapes, and the reward in pounds. JSON stubs let all four of us build in parallel from hour 0.
- **Synthetic first, then real.** We built and tested against a synthetic generator with the same schema while the real dataset was assembled overnight, then reran everything on real data.
- **Real data ([`data_pipeline/`](data_pipeline/)).** NESO demand and Elexon generation, with archived day-ahead weather forecasts from the Open-Meteo Previous Runs API (never observed weather): 7 Mar 2024 – 31 Dec 2025, 319,200 zone-half-hours, no gaps. Zonal demand is a temperature-adjusted allocation of national demand.
- **Forecaster ([`forecaster/`](forecaster/)).** Persistence for the first hour, LightGBM quantile boosters beyond, chosen per horizon on validation. Features: recent demand, daily and weekly lags, calendar, weather forecast vintages. Demand known only up to T − 30 min.
- **Simulator (`dhruv_latest/grid_env.py`).** DC power flow `f = b(θi − θj)`; partial trips scale susceptance; each electrical island balances on its own.
- **Optimiser (`dhruv_latest/agents_baseline.py`, `dc-lp-v2`).** Sparse LP over the next 8 half-hours (SciPy / HiGHS) minimising fuel + carbon (£67/t) + demand response (£300/MWh) + curtailment (£70/MWh) + value of lost load (£6,000/MWh), under hard line limits, nodal balance and battery constraints. Executes the first step, then replans.
- **Dashboard (`UI/`).** Buildless JavaScript, served by FastAPI (`api.py`) from precomputed replays in `stubs/`.

## Challenges

- **Data leakage:** we replaced near-observed weather with archived day-ahead forecasts, and caught a 30-minute timestamp shift.
- **Islanding:** our first solver gave unphysical flows when the grid split; we rewrote it as a per-island DC solve.
- **RL vs optimisation:** residual PPO on top of the LP won 0 of 20 paired seeds and raised unserved energy from 0.003 to 43.5 MWh, so we cut it.
- **Synthetic data hides things:** our first generator lacked persistence, which made a horizon check meaningless until fixed.
- **Costs that looked free:** on real data the LP treated demand response and curtailment as free; pricing them in cut cost in every scenario.
- **Overconfident uncertainty:** static calibration gave 68% coverage; rolling causal recalibration brought it to 78.7%.

## Run it

```sh
pip install numpy scipy pandas pyarrow gymnasium fastapi uvicorn lightgbm   # or use pyproject.toml

# rerun the scenarios through the simulator and optimiser, refreshing the dashboard replays
python -B UI/scripts/export-api-stubs.py --backend-root dhruv_latest

# serve and open the dashboard
uvicorn api:app --port 8000
python -m http.server 8080 --directory UI    # then visit http://localhost:8080/operations.html
```

Data validator: `cd dhruv_latest && python3 -I ../data_pipeline/check_parquet.py data/canonical/real.parquet`. Tests: `node --test UI/tests/*.test.cjs`, and `python -B UI/tests/api-replay.test.py` with the API running. Hosting: Vercel-ready, see [`UI/VERCEL.md`](UI/VERCEL.md). UI detail: [`UI/README.md`](UI/README.md).

## Repository layout

```
dhruv_latest/     backend: contract, simulator, LP optimiser, scenarios, scripts, real data
forecaster/       probabilistic demand forecaster and real-data evaluation
data_pipeline/    NESO, Elexon and Open-Meteo pulls, zonal allocation, canonical build, validation
UI/               dashboard, exporter, tests
api.py, stubs/    FastAPI server and the replays it serves
```

## Limits

A lossless 10-zone DC approximation: no AC voltage, reactive power, losses or stability. Zonal demand is estimated from national data. The LP plans on a deterministic forecast; optimising over the P10–P90 range is next. Results describe decisions within this model, not operational performance on the real GB grid.
