# Dhruv's Runbook

**Your role:** integration owner. You own the simulator, the optimiser, the joins between
everyone's work, and the call on what ships.

## Already done

Most of your original task list got built early to unblock Eugene. For the record:

| Item | Status |
|---|---|
| `CONTRACT.md`, `schemas.py` | done, self-checking |
| `grid_env.py` — Gymnasium env, 5 incident types, weighted sampling | done |
| **Real DC power flow**, susceptance-weighted, solved per island | **done, just landed** |
| Islanding: every one of the 14 edges can fully trip without a crash | done, tested |
| `agents_baseline.py` — `NoOpAgent`, `OptimiserAgent` (heuristic), `PolicyAgent` | done |
| `scenarios/*.json`, B6 scenario fixed to a full boundary outage | done |
| `api.py` — Leonard's backend, all 10 endpoints | done, serving stubs |
| Stub data: `_fake`, `_holdout`, `_winter` parquet + generator + validator | done |
| `pick_scenario_start.py` — finds real windy-winter B6 conditions | done |
| Specs/runbooks for Eugene, Leonard, Ranya | done |

**The open calibration item is closed.** Quiet-day line loadings were 1.45–1.60 under the old
equal-reactance solve. Under real DC flow they're p50 0.43, p90 0.75, with 2.2% of edge-steps
over limit. That's what a stressed-but-operable grid looks like.

**Current numbers under real physics**, averaged over five seeds:

| Scenario | Unserved, none | Unserved, optimiser | Cost, none | Cost, optimiser |
|---|---|---|---|---|
| B6 full outage | 24,341 MWh | **1,167 MWh** | £173M | £35M |
| North Scotland islanded | 8,188 MWh | **312 MWh** | £76M | £30M |
| Optimiser beats none | | **6 of 6 scenarios** | | |

Throughput dropped from 2,345 to 1,443 steps/sec with the real solve. Still fine — multiply by
Eugene's core count.

---

## What's left

| Stage | Time | What | Trigger |
|---|---|---|---|
| 1 | 30 min | Ship the power flow | **now** |
| 2 | 45 min | Review Eugene's forecaster | now, before he goes further |
| 3 | 2 h | LP optimiser | after stage 2 |
| 4 | 30 min | Wire Eugene's forecaster into the env | when `forecast.py` passes its tests |
| 5 | 45 min | Swap in Ranya's real data | when `real.parquet` passes the validator |
| 6 | 2 h | Wire `api.py` to the real backend | after stage 5 |
| 7 | — | **The agent decision** | hour 16, fixed |
| 8 | 1 h | Final comparison runs | after stage 7 |
| 9 | 3 h | Freeze, video, rehearse | hour 21, fixed |

Stages 4 and 5 wait on other people. Don't sit idle — do stage 3 while you wait.

---

## Stage 1 — Ship the power flow (30 min)

The new `grid_env.py` changes the numbers everyone sees. Push it before anyone builds further on
the old physics.

```bash
python3 schemas.py                       # contract OK
python3 scripts/compare_agents.py        # 6/6
python3 scripts/make_api_stubs.py        # regenerate Leonard's stubs with real-physics numbers
```

Add a `.gitignore` before anyone commits checkpoints:

```
policies/
results/
models/
__pycache__/
*.pyc
data/raw/
data/canonical/real.parquet
```

`_fake.parquet`, `_holdout.parquet` and `_winter.parquet` stay tracked — they're the shared stubs.

```bash
git add grid_env.py stubs/ .gitignore MY_COMMITMENTS.md
git commit -m "Real DC power flow, susceptance-weighted, per-island"
git push
```

**Eugene can't use GitHub right now, so you're his distribution channel.** Send him `grid_env.py`
directly. Message:

> New grid_env.py — real DC power flow. Same API, nothing in your code changes. Drop it in place
> of the old one. Any PPO run started before this was on the old physics, so the stub-env
> training curve is now throwaway; restart it on this one when you get to stage 10.

Tell Leonard to rerun `make_api_stubs.py`. The scoreboard numbers changed.

---

## Stage 2 — Review Eugene's forecaster (45 min)

This is the highest-risk thing in the project right now, and it's yours to catch.

