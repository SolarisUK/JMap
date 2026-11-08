# Upgraded optimiser stub verification

Imported the exported data from upstream commit `2b73169`: root `stubs/` and `UI/assets/simulation-stubs.js`. Existing UI changes were preserved. `api.py` and the loader remain unchanged; the dashboard uses the standard root API.

The standard `uvicorn api:app --port 8000` server reports a healthy API. The dashboard was hard-refreshed with browser caching disabled. It reads all results from the running API; the archived JavaScript data is not loaded by the page.

## Current B6 results

These are verification observations from `/compare`, not dashboard constants:

| Strategy | Unserved MWh | Cost GBP | Model penalty GBP |
|---|---:|---:|---:|
| No response | 53,418.4461 | 370,955,967.1450 | 286,264,372.0853 |
| Optimiser | 0.0112 | 72,128,732.1047 | 4.9751 |

The headline displays **0 MWh unserved** at the dashboard's precision. The small numerical residual is preserved in the API and exports. Unserved-energy and penalty reductions round to 100%. Zero baselines produce no invented percentage; signed zero displays as zero. Cost never includes model penalties.

All 48 optimiser frames render without red overloaded corridors, including in Inspect and Transfers. LP feasibility residue up to `1e-6` of capacity is tolerated by the display; original values remain available. Meaningful overloads remain red in the no-response run.

## Actual incident story

Scotland becomes isolated but remains supplied. Northern England and downstream zones lose supply in the no-response run. A Scottish blackout would misrepresent these data.

The API first marks the B6 corridor unavailable at 16:00 UTC and first reports downstream shortages at 16:30 UTC. Its scenario prose says 17:00. The dashboard now derives the line-trip description and selected-scenario tooltip from recorded API frames, so displayed times agree with the timeline. Original API data and timestamps are preserved. Export validation additionally rejects a replay beginning half an hour after its configured start. The recording also follows `timestamp_utc` without compensation or a time shift.

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

See `recordings/README.md` for the 2:30 backup video, narration cues and presentation-laptop rehearsal checklist. The recording uses actual API data and leaves the product UI unchanged.
