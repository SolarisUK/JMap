# Eugene's Runbook

Stage by stage, with the prompt to paste at each one. Times are hours from when you start, not
clock times. Attach `EUGENE_SPEC.md` and `schemas.py` to your AI session once at the start and
leave them attached; each stage says what else to add.

**Read this first:** stage 1 is a PPO smoke test, before any forecasting work. That is deliberate.
Whether PPO converges on this problem is the single biggest unknown in the project, the simulator
already exists, and the test needs no data from anyone. Answering it at hour 1 means we can still
change approach. Answering it at hour 16 means we cannot.

| Stage | Hours | What | Gate |
|---|---|---|---|
| 0 | 0:00–0:20 | Setup and verify | `grid_env` runs |
| 1 | 0:20–1:15 | **PPO smoke test** | Does reward improve at all? |
| 2 | 1:15–1:30 | Launch a long background PPO run on the stub | Uses the mainframe while you do stage 3 |
| 3 | 1:30–3:00 | Feature pipeline | No-leakage check passes |
| 4 | 3:00–3:30 | Baseline | A single MAE number to beat |
| 5 | 3:30–5:30 | LightGBM quantiles | Beats the baseline |
| 6 | 5:30–6:30 | Evaluation | `metadata.json` written, coverage near 0.80 |
| 7 | 6:30–7:00 | `forecast.py` | Acceptance tests pass |
| 8 | 7:00–8:30 | Optuna and SHAP | Background sweep running |
| 9 | 8:30–9:30 | Wire your forecaster into the env | Forecast slots carry your P50 |
| 10 | 10:00–16:00 | Real PPO run on the real env | Beats the optimiser, or we ship the optimiser |
| 11 | 16:00–18:00 | `results/compare.json` | Scoreboard complete |

---

## Stage 0 — Setup (20 min)

```bash
git pull
pip install lightgbm optuna shap holidays pyarrow pandas gymnasium stable-baselines3
nproc                                   # note this number, you need it in stage 2
python3 schemas.py                      # must print "contract v1.0.0 OK"
python3 scripts/compare_agents.py       # must print "6/6 scenarios"
```

If `data/canonical/_fake.parquet` is missing:

```bash
python3 -I scripts/make_fake_canonical.py
```

No prompt for this stage. Don't let an AI near the setup.

---

## Stage 1 — PPO smoke test (55 min)

The goal is **not** a good policy. It is a yes or no answer to "does the reward curve move".

> Attach: `grid_env.py`, `agents_baseline.py`.
>
> I'm running a 24-hour hackathon on grid management. `grid_env.py` is a Gymnasium environment,
> already working. I need a PPO smoke test that answers one question: does the reward improve at
> all over a short run? This is throwaway diagnostic code, not the real training script.
>
> Write `smoke_ppo.py` that:
>
> 1. Builds a `SubprocVecEnv` of `grid_env.GridEnv` with `n_envs` from a `--n-envs` argument,
>    wrapped in `VecNormalize(norm_obs=True, norm_reward=True, clip_obs=10.0)`.
> 2. Measures the mean episode reward of `agents_baseline.NoOpAgent` and
>    `agents_baseline.OptimiserAgent` over 20 episodes. These are the two lines to beat.
> 3. Trains `PPO("MlpPolicy", env, policy_kwargs=dict(net_arch=[256,256]), n_steps=256,
>    batch_size=1024, device="cpu")` for a `--steps` argument, default 100000.
> 4. Every 10000 steps, evaluates the current policy over 10 fresh episodes and prints
>    `steps, mean_reward, noop_reward, optimiser_reward` as one line of a table.
> 5. Saves a matplotlib plot of those three series to `results/smoke_curve.png`.
>
> Critical, and the mistake I expect you to make: the observation space is `Box(10, 52)` and the
> action space is `Box(10, 11)`. SB3 handles both natively. Do NOT flatten the observation.
> `model.predict(obs)` takes `(10, 52)` and returns `(10, 11)`. Passing `obs.flatten()` raises
> `ValueError: Unexpected observation shape (520,)`. I have verified this against
> stable-baselines3 2.9.2.
>
> Before you write the file, tell me in two sentences how you're evaluating the policy without
> contaminating the `VecNormalize` running statistics.

Run it:

```bash
mkdir -p results
python3 smoke_ppo.py --n-envs $(nproc) --steps 100000
```

**Reading the result.** You are looking for the curve to rise, not for the policy to win. Dhruv
already ran this on 2 cores so you know what normal looks like:

```
noop          -3,261,291
optimiser     -2,012,634
   steps       policy
       0     -73,741,338     <- untrained, ~20x worse than doing nothing
   15000     -70,234,542
   30000     -50,882,176
   45000     -41,636,696
   60000     -36,862,009
```

