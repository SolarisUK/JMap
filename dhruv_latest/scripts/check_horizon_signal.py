"""Does this table contain horizon-dependent signal at all?

Compares two deliberately simple forecasters on one canonical table:

  lag_1w       same half-hour last week. Uses no recent demand, so its error should be
               roughly FLAT across horizons.
  persistence  lag_1w scaled by how far demand at the last known half-hour sat above or below
               its own value a week earlier. Uses recent demand, so it should be much better
               at short horizons and decay toward lag_1w at long ones.

If persistence beats lag_1w at h=1 by a wide margin and the gap closes by h=48, the table has
real horizon structure and the horizon-degradation gate is a meaningful test. If the two are
level at every horizon, the gate cannot pass on this data even for a perfect model.

Usage: python3 scripts/check_horizon_signal.py data/canonical/_fake.parquet
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pyarrow.parquet as pq

path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/canonical/_fake.parquet")
df = pq.read_table(path).to_pandas().sort_values(["zone_id", "timestamp_utc"])

HORIZONS = (1, 4, 12, 24, 48)
WEEK = 336

err = {name: {h: [] for h in HORIZONS} for name in ("lag_1w", "persistence")}

for _, g in df.groupby("zone_id", observed=True):
    y = g["demand_mw"].to_numpy(dtype=float)
    n = len(y)
    # issue times every 6 hours, with a week of history behind and a day ahead
    for T in range(WEEK + 1, n - 48, 12):
        last = T - 1
        if np.isnan(y[last]) or np.isnan(y[last - WEEK]) or y[last - WEEK] == 0:
            continue
        ratio = y[last] / y[last - WEEK]
        for h in HORIZONS:
            tgt = T + h - 1
            if np.isnan(y[tgt]) or np.isnan(y[tgt - WEEK]):
                continue
            base = y[tgt - WEEK]
            err["lag_1w"][h].append(abs(y[tgt] - base))
            err["persistence"][h].append(abs(y[tgt] - base * ratio))

print(f"=== {path.name} ===")
print(f"{'horizon':>8} {'lag_1w MAE':>12} {'persistence MAE':>16} {'persistence gain':>17}")
for h in HORIZONS:
    a = np.mean(err["lag_1w"][h])
    b = np.mean(err["persistence"][h])
    print(f"{h:8d} {a:12.1f} {b:16.1f} {100 * (1 - b / a):16.1f}%")

p1 = np.mean(err["persistence"][1])
p48 = np.mean(err["persistence"][48])
print()
print(f"persistence error h=48 / h=1: {p48 / p1:.2f}x")
print(
    "HORIZON STRUCTURE PRESENT" if p48 / p1 > 1.5 else "NO HORIZON STRUCTURE: the gate cannot pass here"
)
