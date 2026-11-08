# Frozen real-data replay verification

Verified the supplied real-data root `stubs/` through the standard root API. Inputs use NESO/Elexon demand and Open-Meteo day-ahead weather. Dispatch and grid outcomes remain simulated. `api.py`, the loader, stub files and JSON shapes are unchanged by this verification.

The standard `uvicorn api:app --port 8000` server reports a healthy API. The dashboard was hard-refreshed with browser caching disabled. It reads all results from the running API; the archived JavaScript data is not loaded by the page.

## Current B6 results

These are verification observations from `/compare`, not dashboard constants:

| Strategy | Unserved MWh | Cost GBP | Model penalty GBP |
|---|---:|---:|---:|
| No response (network-blind dispatch) | 63,917.2449 | 388,514,893.7588 | 205,171,133.4772 |
| Optimiser | 0.0020 | 17,380,851.9438 | 3.5302 |

The headline displays **0 MWh unserved** at the dashboard's precision. The small numerical residual is preserved in the API and exports. Unserved-energy and penalty reductions round to 100%. Zero baselines produce no invented percentage; signed zero displays as zero. Cost never includes model penalties.

All displayed costs and penalties use GBP millions with one decimal. The supplied B6 penalty is GBP 3.53 and displays as **£0.0M**; full precision is retained in the API and CSV exports. Signed values that round to zero have no minus sign.

## Other release results and dates

- B6: 14 December 2025; recorded incident and shortage onset at 17:00 UTC.
- Cold snap: 10 January 2025. No-response unserved energy is 10,591.7014 MWh; optimiser is 3,052.5241 MWh, costing GBP 96,010,718.3701.
- Nuclear outage, low wind: 9 November 2024. Both runs display zero unserved MWh; raw residuals are 0.0094 and 0.0081 MWh. Optimiser cost is GBP 49,492,933.9015 versus GBP 49,950,978.6586.

The UI shows only No response (network-blind dispatch) and Optimiser. An additional duplicated strategy and its placeholder flag are ignored; browser tests inject that case. Real-data labels and dates including years are verified. No measured result is hardcoded into the dashboard.

All 48 optimiser frames render without red overloaded corridors, including in Inspect and Transfers. LP feasibility residue up to `1e-6` of capacity is tolerated by the display; original values remain available. Meaningful overloads remain red in the no-response run.

## Actual incident story

After the B6 trip at 17:00, Scotland is islanded WITH SURPLUS wind and stays supplied. Shortfalls affect all eight England and Wales zones (NORT, YORK, WALE, MIDL, EAST, SWES, LOND, SOUT) in the no-response run. The optimiser has zero displayed unserved MWh and no overloaded lines throughout the episode.

The API first marks the B6 corridor unavailable at 16:30 UTC, while incident records and downstream shortages start at 17:00 UTC. The backend reports next-decision availability alongside the just-simulated zone measurements. The dashboard derives the trip label from the recorded incident's `timestamp_utc`, preserving all original API data and slider timestamps. It falls back to first-recorded availability only when no incident record exists.

## Future data refresh

```powershell
python -B UI/scripts/export-api-stubs.py --backend-root dhruv_latest
uvicorn api:app --port 8000
```

Stop any existing API process before restarting it, then hard-refresh the dashboard. The exporter writes the full replay, conventional JSON files and archived fixture together. No UI code or numeric edits are needed for subsequent datasets with the same contract.

## Validation and recording

```powershell
node --test UI/tests/*.test.cjs
python -B UI/tests/api-replay.test.py
python -B UI/tests/api-replay-browser.py
python -B UI/tests/lp-demo-browser.py
```

The API tests check all 288 scenario/strategy snapshots, timestamps, final totals and forecasts. Browser checks cover distinct split-screen runs, API-only changed data, scoreboard and CSV values, penalties, every B6 frame, zero denominators and compact layouts.

The final 2:30 captioned backup in `recordings/b6-demo.mp4` uses this real-data release, the 17:00 incident time, the Scotland-surplus/England-and-Wales-shortfall narrative, and the API-driven 63,917 to zero MWh and £388.5M to £17.4M comparison. `recordings/README.md` contains the timed narration and replay data notes.
