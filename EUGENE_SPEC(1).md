# Eugene's Spec — Forecaster and Agents

**For:** Eugene. **Written by:** Dhruv, hour 1. **Depends on:** `schemas.py`, `CONTRACT.md`.

You have two jobs. Job 1 is the demand forecaster. Job 2 is the reinforcement-learning agents.
They are sequential, and Job 2 can't start until my simulator runs at about hour 12.

## How to use this document

Paste this whole file into your AI as context, along with `schemas.py`. Then prompt it one
numbered section at a time — not the whole spec at once. There's a starter prompt at the end.

Two rules for anything the AI writes:

1. **Never let it invent names.** Zone IDs, fuel names, column names and array indices all come
   from `schemas.py` via `import schemas`. If the AI types `"London"` or `"Scotland"` or
   `"temperature_c"`, it has guessed, and the guess is wrong.
2. **Every section below has acceptance tests.** Make the AI write them as real assertions and run
   them. A section isn't done until its tests pass.

---

# Part 1 — The forecaster (hours 2–12)

## 1.1 What it is

Given a zone and an issue time, predict that zone's electricity demand for the next 48 half-hours,
as three quantiles: P10, P50, P90. One model serves all ten zones.

## 1.2 Input

One parquet file. Start with the stub, swap in Ranya's real file when it lands — same schema, so
no code changes.

```
data/canonical/_fake.parquet
```

Columns, exactly (`schemas.CANONICAL_COLUMNS`):

| Column | Type | Meaning |
|---|---|---|
| `zone_id` | string | one of `schemas.ZONE_ORDER` |
| `timestamp_utc` | timestamp[us, UTC] | **start** of the half-hour interval |
| `demand_mw` | float32 | zone demand; null where unknown |
| `temp_c` | float32 | 2 m air temperature |
| `wind_ms` | float32 | 100 m wind speed |
| `solar_wm2` | float32 | shortwave radiation |
| `weather_issue_time_utc` | timestamp[us, UTC] | when that weather was **forecast** |
| `quality_flag` | uint8 | bitfield, `schemas.QF` |
| `is_estimated` | bool | true when demand was split from national |

## 1.3 The time convention — read this twice

This is where forecasting code usually goes wrong.

- A row's `timestamp_utc` is the **start** of its half-hour.
- At issue time `T`, the interval starting at `T` has **not finished**. The most recent demand you
  know is the interval starting at `T − 30min`.
- `predict(zone, T)` returns 48 rows. **Row `i` is the interval starting at `T + i × 30min`.**
- Define `h = i + 1`, so `h` runs 1 to 48. `h` is a model feature.

**The leakage rule, in one line:**

> Every feature must derive from a `timestamp_utc` of `T − 30min` or earlier — except weather
> features, which must come from rows whose `weather_issue_time_utc` is `T` or earlier.

A useful consequence: for every `h` in 1..48, the target interval's **same half-hour yesterday**
is always available. At `h = 48` the target starts at `T + 23.5h`, and 24 hours before that is
exactly `T − 30min`, the last interval you know. So `lag_1d` is never a leak, at any horizon.

## 1.4 Features

Let `target_time = T + (h−1) × 30min`.

**Target-aligned lags** (relative to `target_time`, all safely in the past per 1.3):

| Feature | Definition |
|---|---|
| `lag_1d` | `demand_mw` at `target_time − 24h` |
| `lag_2d` | `demand_mw` at `target_time − 48h` |
| `lag_1w` | `demand_mw` at `target_time − 168h` |
| `lag_2w` | `demand_mw` at `target_time − 336h` |
| `same_hh_mean_3w` | mean of `lag_1w`, `lag_2w`, and `target_time − 504h` |

`lag_1w` on its own is the baseline you have to beat. Keeping it as a feature is deliberate: the
model should learn when to trust it and when to depart from it.

**Issue-time features** (relative to `T`, identical across all 48 horizons):

| Feature | Definition |
|---|---|
| `last_known` | `demand_mw` at `T − 30min` |
| `last_known_2` | `demand_mw` at `T − 60min` |
| `last_known_3` | `demand_mw` at `T − 90min` |
| `roll_mean_2h` | mean of the last 4 known intervals |
| `roll_mean_24h` | mean of the last 48 known intervals |
| `roll_std_24h` | std of the last 48 known intervals |
| `roll_mean_7d` | mean of the last 336 known intervals |
| `recent_vs_week` | `roll_mean_24h / roll_mean_7d` |