So **at 100k steps you should still be several times worse than `NoOpAgent`, and that is fine.**
A random policy throws away enormous amounts of energy, so it starts from a very deep hole. What
matters is that the number improves at every evaluation. It needs a few million steps to become
competitive, which is minutes on the mainframe and the reason stage 2 exists.

| What you see | What it means | What to do |
|---|---|---|
| Improves at every evaluation, still below `NoOpAgent` | **The expected result.** PPO learns this | Go to stage 2 |
| Improves and reaches `NoOpAgent` inside 100k steps | Better than expected | Go to stage 2 |
| Flat or falling across all evaluations | Something is wrong, not just slow | 20 minutes on reward scale, then see below |
| Crash in a worker | Usually an illegal action | Print the action, check `validate_action` |

Throughput for planning: 619 steps/sec on 2 cores. Scale by your core count — 3M steps should be
well under an hour on the mainframe.

**If it's flat:** try `ent_coef=0.01` and `learning_rate=1e-3`, and try `norm_reward=False` — the
reward is dominated by a large negative cost term and normalising it can flatten the signal. If
20 minutes of that changes nothing, **stop and tell Dhruv**. We ship the optimiser as the response
layer, you spend your whole day on the forecaster, and we lose nothing because it is hour 1.

---

## Stage 2 — Launch the long background run (15 min)

Whatever stage 1 showed, start a long run now. It costs you nothing to let the mainframe work
while you write feature code, and by stage 9 you will know what the stub env can reach.

> Attach: `smoke_ppo.py` (the file you just made).
>
> Turn `smoke_ppo.py` into `train_ppo.py`, a real training script:
>
> - arguments `--steps` (default 3000000), `--n-envs`, `--out` (default `policies/`)
> - `CheckpointCallback` saving to `policies/checkpoints/` every 100000 steps
> - on completion, save `policies/ppo_final.zip` AND
>   `vec_env.save("policies/vecnormalize.pkl")`
> - append every evaluation row to `results/training_log.csv` so I can plot it later
> - log to tensorboard under `results/tb/`
>
> The `vecnormalize.pkl` save is not optional. Without it the policy receives differently scaled
> observations at inference and behaves like noise, and it fails silently. Put it in a `finally`
> block so it is written even if the run is interrupted.

Then:

```bash
mkdir -p policies/checkpoints results
nohup python3 train_ppo.py --steps 3000000 --n-envs $(nproc) > results/train_stub.log 2>&1 &
echo $! > results/train_stub.pid
```

Check on it occasionally with `tail -5 results/train_stub.log`. Do not babysit it.

---

## Stage 3 — Feature pipeline (90 min)

> Attach: `EUGENE_SPEC.md`, `schemas.py`.
>
> Build `features.py` per section 1.4 of the spec. Read section 1.3 twice before you write
> anything — the time convention is where this normally goes wrong.
>
> Requirements:
>
> - Load `data/canonical/_fake.parquet`.
> - Build a table of `(zone_id, issue_time, h)` rows, `h` from 1 to 48.
> - Issue times: for now only 00:00, 06:00, 12:00 and 18:00 UTC. A `--dense` flag switches to
>   every 2 hours.
> - Every feature in section 1.4, with exactly the names given in the tables.
> - Drop rows whose target has `quality_flag & schemas.QF_UNSCORABLE` or a null `demand_mw`.
>   Those rows are still allowed as *feature sources* — only as targets are they excluded.
> - `zone_id` as a pandas `category` dtype.
> - A function `check_no_leakage(df)` that asserts, for every row, that each lag feature's source
>   timestamp is at or before `issue_time - 30min`, and that weather comes from a row whose
>   `weather_issue_time_utc` is at or before `issue_time`. Make it raise with the offending row
>   when it fails.
>
> Four specific things to get right, which are the common failure modes:
>
> 1. Sort by `["zone_id", "timestamp_utc"]` before any shift or rolling operation.
> 2. Use `.groupby("zone_id").shift()`, never a bare `.shift()`. A bare shift leaks one zone's
>    demand into another zone's lag at every zone boundary.
> 3. Target-aligned lags (`lag_1d`, `lag_1w`, ...) are relative to `target_time`. Issue-time
>    features (`last_known`, `roll_mean_24h`, ...) are relative to `issue_time`. These are
>    different anchors; don't collapse them into one.
> 4. Calendar features use `Europe/London` local time, everything else stays UTC.
>
> Before writing the file, state which of the twelve mistakes in the spec's "Things not to do"
> section this file is most at risk of, and how you're avoiding it.

Verify:

