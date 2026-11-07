# Data quality: GB regional demand, 2024-2025

Regional demand is estimated from national demand and temperature, rather than measured at regional meters.

Weather contains archived short forecasts with proxy issue times, so this data does not establish a leak-free day-ahead backtest.

The regional target uses temperature in its formula, so regional model scores do not test independent regional measurements.

**Scope:** 350,880 rows; 10 zones; 731 UTC days; 2024-01-01T00:00:00+00:00 to 2025-12-31T23:30:00+00:00 (half-hour starts). All 350,880 rows are marked estimated.

| Zone | Rows | Target coverage | Estimated share | Contract share | Difference (pp) |
|---|---:|---:|---:|---:|---:|
| NSCO | 35,088 | 100.00% | 4.030% | 4.000% | +0.030 |
| SSCO | 35,088 | 100.00% | 7.138% | 7.000% | +0.138 |
| NORT | 35,088 | 100.00% | 13.192% | 13.000% | +0.192 |
| YORK | 35,088 | 100.00% | 7.988% | 8.000% | -0.012 |
| WALE | 35,088 | 100.00% | 6.185% | 6.000% | +0.185 |
| MIDL | 35,088 | 100.00% | 16.920% | 17.000% | -0.080 |
| EAST | 35,088 | 100.00% | 9.928% | 10.000% | -0.072 |
| SWES | 35,088 | 100.00% | 7.998% | 8.000% | -0.002 |
| LOND | 35,088 | 100.00% | 12.693% | 13.000% | -0.307 |
| SOUT | 35,088 | 100.00% | 13.929% | 14.000% | -0.071 |

Coverage = non-null targets / expected UTC half-hours, including any flagged fills. 350,880 rows are eligible under the contract's MISSING/INTERPOLATED scoring rule. Shares use total demand, equivalent to MWh shares for equal half-hours.

| Quality flag | Rows |
|---|---:|
| OK | 348,960 |
| MISSING | 0 |
| INTERPOLATED | 0 |
| ZERO_RUN | 0 |
| JUMP | 0 |
| DST_BOUNDARY | 1,920 |

OK means a zero flag; other flag counts are bitwise and can overlap. DST flags cover full 46/50-period local days. All UTC days have 48 periods.

**Target gaps longer than two hours:** None.

**National demand:** min **12,803 MW**, mean **26,222.51 MW**, max **45,924 MW**, versus the runbook's rough 18,000-48,000 MW guide. 1,583 half-hours fall below that guide and 0 above; the original outturn values are retained.

**Validation:** independent and supplied team checkers passed; this report verifies the recorded output and input file hashes. Float32 rounding leaves a maximum national-total difference of 0.00122070 MW (tolerance 0.01 MW). Null values across the canonical table: 0.

**Sources:** NESO ND outturn and Open-Meteo Historical Forecast output at contract zone centroids. Regional allocation uses contract shares and 1.5% per degree below 15.5 C, renormalised per half-hour. Supporting generation limitations are recorded in `stage2_checks.txt`.

[Daily target-coverage heatmap](data_coverage.png). Full figures and the validated file hash: `data_quality_summary.json`.