**Calendar features** (of `target_time`, converted to `Europe/London` for the human-facing ones):

| Feature | Definition |
|---|---|
| `hh_of_day` | 0–47, local |
| `dow` | 0–6, local |
| `is_weekend` | bool |
| `month` | 1–12 |
| `is_bank_holiday` | GB bank holidays; use the `holidays` package, `country="GB"` |
| `is_dst_change_day` | from `quality_flag & schemas.QF.DST_BOUNDARY` |
| `tod_sin`, `tod_cos` | `sin/cos(2π × hh_of_day / 48)` |
| `doy_sin`, `doy_cos` | `sin/cos(2π × day_of_year / 365)` |

**Weather features** (of `target_time`, from a forecast issued at or before `T`):

| Feature | Definition |
|---|---|
| `temp_c`, `wind_ms`, `solar_wm2` | as given |
| `hdd` | `max(0, 15.5 − temp_c)` |
| `cdd` | `max(0, temp_c − 20.0)` |
| `temp_roll_24h` | mean `temp_c` over the 48 intervals up to `target_time` |
| `temp_delta_24h` | `temp_c` minus `temp_c` at `target_time − 24h` |

`temp_roll_24h` matters more than people expect. Buildings have thermal mass, so demand responds
to the last day of weather, not just this half-hour.

**Horizon and zone:**

| Feature | Definition |
|---|---|
| `h` | 1–48 |
| `zone_id` | pandas `category` dtype, passed to LightGBM as a categorical feature |

## 1.5 Three design decisions — don't let the AI change these

1. **`h` is a feature, not 48 separate models.** One model covers every horizon. The alternative
   is 48 × 3 = 144 boosters, which you don't have time for and which fits worse per-horizon anyway.
2. **`zone_id` is a categorical feature, not 10 separate models.** One global model learns shared
   structure across zones and still differentiates them. With 10 zones this is both less code and
   more accurate.
3. **Direct multi-horizon, never recursive.** Do not feed a prediction back in as an input for the
   next step. Errors compound and the 48-step-ahead forecast becomes noise.

## 1.6 Building the training table

Rows are `(zone_id, issue_time, h)`. Dense issue times explode the row count, so stage it:

- **First pass, to get the pipeline running:** issue times at 00:00, 06:00, 12:00, 18:00 UTC.
- **Then densify:** every 2 hours over the full history, plus every 30 minutes over the last 60
  days. Real data at 2-hourly issue times is roughly 4 M rows for two years, which LightGBM
  handles fine.

**Row exclusion.** A row is dropped from training and scoring if its **target** has
`quality_flag & schemas.QF_UNSCORABLE` set, or if `demand_mw` is null. Those same rows may still
be used as *feature sources* — a flagged interval is fine as a lag input, it just can't be a target.
`schemas.is_scorable(flag)` does this check.

## 1.7 Splits

Rolling origin, by time, never shuffled.

```
test       = last 14 days of the data
validation = the 14 days before that
train      = everything before that
```

Split on `issue_time`, not on `target_time` — otherwise a late issue time in train predicts into
the validation window and you've leaked.

**If the AI writes `train_test_split(..., shuffle=True)` or any `KFold`, stop and fix it.** That
single line invalidates every number you report.

## 1.8 Training

Three LightGBM models, identical except `alpha`:

```python
params = dict(
    objective="quantile",
    alpha=<0.1 | 0.5 | 0.9>,
    n_estimators=3000,
    learning_rate=0.05,
    num_leaves=128,
    min_child_samples=50,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    max_bin=255,
    n_jobs=-1,
)
```

Early stopping on the validation set, 100 rounds patience, metric `quantile`.

**Optuna, after a plain run works.** 30 trials, parallel across the mainframe's cores. Tune
`learning_rate`, `num_leaves`, `min_child_samples`, `subsample`, `colsample_bytree`, `reg_lambda`.
Optimise **validation pinball loss averaged over the three quantiles**, not P50 MAE — otherwise you
tune the median and leave the intervals miscalibrated.

## 1.9 Evaluation

Compute on the test set and write every number into `models/metadata.json`.