```bash
python3 -c "
import features
df = features.build()
features.check_no_leakage(df)
print(df.shape)
print(df.columns.tolist())
print(df.groupby('h').size().head())
"
```

Expect roughly 10 zones × 4 issue times/day × 21 days × 48 horizons ≈ 40k rows, minus exclusions.

---

## Stage 4 — Baseline (30 min)

> Attach: `features.py`.
>
> Write `baseline.py`. It predicts `lag_1w` directly as the forecast and reports MAE, WAPE, and
> MAE broken out by horizon at h = 1, 4, 12, 24, 48, on the test split defined in spec section 1.7
> (last 14 days by issue time). Print it as a small table and save it to
> `results/baseline.json`.
>
> No model, no training. This is the number every later result gets compared against, so it needs
> to be computed on exactly the same split the models will use. Put the split logic in a shared
> function so `train.py` can import it rather than reimplementing it.

That shared split function matters more than it looks. If the baseline and the model compute their
test sets separately, the comparison is meaningless and you will not notice.

---

## Stage 5 — LightGBM quantiles (2 h)

> Attach: `EUGENE_SPEC.md`, `features.py`, `baseline.py`.
>
> Write `train.py` per spec sections 1.5 to 1.8. Three LightGBM models, `objective="quantile"`,
> `alpha` of 0.1, 0.5 and 0.9, with the parameters in section 1.8.
>
> - Time-ordered splits from section 1.7, imported from `baseline.py`, not reimplemented.
> - `zone_id` passed as a categorical feature.
> - `h` as an ordinary numeric feature.
> - Early stopping on the validation set, 100 rounds.
> - Save to `models/lgbm_q{10,50,90}.txt` with `booster_.save_model`, and the ordered feature list
>   to `models/feature_names.json`.
> - Print validation MAE for the P50 model alongside the baseline MAE from `results/baseline.json`
>   so I can see immediately whether it's working.
>
> Three design decisions are fixed and I don't want them changed: `h` is a feature rather than 48
> separate models; `zone_id` is a categorical rather than 10 separate models; prediction is direct
> multi-horizon, never recursive. If you think one of these is wrong, tell me, don't just do
> something else.

**Gate:** the P50 validation MAE must be below the baseline MAE. If it isn't, don't move on — it
is nearly always a feature bug, not a model problem, and the usual culprit is a lag misaligned by
one step. Print a few rows of features alongside their target and read them by eye.

---

## Stage 6 — Evaluation (1 h)

> Attach: `EUGENE_SPEC.md`, `train.py`.
>
> Write `evaluate.py` computing every metric in spec section 1.9 on the test split, written to
> `models/metadata.json`: `baseline_mae_mw`, `mae_mw`, `wape`, `mae_by_horizon` (h = 1, 4, 12, 24,
> 48), `mae_peak` (top 10% of observed demand), `pinball_loss`, `coverage_80`, plus the train,
> validation and test date ranges.
>
> Also print a readable summary table to stdout.
>
> Do not compute MAPE. Zone demand approaches zero overnight in some zones and MAPE explodes.

**Two numbers to look at, in this order:**

- `coverage_80` should be near 0.80. At 0.95 your intervals are too wide to be useful to the
  agents; at 0.60 they are too narrow and the agents will be blindsided. Report it honestly —
  a calibration number a judge can check is worth more than a suspiciously small MAE.
- `mae_by_horizon["1"]` must be **less than** `mae_by_horizon["48"]`. If 48-step-ahead error
  equals 1-step-ahead error, you have a leak. Go back to `check_no_leakage` and make it stricter.

---

## Stage 7 — `forecast.py` (30 min)

> Attach: `EUGENE_SPEC.md`, `train.py`, `features.py`.
>
> Write `forecast.py` with exactly the two functions in spec section 1.10 — `predict(zone_id,
> issue_time_utc)` and `predict_all(issue_time_utc)` — and nothing else in its public surface.
>
> - Return plain nested Python lists, not numpy arrays. Dhruv's env and Leonard's API both consume
>   these directly and neither should need a converter.
> - Sort the three quantiles per row so `p10 <= p50 <= p90` always holds. Independently trained
>   quantile models cross each other sometimes.
> - Load the boosters once at module import, not per call. `predict_all` gets called 48 times per
>   simulated day inside the training loop.
>
> Then write `test_forecast.py` as a runnable pytest file containing exactly the acceptance tests
> in spec section 1.11.

```bash
python3 -m pytest test_forecast.py -v
```

All of them must pass. Tell Dhruv the moment they do — he needs `forecast.py` to wire your
predictions into the environment's observation.

---

## Stage 8 — Optuna and SHAP (90 min)

