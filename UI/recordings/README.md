# B6 backup recording

The captioned MP4 is a 2 minute 30 second recording of the local dashboard using the running API. It has no audio; the subtitles provide a timed voiceover script. Keep a local copy on the demo laptop and test playback before presenting.

Start the API with `uvicorn api:app --port 8000`. The recording disables browser caching and hard-refreshes the dashboard. It uses the actual timeline, route inspection and Results controls; it does not alter figures, map colours or API responses.

## Run of show

- 00:00:00: Same B6 contingency. Left: no response. Right: linear-programming optimiser.
- 00:00:12: Before the outage: demand is served in both runs. The left run already has line overloads.
- 00:00:20: Half-hour snapshots advance together. Arrowheads show the direction of electricity flow.
- 00:00:40: The B6 boundary carries electricity from Scotland towards northern England.
- 00:00:52: Inspecting SSCO-NORT: flow and capacity come from the API.
- 00:01:04: B6 trips. The same boundary is unavailable in both runs.
- 00:01:12: No response: northern England and downstream zones develop unmet demand.
- 00:01:25: Scotland is islanded but still supplied. Red nodes indicate shortages elsewhere.
- 00:01:34: The optimiser keeps demand served, with no red overloaded lines throughout the episode.
- 00:01:48: 0 MWh unserved at dashboard precision across the full episode.
- 00:02:00: Full episode: 53,418 vs 0 MWh unserved. Costs: £371M vs £72M.
- 00:02:12: Model penalties are separate from cost: about £5 for the optimiser.
- 00:02:20: RL agents were also trained; they did not beat the optimiser.

## Data notes

- Scotland is isolated but remains supplied in these API frames. Northern England and downstream regions develop shortages in the no-response run. Do not describe a Scottish blackout.
- The optimiser's raw full-episode residual is 0.01116506601238143 MWh; the dashboard correctly rounds it to zero at its display precision. Its raw penalty is GBP 4.975137700967025, shown separately from cost.
- The API first marks the boundary tripped at 2025-12-16T16:00:00+00:00 and first shows shortages at 2025-12-16T16:30:00+00:00. The recording follows those timestamps without shifting them to match the scenario's prose description.
- `b6-demo.json` captures the runtime comparison and scene timings. The source WebM has the untrimmed initial page load; the MP4 removes only that setup and preserves the full 150-second walkthrough.

## Refresh for new data

Run the existing exporter: `python -B UI/scripts/export-api-stubs.py --backend-root dhruv_latest`, restart the API, then rerun `python -B UI/scripts/record-b6-demo.py --ffmpeg PATH_TO_FFMPEG`. Captions and figures regenerate from the running API. The script stops for review if the Scottish supply story or optimiser overload/shortage guarantees change.

Rehearse twice on the presentation laptop with a timer. On each run check the boundary trip, left/right contrast, zero-unserved headline, final scoreboard, and offline MP4 playback. This capture does not verify that physical laptop or projector.