| Metric | How |
|---|---|
| `baseline_mae_mw` | MAE of `lag_1w` used directly as the prediction |
| `mae_mw` | MAE of P50 |
| `wape` | `Σ|y − ŷ| / Σ|y|` |
| `mae_by_horizon` | MAE of P50 at h = 1, 4, 12, 24, 48 |
| `mae_peak` | MAE of P50 on the top 10% of observed demand |
| `pinball_loss` | mean over the three quantiles |
| `coverage_80` | fraction of actuals inside [P10, P90] |

`coverage_80` should land near 0.80. If it's 0.95 the intervals are too wide and useless for the
agents; if it's 0.6 they're too narrow and the agents will be blindsided. Report it honestly either
way — a calibration number judges can check beats a suspiciously small MAE.

**Never use MAPE.** Zone demand can approach zero and MAPE explodes.

**SHAP** on the P50 model: a global importance bar chart, plus a function returning the top 3
contributing features for one prediction. Leonard displays the latter.

## 1.10 Outputs

Files:

```
models/lgbm_q10.txt         booster, alpha=0.1   (use booster.save_model)
models/lgbm_q50.txt         booster, alpha=0.5
models/lgbm_q90.txt         booster, alpha=0.9
models/feature_names.json   ordered list of feature columns, exactly as trained
models/metadata.json        every metric in 1.9, plus train/val/test date ranges
models/shap_importance.png  global SHAP bar chart
```

And `forecast.py`, exposing exactly this:

```python
def predict(zone_id: str, issue_time_utc: datetime) -> list[list[float]]:
    """48 rows of [p10, p50, p90] in MW. Row i is the half-hour starting at
    issue_time_utc + i*30min."""

def predict_all(issue_time_utc: datetime) -> list[list[list[float]]]:
    """10 x 48 x 3, zones in schemas.ZONE_ORDER order."""
```

Plain nested Python lists, not numpy arrays — Leonard serialises these straight to JSON.

Enforce `p10 <= p50 <= p90` before returning. Independently trained quantile models cross
sometimes; sort the three values per row. `schemas.validate_forecast()` will catch it if you don't.

## 1.11 Acceptance tests — Part 1

```python
import schemas as S
from datetime import datetime, timezone
import forecast, json

T = datetime(2026, 11, 1, 17, 0, tzinfo=timezone.utc)

# shape and ordering
fc = forecast.predict("LOND", T)
S.validate_forecast(fc)                       # 48 rows, quantiles ordered

allz = forecast.predict_all(T)
assert len(allz) == S.N_ZONES
for row in allz:
    S.validate_forecast(row)

# every zone id works
for z in S.ZONE_ORDER:
    S.validate_forecast(forecast.predict(z, T))

# JSON-serialisable, so Leonard's API doesn't need a converter
json.dumps(fc)

# beats the baseline
m = json.load(open("models/metadata.json"))
assert m["mae_mw"] < m["baseline_mae_mw"], "model is worse than same-half-hour-last-week"

# intervals are calibrated
assert 0.70 <= m["coverage_80"] <= 0.90, f"coverage {m['coverage_80']} is miscalibrated"

# error grows with horizon — if it doesn't, something is leaking
h = m["mae_by_horizon"]
assert h["1"] < h["48"], "no horizon degradation: suspect leakage"

# magnitudes are physical
assert 500 < fc[0][1] < 12000, f"P50 of {fc[0][1]} MW is not a plausible zone demand"
```

That `h["1"] < h["48"]` assertion is the most valuable one here. A model that predicts 24 hours
ahead as accurately as 30 minutes ahead has seen the future somewhere in the feature pipeline.

**Note on the stub data:** `_fake.parquet` holds 21 days, so `lag_2w` is thin and
`same_hh_mean_3w` is barely computable. Expect poor accuracy on the stub — you're testing that the
pipeline runs, not that the model is good. Judge accuracy only on Ranya's real file.

---

# Part 2 — The agents (hours 12–19)

Blocked until my Gym env lands. Build Part 1 fully first.

## 2.1 What the env gives you

```python
import grid_env
env = grid_env.GridEnv()
obs, info = env.reset(seed=0)
obs, reward, terminated, truncated, info = env.step(action)
```