Eugene's AI wrote all twelve stages and then reviewed its own code. Self-review is the weakest
check there is — it won't find a bug it believes isn't one. A target leak survives every later
check and reaches the slide.

**Get four numbers from him. These need nobody's review to trust:**

| Check | Pass |
|---|---|
| `mae_by_horizon["1"]` vs `["48"]` | 1 clearly below 48 |
| `coverage_80` | 0.70–0.90 |
| `mae_mw` vs `baseline_mae_mw`, **validation** | model below baseline |
| Runs clean on `_holdout.parquet` | same shapes, no errors |

**If horizon 1 and horizon 48 have similar error, something is leaking**, regardless of what any
review concluded. A model that forecasts 24 hours out as well as 30 minutes out has seen the
future.

Then get `features.py`, `train.py` and `evaluate.py` from him and review them yourself — or send
them to me. Look for exactly four things:

1. Any `.shift()`, `.rolling()` or `.diff()` not preceded by `.groupby("zone_id")`.
2. Any shift or rolling op before a sort on `(zone_id, timestamp_utc)`.
3. Any `shuffle=True`, `KFold`, or `train_test_split` anywhere.
4. Baseline and model computing their test set from two separate functions.

Ask him which fixes his review made, and whether any touched the split or lag alignment. A leak
repaired badly is worse than one left in, because it now looks checked.

---

## Stage 3 — LP optimiser (2 h)

The heuristic optimiser works, but it's a set of rules. An LP is defensibly optimal and a much
better answer to "how do you know this is the best response?" — which judges will ask.

**Formulation**, one LP per step:

Decision variables, all ≥ 0:

- `g[z,f]` — dispatch per zone and dispatchable fuel, bounded by available capacity
- `c[z]` — renewable curtailment, bounded by renewable output
- `d[z]` — demand response called, bounded by `dr_mw`
- `s[z]` — storage discharge, bounded by power and state of charge
- `u[z]` — unserved energy, the slack that keeps the LP always feasible

Objective:

```
minimise  Σ cost[f]·g[z,f]  +  6000·Σ u[z]  +  2·Σ c[z]  +  small·Σ d[z]
```

The £6,000/MWh on unserved energy is the value of lost load already used in `grid_env.py`. It
guarantees the LP sheds load only as a last resort.

Constraints:

- **Per island, energy balance:** generation + storage + DR + unserved − curtailment = demand.
  Use `agents_baseline._islands(info)` — it already exists.
- **Line limits via PTDFs:** `−limit ≤ PTDF · injections ≤ limit`. The PTDF matrix comes from the
  same susceptance matrix `grid_env` already builds — expose a method that returns it rather than
  rebuilding it, so the LP and the physics can't disagree.

Use `scipy.optimize.linprog(method="highs")`. Ten zones, 8 fuels, 14 lines: a few hundred
variables, milliseconds per solve.

**Then map the LP solution back to the action vector.** The env takes fractions in `[-1, 1]`;
the LP gives MW. Convert per slot with `frac * 2 - 1`, using available capacity from the
observation as the denominator.

**Gate:**

```bash
python3 scripts/compare_agents.py
```

The LP must beat `none` in 6 of 6 *and* match or beat the heuristic in every scenario. If it's
worse than the heuristic anywhere, the LP has a bug — almost certainly the PTDF sign convention
or the action mapping. An optimal solver cannot lose to a rule of thumb on the same problem.

Keep the heuristic as `HeuristicAgent`. If the LP isn't solid by the time stage 6 starts, ship the
heuristic and say so.

---

## Stage 4 — Wire Eugene's forecaster (30 min)

Trigger: Eugene's `test_forecast.py` passes.

This is commitment #2, the one that fails silently. Today the env fills the forecast slots with a
naive same-half-hour-last-week guess. Swap in his model:

```python
import grid_env, forecast, schemas as S
env = grid_env.GridEnv(forecaster=forecast)
obs, info = env.reset(seed=0)
assert (obs[:, S.OBS_FC_P50:S.OBS_FC_P50+4] != 0).any()
```

