# B6 backup recording

The captioned MP4 is a 2 minute 30 second recording of the local dashboard using the running API. It has no audio; the subtitles provide a timed voiceover script. Keep a local copy on the demo laptop and test playback before presenting.

Start the API with `uvicorn api:app --port 8000`. The recording disables browser caching and hard-refreshes the dashboard. It uses the actual timeline, route inspection and Results controls; it does not alter figures, map colours or API responses.

## Run of show

- 00:00:00: Same B6 contingency. Left: no response. Right: linear-programming optimiser.
- 00:00:12: Before the outage: demand is served in both runs. Line colours show corridor loading.
- 00:00:20: Half-hour snapshots advance together. Arrowheads show the direction of electricity flow.
- 00:00:40: Surplus Scottish wind is exported over B6 towards England.
- 00:00:52: Inspecting SSCO-NORT: flow and capacity come from the API.
- 00:01:04: B6 trips at 17:00 UTC on 14 Dec 2025. Scotland is cut off from England.
- 00:01:12: Scotland is islanded WITH SURPLUS wind and stays supplied. Curtailment shows spare generation.
- 00:01:26: No response: all eight England and Wales zones, NORT through SOUT, develop shortfalls.
- 00:01:44: The optimiser keeps demand served, with no red overloaded lines throughout the episode.
- 00:01:48: 0 MWh unserved at dashboard precision across the full episode.
- 00:02:00: Full episode: 63,917 vs 0 MWh unserved. Costs: £388.5M vs £17.4M.
- 00:02:12: Optimiser model penalty: £0.0M. Model penalties remain separate from cost.
- 00:02:20: RL policies were also trained; they did not beat the optimiser.

## Data notes

- Scotland is islanded WITH SURPLUS wind and stays supplied. All eight England and Wales zones (NORT, YORK, WALE, MIDL, EAST, SWES, LOND, SOUT) develop shortfalls in the no-response run. The optimiser has zero displayed unserved MWh and no overloaded lines throughout the episode.
- The optimiser's raw full-episode residual is 0.0020040470450339853 MWh; the dashboard correctly rounds it to zero at its display precision. Its raw penalty is GBP 3.530229645889449, shown separately from cost.
- The recorded B6 incident starts at 2025-12-14T17:00:00+00:00; shortfalls begin at 2025-12-14T17:00:00+00:00. The recording uses the active incident's timestamp, rather than next-decision availability, to label the trip.
- Every cost and penalty is shown in GBP millions with one decimal. The supplied raw penalty remains unchanged; its displayed value is £0.0M.
- `b6-demo.json` captures the runtime comparison and scene timings. The source WebM has the untrimmed initial page load; the MP4 removes only that setup and preserves the full 150-second walkthrough.

## Refresh for new data

Run the existing exporter: `python -B UI/scripts/export-api-stubs.py --backend-root dhruv_latest`, restart the API, then rerun `python -B UI/scripts/record-b6-demo.py --ffmpeg PATH_TO_FFMPEG`. Captions and figures regenerate from the running API. The script stops for review if the Scottish supply story or optimiser overload/shortage guarantees change.

Rehearse twice on the presentation laptop with a timer. On each run check the boundary trip, left/right contrast, zero-unserved headline, final scoreboard, and offline MP4 playback. This capture does not verify that physical laptop or projector.