- `obs` — `float32`, shape `(10, 52)`. One row per zone, in `schemas.ZONE_ORDER`.
- `action` — `float32`, shape `(10, 11)`, every element in `[-1, 1]`.
- One step is one half-hour. An episode is 48 steps.
- `reward` — scalar, summed across zones. Heavily negative; near zero is good.

Observation and action index constants are `schemas.OBS_*` and `schemas.ACT_*`. Full layouts are in
`CONTRACT.md` sections 6. You don't need to interpret them to train — but you do need them to debug,
and `OBS_FC_P50` at indices 4–7 is where my env writes *your* forecast. That's the link between
your two jobs: the agents see the P50 and P90 predictions and act before an incident, not just
after.

## 2.2 The policy architecture

Stable-Baselines3 PPO. Two plans; do A first.

**Do not flatten the observation.** SB3 accepts the `(10, 52)` Box and the `(10, 11)` action box
natively; its `FlattenExtractor` handles the reshape internally. `model.predict(obs)` takes
`(10, 52)` and returns `(10, 11)`. Passing `obs.flatten()` raises `ValueError: Unexpected
observation shape (520,)`. Verified against stable-baselines3 2.9.2.

**Plan A — centralised, works immediately.** `PPO("MlpPolicy", env)` with
`policy_kwargs=dict(net_arch=[256, 256])`. Nothing else. One policy controls all ten zones. It is
not really multi-agent, so describe it as a central controller, not as agents.

**Plan B — shared per-zone policy, the better story.** Custom feature extractor that takes the
`(10, 52)` observation, applies one shared MLP to each zone's row, and concatenates. Every zone
runs the same weights on its own local observation, which is genuine parameter sharing across
agents.

Upgrade A to B only once A is converging. If you're still on A at hour 17, ship A.

## 2.3 PPO configuration

```python
PPO(
    policy,
    env,                       # SubprocVecEnv, n_envs = min(os.cpu_count(), 32)
    n_steps=256,               # per env, so 256 * n_envs per rollout
    batch_size=4096,
    n_epochs=10,
    learning_rate=3e-4,
    gamma=0.99,
    gae_lambda=0.95,
    clip_range=0.2,
    ent_coef=0.005,
    vf_coef=0.5,
    max_grad_norm=0.5,
)
```

Wrap the vec env in `VecNormalize(norm_obs=True, norm_reward=True, clip_obs=10.0)`.

**Save the VecNormalize statistics.** `vec_env.save("policies/vecnormalize.pkl")`. If you lose them
the policy receives differently-scaled observations at inference and behaves like noise. This is the
single most common way a working PPO run ends up useless, and it fails silently.

Total budget: 2–5 M steps. With 32 parallel envs that's comfortably inside your window.

## 2.4 Incident sampling — one thing to get right

Randomise incidents every episode, or the policy memorises one scenario and collapses in the demo.
But **do not sample edges uniformly.**

`NSCO` connects to the rest of the grid by a single corridor. Trip it and North Scotland islands
entirely, with about 6000 MW of wind against 1500 MW of demand. There is no rerouting solution —
the agents can only curtail. Train uniformly and a large share of episodes are unsolvable, which
teaches the policy that nothing it does matters.

Weight `line_trip` targets toward `schemas.B6_EDGE` and the Midlands corridors
(`YORK-MIDL`, `MIDL-LOND`, `MIDL-EAST`, `EAST-LOND`, `LOND-SOUT`). Give `NSCO-SSCO` a small weight,
not zero — the policy should still handle it, just not be dominated by it.

Mix the five incident types roughly evenly, plus about 20% of episodes with no incident at all so
the policy learns normal economic dispatch too.

## 2.5 Evaluation

Every 100k steps, checkpoint and evaluate against the three scenarios in `scenarios/`, comparing
your policy to my optimiser. The optimiser is mine to build; you call it through this interface,
which I guarantee:

```python
import agents_baseline

opt = agents_baseline.OptimiserAgent()         # least-cost LP dispatch
act = opt.act(obs, info)                       # (10, 52) + info dict -> (10, 11) action

noop = agents_baseline.NoOpAgent()             # the "none" strategy: do nothing
```

Both expose the same `.act(obs, info) -> action` signature, so one eval loop drives all three
strategies — mine, yours, and nothing. Write:

