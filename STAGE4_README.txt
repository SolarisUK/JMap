Stage 4: estimated regional demand, 2024-2025

Extract this ZIP into C:\Users\ranya\JMap. Its pulls, data and results folders
belong directly inside JMap, beside schemas.py and the earlier stage files.

At a fresh PowerShell prompt inside JMap, run:

    python .\pulls\build_zone_demand.py

This makes no network requests. It reads your project's schemas.ZONE_ORDER and
schemas.DEMAND_SHARE, plus the national-demand and weather Parquets from the
previous stages, then rebuilds data/raw/zone_demand.parquet.

Expected: Stage 4 estimated zone-demand checks: PASS; 10 zones; 350,880 rows;
no missing half-hours, nulls or duplicate keys; is_estimated True on all rows.

Files
-----
pulls/build_zone_demand.py
data/raw/zone_demand.parquet
results/stage4_checks.txt
results/stage4_allocation.json

Method
------
For each half-hour and zone:

    heating_degrees = max(15.5 - zone_temperature_c, 0)
    weight = contract_share * (1 + 0.015 * heating_degrees)
    estimated_zone_demand = national_demand * weight / sum_of_zone_weights

Colder zones receive relatively more demand when heating is needed. If all
zones have the same temperature, the original contract shares are recovered.
If all zones are at or above 15.5 C, the original shares are also recovered.

The weights are renormalised at each half-hour. This allocation changes where
demand is assigned; it does not add to the national total. Tiny floating-point
residue is assigned to the largest-share zone, determined from the contract.

Completed checks
----------------
35,088 timestamps per zone across 2024-2025; 350,880 rows in total.
Maximum national-total conservation difference: approximately 1.46e-11 MW.
The numerical check allows an absolute tolerance of 1e-8 MW.
The largest aggregate share change is London: -0.307 percentage points.
All zone shares remain within one percentage point of the contract.

The percentage comparison uses total demand across the data window, equivalent
to total MWh shares because every UTC interval lasts 0.5 hours.

Output format
-------------
zone_id          string
timestamp_utc    timestamp[us, tz=UTC]
demand_mw        float64
is_estimated     bool

This intermediate keeps float64 demand values so national totals are conserved
to numerical precision. Stage 5 casts demand to float32, as required by the
canonical schema. Small float32 rounding differences will then be expected.
The final nine-column real.parquet is still the Stage 5 deliverable.

Limits and interpretation
------------------------
Label this data "estimated regional demand" everywhere. National demand is
real NESO outturn; regional values are an allocation, not regional measurements.
The base shares and heating sensitivity are assumptions supplied by the
contract and runbook. The script does not independently verify the statistical
origin of those shares or calibrate the sensitivity to regional meters.

The constructed regional targets depend on the weather features used to create
them. Regional prediction accuracy therefore measures this allocation, not
independent measured regional demand. The Stage 3 weather-issue-time proxy
also remains a limit for historical day-ahead forecast evaluation.

The preparatory build used the demand shares printed from schemas.py in your
supplied PowerShell history. Running the script on your computer reads your
current schemas.py, which remains authoritative. No schemas.py is overwritten.

results/stage4_allocation.json records the formula, shares, share comparisons,
conservation error and hashes of the input files. Stage 5 still needs to check
the final canonical schema, quality flags and demand/weather join.