> Attach: `train.py`, `evaluate.py`.
>
> Two things.
>
> First, `tune.py`: an Optuna study of 30 trials over `learning_rate`, `num_leaves`,
> `min_child_samples`, `subsample`, `colsample_bytree` and `reg_lambda`, parallelised with
> `n_jobs` from an argument. Optimise **validation pinball loss averaged over the three
> quantiles**, not P50 MAE — tuning on the median alone leaves the intervals miscalibrated. Save
> the best parameters to `models/best_params.json` and support a `--retrain` flag that rebuilds
> the three final models with them.
>
> Second, `explain.py`: SHAP on the P50 model. A global importance bar chart to
> `models/shap_importance.png`, plus a function `top_factors(zone_id, issue_time, h) -> list[str]`
> returning three short human-readable strings like "colder than usual" or "demand elevated over
> the last 24h". Leonard displays those in the dashboard, so they need to read as English, not as
> feature names.

Run the sweep in the background and move on:

```bash
nohup python3 tune.py --trials 30 --n-jobs $(nproc) > results/tune.log 2>&1 &
```

---

## Stage 9 — Wire your forecaster into the env (1 h)

This is the join between your two jobs, and the step most likely to be skipped.

```bash
python3 -c "
import grid_env, forecast, schemas as S
env = grid_env.GridEnv(forecaster=forecast)
obs, info = env.reset(seed=0)
fc = obs[:, S.OBS_FC_P50:S.OBS_FC_P50+4]
assert (fc != 0).any(), 'forecast slots are zero'
print('P50 lead-1 per zone, MW:', (fc[:,0]*S.NORM_DEMAND_MW).round().astype(int))
"
```

Then compare: run `scripts/compare_agents.py` with and without `forecaster=forecast` and check the
optimiser's numbers change. If they are identical, your forecast is not reaching the observation
and stage 10 will train a policy with no forward view. **That failure is silent** — training will
look completely normal.

---

## Stage 10 — The real run (6 h, mostly waiting)

By now Dhruv's real power flow is in `grid_env.py` and the API hasn't changed, so `train_ppo.py`
needs no edits.

```bash
kill $(cat results/train_stub.pid)        # stop the stub run
nohup python3 train_ppo.py --steps 5000000 --n-envs $(nproc) > results/train_real.log 2>&1 &
```

Check in every 30–45 minutes. While it runs, build stage 11.

**Hour 16 is the decision point.** If the policy is not beating `OptimiserAgent` on at least two
of the three scenarios, we ship the optimiser and describe the system accurately. That is a good
outcome, not a failure — and it is only a good outcome if we decide it at 16 rather than 21.

---

## Stage 11 — The scoreboard (2 h)

> Attach: `agents_baseline.py`, `grid_env.py`, `schemas.py`.
>
> Write `scripts/run_comparison.py`. For each scenario in `schemas.SCENARIOS`, run all three
> strategies — `agents_baseline.NoOpAgent`, `agents_baseline.OptimiserAgent`, and
> `agents_baseline.PolicyAgent` wrapping the trained policy and its `VecNormalize` statistics —
> over 5 seeds each, and write the averaged totals to `results/compare.json` in exactly the shape
> in `EUGENE_SPEC.md` section 2.5. The three strategy keys are `schemas.STRATEGIES` and must not
> be renamed; Leonard's `/compare` endpoint reads them.
>
> Also save `results/training_curve.png` from `results/training_log.csv`.
>
> Load `VecNormalize` from `policies/vecnormalize.pkl` and set `training=False` and
> `norm_reward=False` on it before evaluating. Forgetting this is the standard way an evaluation
> silently disagrees with the training curve.

---

## The six things that will cost you an hour each

1. Flattening the observation for SB3. It isn't needed and it raises.
2. A random or k-fold split instead of time-ordered. Invalidates every number.
3. A bare `.shift()` instead of `.groupby("zone_id").shift()`. Silent, wrong at zone boundaries.
4. Not saving `vecnormalize.pkl`. Silent, policy useless at inference.
5. Training on rows flagged `MISSING` or `INTERPOLATED`.
6. Running `scripts/compare_agents.py` without `forecaster=forecast` and concluding the forecast
   doesn't help.

## When to stop and talk to Dhruv

- Stage 1 flat after 100k steps and 20 minutes of fiddling.
- Stage 5 model can't beat the baseline.
- Stage 6 shows no horizon degradation, which means a leak you can't find.
- Stage 9 shows the forecast slots unchanged.
- Hour 16 and the policy isn't beating the optimiser.

Every one of those has a planned fallback. None of them is a crisis if it surfaces early, and all
of them are if it surfaces at hour 21.
