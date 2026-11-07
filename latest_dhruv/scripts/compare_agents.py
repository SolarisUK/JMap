"""Run the baseline strategies across scenarios and print the scoreboard.

Usage: python3 scripts/compare_agents.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agents_baseline as AB
import grid_env
import schemas as S

SCENARIOS = {
    "quiet": [],
    "b6_trip_1circuit": [S.Incident("line_trip", "SSCO-NORT", 34, 14, 0.5)],
    "b6_trip_full": [S.Incident("line_trip", "SSCO-NORT", 34, 14, 1.0)],
    "cold_snap": [S.Incident("demand_spike", z, 30, 12, 1.18) for z in S.ZONE_ORDER],
    "nsco_islanded": [S.Incident("line_trip", "NSCO-SSCO", 10, 20, 1.0)],
    "east_outage": [
        S.Incident("generator_outage", "EAST", 20, 16, 0.9),
        S.Incident("wind_lull", "NSCO", 20, 16, 0.25),
    ],
}

SEEDS = [1, 2, 3, 4, 5]


def run(agent, scenario, seed):
    env = grid_env.GridEnv(scenario=scenario)
    obs, info = env.reset(seed=seed)
    total = 0.0
    peak_overload = 0.0
    for _ in range(S.STEPS_PER_EPISODE):
        obs, r, term, trunc, info = env.step(agent.act(obs, info))
        total += r
        peak_overload = max(
            peak_overload, max(e["loading_frac"] for e in info["edges"].values())
        )
        if term or trunc:
            break
    t = info["totals"]
    return {"reward": total, "peak_loading": peak_overload, **t}


print(
    f"{'scenario':20} {'strategy':10} {'reward':>12} {'unserved':>10} "
    f"{'cost GBP':>13} {'curtail':>9} {'peak load':>10}"
)
print("-" * 92)

wins = 0
for name, sc in SCENARIOS.items():
    results = {}
    for strat, agent in [("none", AB.NoOpAgent()), ("optimiser", AB.OptimiserAgent())]:
        runs = [run(agent, sc, s) for s in SEEDS]
        results[strat] = {k: sum(r[k] for r in runs) / len(runs) for k in runs[0]}
        r = results[strat]
        print(
            f"{name:20} {strat:10} {r['reward']:12.0f} {r['unserved_mwh']:10.1f} "
            f"{r['cost_gbp']:13.0f} {r['curtailed_mwh']:9.1f} {r['peak_loading']:10.2f}"
        )
    better = results["optimiser"]["reward"] > results["none"]["reward"]
    delta = results["optimiser"]["reward"] - results["none"]["reward"]
    wins += better
    print(f"{'':20} {'-> optimiser':10} {'better' if better else 'WORSE':>12} by {delta:+.0f}")
    print()

print(f"optimiser beats no-response in {wins}/{len(SCENARIOS)} scenarios")
