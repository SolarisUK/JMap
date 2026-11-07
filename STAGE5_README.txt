Stage 5: canonical real.parquet, 2024-2025

The main deliverable is data/canonical/real.parquet. It has 350,880 rows and
exactly the same nine column names, order and Arrow types as the uploaded
_fake.parquet. It is sorted by zone_id and timestamp_utc.

Extract this ZIP into C:\Users\ranya\JMap. Keep pulls, scripts, data and results
directly inside JMap, beside schemas.py and the preceding stages' files.

At a fresh PowerShell prompt in JMap, run:

    python .\pulls\build_canonical.py

No downloads are needed. This reads the current project's CANONICAL_SCHEMA,
QF constants, ZONE_ORDER and DEMAND_SHARE, joins the Stage 3/4 files, builds
the Arrow schema from that dict, and writes real.parquet. Your schemas.py and
the supplied check_parquet.py validation rules are preserved.

The builder auto-detects data/canonical/_fake.parquet, _fake.parquet or
_fake(1).parquet and compares the schema if a sample is present. An explicit
--reference path is also supported.

Checks and the original runbook gate
-----------------------------------
Expected: Independent canonical contract checks: PASS.

The package includes scripts/check_canonical_contract.py, a NEW validator
written from the supplied contract. It is separate from the team's original
scripts/check_parquet.py, which has now also been supplied and checked.

The builder runs the original checker through scripts/run_team_checker.py
with Python -I. The launcher loads the project's schema rather than relying
on the checker's hardcoded /home/claude path. It derives a failing exit code
from the checker's problems list. The supplied checker is otherwise unchanged.
Both validators pass on the generated data. The team checker reports no warnings.
Your local run verifies the same checks against your current schemas.py.

To rerun only the included validator:

    python -I scripts/check_canonical_contract.py data/canonical/real.parquet

To run only the supplied team checker through its portable launcher:

    python -I scripts/run_team_checker.py data/canonical/real.parquet

Files
-----
data/canonical/real.parquet
pulls/build_canonical.py
scripts/check_canonical_contract.py
scripts/check_parquet.py
scripts/run_team_checker.py
results/stage5_checks.txt
results/canonical_metadata.json

Exact canonical schema
----------------------
zone_id                        string
timestamp_utc                  timestamp[us, tz=UTC]
demand_mw                      float32
temp_c                         float32
wind_ms                        float32
solar_wm2                      float32
weather_issue_time_utc          timestamp[us, tz=UTC]
quality_flag                   uint8
is_estimated                   bool

Completed independent checks
----------------------------
10 zones, 35,088 timestamps per zone, 350,880 rows.
2024-01-01 00:00 UTC through 2025-12-31 23:30 UTC, interval starts.
No duplicate keys, missing half-hours, null weather or null demand values.
Source weather and issue-time values are preserved.
Demand values exactly match Stage 4 after the required float32 cast.
All rows are marked is_estimated=True.
Maximum zone-total versus national-demand difference is 0.001220703125 MW,
within a 0.01 MW absolute tolerance. This difference comes from float32 rounding.
Aggregate shares remain within one percentage point of the contract.

Bitwise flag counts:
MISSING=0, INTERPOLATED=0, ZERO_RUN=0, JUMP=0, DST_BOUNDARY=1,920.
There are no target rows excluded by MISSING or INTERPOLATED in this build.
DST flags cover full local settlement days, including all 46/50 half-hours,
even when part of an October local day lies on the preceding UTC date.

Gap and quality policies
------------------------
The grid includes every zone/half-hour from the national demand window.
Only bounded gaps of 1, 2 or 3 half-hours are interpolated. Their values are
flagged INTERPOLATED and are excluded from scoring. Edge gaps and gaps of
4+ half-hours remain null and are flagged MISSING. Exactly two hours is kept
missing under the runbook's strict "under 2 hours" rule. No such gaps occur
in the completed 2024-2025 data.

Near-zero means demand <= 1 MW for at least 3 consecutive half-hours; flag
the entire run. JUMP marks changes over 40% from a strictly positive preceding
value. Flags are computed on the rounded canonical demand and combined by OR.
Weather resampling alone does not set the target INTERPOLATED bit.

Interpretation and limits
-------------------------
National demand is NESO outturn. Regional demand is a temperature-adjusted
allocation, not measured regional load. Regional accuracy scores therefore
describe this constructed allocation, not independent regional ground truth.

Weather is Open-Meteo archived short-range forecast output. Its previous-day
06:00 UTC issue timestamp is the runbook's proxy, not the actual forecast run
or publication time. This remains a limit for day-ahead backtesting. Solar
is an approximate interpolated feature based on source preceding-hour means.

Elexon generation remains in its own supporting file. It is not added as
extra columns because the canonical contract specifies exactly nine columns.

The preparatory build used schema and QF values printed from schemas.py in
the supplied PowerShell history and verified its schema against the attached
_fake.parquet. Running the script uses your current schemas.py as authority.

After the team check passes on your computer, Stage 5's gate is closed.
The full quality report and coverage heatmap are Stage 6. Zone polygons are
Stage 7.