```json
{"scenario": "b6_trip_windy_peak",
 "strategies": {
   "none":      {"unserved_mwh": 0, "cost_gbp": 0, "carbon_t": 0, "curtailed_mwh": 0},
   "optimiser": {...},
   "agents":    {...}}}
```

to `results/compare.json`. Strategy keys are fixed: `schemas.STRATEGIES`.

You must be able to answer, at any moment after hour 14, whether the agents currently beat the
optimiser. If they don't by hour 18, we ship the optimiser and say so.

## 2.6 Outputs

```
policies/ppo_final.zip         the trained policy
policies/vecnormalize.pkl      the observation statistics — do not forget this
policies/checkpoints/          intermediate saves
results/compare.json           the scoreboard
results/training_curve.png     reward against steps
```

## 2.7 Acceptance tests — Part 2

```python
import schemas as S, numpy as np
from stable_baselines3 import PPO
import grid_env

env = grid_env.GridEnv()
obs, info = env.reset(seed=0)
assert obs.shape == (S.N_ZONES, S.OBS_DIM)

model = PPO.load("policies/ppo_final.zip")

# a loaded policy produces legal actions -- obs is passed UNFLATTENED
a, _ = model.predict(obs, deterministic=True)
S.validate_action(a)

# a full episode runs without error
obs, info = env.reset(seed=1)
total = 0.0
for _ in range(S.STEPS_PER_EPISODE):
    a, _ = model.predict(obs, deterministic=True)
    obs, r, term, trunc, info = env.step(a)
    total += r
    if term or trunc:
        break
assert np.isfinite(total)

# the policy beats doing nothing
import json
c = json.load(open("results/compare.json"))["strategies"]
assert c["agents"]["unserved_mwh"] <= c["none"]["unserved_mwh"]
```

---

# Things not to do

Every one of these is a mistake AI-generated code makes by default.

1. **No random or k-fold splits.** Time-ordered only, split on `issue_time`.
2. **No observed weather where a forecast is required.** Respect `weather_issue_time_utc`.
3. **Sort by `(zone_id, timestamp_utc)` before any rolling or lag operation.** Unsorted groupby
   shifts produce silently wrong features.
4. **Use `.groupby("zone_id").shift()`, never a bare `.shift()`.** A bare shift leaks one zone's
   demand into another's lag at every zone boundary.
5. **Don't train or score on rows whose target is flagged** `MISSING` or `INTERPOLATED`.
6. **Don't forget `vecnormalize.pkl`.**
7. **Don't sample `line_trip` edges uniformly.** See 2.4.
8. **Don't hardcode zone IDs, fuel names, column names or array indices.** Import from `schemas`.
9. **Don't use MAPE.**
10. **Don't build per-zone or per-horizon models.** One model, `zone_id` categorical, `h` a feature.
11. **Don't return numpy arrays from `predict()`.** Plain lists.
12. **Don't tune on P50 MAE alone.** Average pinball loss over the three quantiles.

---

# Starter prompt for your AI

> I'm building a half-hourly electricity demand forecaster for a hackathon. I'm attaching two
> files: `EUGENE_SPEC.md` (the spec) and `schemas.py` (the shared contract — every zone ID, column
> name and array index comes from here, never invent your own).
>
> Work through Part 1 of the spec only. Do not start Part 2.
>
> Build it in this order, and stop after each step so I can run it:
>
> 1. `features.py` — load `data/canonical/_fake.parquet` and build the training table from spec
>    section 1.4, with issue times at 00:00/06:00/12:00/18:00 UTC only. Respect the leakage rule in
>    1.3 exactly. Include a `check_no_leakage()` function that asserts every feature's source
>    timestamp is at or before `T − 30min`, weather excepted.
> 2. `baseline.py` — predict using `lag_1w` alone and print its MAE. This is the number to beat.
> 3. `train.py` — the three LightGBM quantile models from 1.8, time-ordered splits from 1.7, saving
>    the files in 1.10.
> 4. `evaluate.py` — every metric in 1.9, written to `models/metadata.json`.
> 5. `forecast.py` — the exact two-function interface in 1.10.
> 6. The acceptance tests in 1.11, as a runnable pytest file.
>
> Before writing each file, tell me which of the twelve mistakes in "Things not to do" that file is
> most at risk of, and how you're avoiding it.

That last instruction is worth keeping. It makes the model state its assumptions before it commits
to them, which is when they're cheap to correct.