Then run `compare_agents.py` with and without `forecaster=forecast`. **The optimiser's numbers
must change.** If they're identical, his forecast isn't reaching the observation and every PPO
run afterwards trains a policy with no forward view. Nothing errors when that happens. The
training curve looks completely normal.

Check speed too. `predict_all` gets called every step, 48 times an episode, inside every one of
Eugene's parallel envs. If his boosters load per call instead of once at import, training slows
to a crawl.

---

## Stage 5 — Swap in Ranya's real data (45 min)

Trigger: `real.parquet` exists.

```bash
python3 -I scripts/check_parquet.py data/canonical/real.parquet      # must say PASS
python3 scripts/pick_scenario_start.py data/canonical/real.parquet --write
python3 scripts/compare_agents.py                                    # rerun on real
```

The selector picks the real windy winter evening with the biggest Scottish surplus and rewrites
`scenarios/b6_trip_windy_peak.json`. The demo then starts from conditions that actually occurred.

Change `grid_env.DEFAULT_DATA` to point at `real.parquet` for all final runs.

**Tell Eugene immediately.** Every accuracy number he has came from synthetic data, and none of it
goes on a slide. He retrains on real.

---

## Stage 6 — Wire the real backend (2 h)

`api.py` serves stub files. Replace each function body with a real call. URLs, parameters and
response shapes stay identical — that's the whole point of the stubs — so Leonard's dashboard
keeps working throughout.

| Endpoint | Becomes |
|---|---|
| `/zones` | read `data/geo/zones.geojson` if Ranya made it, else the stub |
| `/state/series` | run one episode of `GridEnv` with the requested scenario and strategy |
| `/forecast/{zone_id}` | `forecast.predict(zone_id, issue_time)` |
| `/compare` | read `results/compare.json` |
| `POST /incident` | queue the incident into the next episode |

**Cache `/state/series`.** Three scenarios × three strategies is nine episodes. Precompute them at
startup rather than simulating per request, or the demo stalls for seconds every time someone
moves the slider.

This was Leonard's in the original plan, but he's a vibe coder and it's backend wiring against
your own simulator. Faster for you to do it than to explain it.

---

## Stage 7 — The agent decision (hour 16, fixed)

Does Eugene's PPO policy beat your optimiser on at least two of the three scenarios?

- **Yes:** the scoreboard shows all three strategies, agents last.
- **No:** ship the optimiser as the response layer and say so on the slide.

Make the call at 16, not 20. Either outcome is a good demo. Only one of them is a good demo if you
decide late.

If it's the optimiser, the agents column says "trained, did not beat the optimiser" with the real
numbers — not hidden, not the optimiser's numbers relabelled. A team that shows its negative
result honestly is more credible than one with a suspiciously clean win.

---

## Stage 8 — Final comparison runs (1 h)

```bash
python3 scripts/run_comparison.py     # Eugene's, writes results/compare.json
```

Five seeds per scenario per strategy, on real data, with the real forecaster wired in. Check:

- `agents_is_placeholder` is gone from `compare.json`
- every number on Leonard's scoreboard traces back to that file
- the headline B6 number you quote matches what the dashboard shows

---

## Stage 9 — Freeze (hour 21, fixed)

**Feature freeze at 21. Mean it.** Nothing new after this, only fixes to things that are broken.

- Leonard records the backup video. Non-negotiable — hackathon demos fail live constantly.
- Rehearse the pitch twice, timed. Three minutes.
- One person owns the laptop during the demo. Everyone else stays off it.

---

## Open commitments

From `MY_COMMITMENTS.md`, what's still yours:

| # | Promise | Status |
|---|---|---|
| 2 | Env writes Eugene's real P50/P90 into obs slots 4–9 | **stage 4** — naive forecast until then |
| 3 | `OptimiserAgent` as an LP | **stage 3** — heuristic until then |
| — | `api.py` serving real data | **stage 6** |

Everything else on that list is closed.

## If you're short on time, cut in this order

1. Real zone polygons — boxes are fine.
2. The LP — the heuristic already wins 6 of 6.
3. PPO agents — the optimiser is the response layer.

**Never cut:** the forecaster review in stage 2, the real-data swap in stage 5, or the backup
video. Those are the three things that decide whether what you show is true.
