# Dhruv's commitments to other people's code

Interfaces I have promised in other people's specs and must actually build. None of these appear on
my own task list, and most fail silently rather than loudly.

| # | Promise | Promised in | Fails how | Status |
|---|---|---|---|---|
| 1 | `grid_env.py` exposing class `GridEnv`, Gymnasium API | `EUGENE_SPEC.md` 2.1, 2.7 | Loud — his tests fail at import | **done**, `check_env` passes |
| 2 | `GridEnv` writes Eugene's P50 into obs indices 4–7 and P90 into 8–9 | `EUGENE_SPEC.md` 2.1 | **Silent** — PPO trains fine on zeros, agents just lose all foresight | **done** with a naive forecast; swap in his model via `GridEnv(forecaster=...)` |
| 3 | `agents_baseline.py` exposing `OptimiserAgent` and `NoOpAgent`, both with `.act(obs, info) -> action` | `EUGENE_SPEC.md` 2.5 | Loud — his eval loop has nothing to call | **done**, heuristic; LP at hour 14 |
| 4 | `scenarios/*.json` for the three named scenarios, readable by his eval loop | `CONTRACT.md` 10 | Loud | **done**, all three load |
| 5 | `info` dict on every `step()` carrying the keys in `CONTRACT.md` 6 | `CONTRACT.md` 6 | **Silent** — Leonard's dashboard renders blanks or stale values | **done**, asserted + JSON-serialisable |
| 6 | `obs` is `float32` `(10, 52)`, `action` accepted as `(10, 11)` | `CONTRACT.md` 6 | Loud | **done** |
| 7 | `MIDL` is the slack bus; power flow stays solvable when any single edge trips | `CONTRACT.md` 1, 2 | **Silent** — singular matrix only on certain incident combinations | **done**, all 14 edges tested at full trip |

## Calibration item — closed

Quiet-day line loadings were 1.45–1.60 under the equal-reactance (pinv) solve. Under the real
susceptance-weighted DC flow they are p50 0.43, p90 0.75, p99 1.12, with 2.2% of edge-steps over
limit across six seeds. The flow model was the problem, not the limits. Fixed by the physics,
not by widening anything.

## The two to watch

**#2 is the one that would actually get missed.** Zeros in an observation slot are a legal
observation. Training proceeds, the reward curve descends, the policy works. It is simply a
controller with no forward view, which makes the forecaster decorative and removes the one thing
that makes this project more than a dispatch optimiser. Test it by asserting the slots are non-zero
after `reset()`, not by reading the training curve.

**#7 needs a guard.** `NSCO` has degree 1. If `NSCO-SSCO` is fully tripped, North Scotland is an
electrical island and the susceptance matrix for that component is singular. The flow solver must
detect disconnected components and solve each one separately with its own slack, rather than
throwing. Build that in from the start — it will come up in training, and a crash inside a
`SubprocVecEnv` worker surfaces as an unhelpful broken pipe.

## Rule

Every time I write an interface into someone else's document, it goes in this table before I close
the file.
