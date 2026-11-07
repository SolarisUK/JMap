# JMap grid operations

A compact simulator dashboard implementing `LEONARD_SPEC.md`. The primary page is `UI/operations.html`; `UI/main.html`, `UI/overview.html`, and the API root route there. The historical local-authority explorer remains at `UI/explorer.html` and is documented in [Energy context](docs/energy-context.md).

## Run

From the repository root in PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe scripts/make_api_stubs.py
.venv/Scripts/python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. Dependencies and generated stubs are already prepared in this workspace. The API serves the UI and all nine contract endpoints from the same origin. API documentation is at `/docs`.

Opening `UI/operations.html` directly from disk uses the generated offline bundle. Its three scenarios, timeline, forecasts, maps and comparisons work without a server. Incident controls explicitly load pre-generated scenarios in this read-only preview; start the simulation API for custom injection.

## Implemented contract

| Requirement | Implementation |
| --- | --- |
| Shared constants | `/reference` reads `schemas.py`; the UI consumes canonical zone, edge, strategy and fuel ordering. |
| Network | `/zones` and `/edges` provide ten zone polygons and fourteen corridors, including the highlighted Scotland–England boundary. |
| Half-hour state | `/state` drives map colours from `unserved_mw`, zone details and cumulative episode KPIs. Importing electricity is not itself a shortage. |
| Corridor semantics | Signed arrows, thermal loading bands, overloads above 100%, partial-trip dashes, and zero-limit out-of-service lines with no arrows. |
| Timeline | `/state/series` supplies 48 consecutive half-hours, play/pause/seek, synchronized baseline/response maps and camera controls. |
| Forecast | `/forecast/{zone_id}` supplies a P50 line, P10–P90 band, 48 UTC-aligned timestamps and three explanation strings. |
| Incidents | `/scenarios` and validated `POST /incident` support the three named scenarios and the boundary-trip, all-zone cold-snap and East outage controls. |
| Results | `/compare` drives the `none` / `optimiser` / `agents` scoreboard, exports and calculated full-episode result. Placeholder agent metrics are withheld. |
| Demo backup | `artifacts/backup-demo.webm`, recorded against the running simulator API. |

All timestamps remain UTC internally. The UI formats half-hour starts in Europe/London, including BST/GMT disambiguation. Top KPI tiles read cumulative `totals`, while selected-zone cost/carbon describe only the selected interval. Forecast issue time follows the selected interval in simulation mode. Read-only forecasts retain and clearly display their recorded issue time.

The main map is a paired comparison. On narrow phones the maps stack at full width so the zone labels stay legible; Response only is also available. The compact KPI strip preserves map space. Inspect, Forecast and Results share a scrollable analysis panel. Filters and selected replay state persist in the URL.

Zone colours use a display-only 0.05 MW near-zero tolerance to avoid colouring floating-point residuals as red zero-demand shortages; their labels say below 0.1 MW and tooltips/API values remain exact. The scoreboard shows all four cumulative metrics for every actual strategy and withholds all four for an untrained agent placeholder.

## API

| Method | Path |
| --- | --- |
| GET | `/reference` |
| GET | `/zones` |
| GET | `/edges` |
| GET | `/state?t=<UTC ISO or zero-based step>&scenario=<name>&strategy=<key>` |
| GET | `/state/series?scenario=<name>&strategy=<key>` |
| GET | `/forecast/{zone_id}?issue_time=<UTC ISO>` |
| GET | `/scenarios` |
| POST | `/incident?scenario=<name>` |
| GET | `/compare?scenario=<name>` |

`POST /incident` accepts exactly `type`, `target`, `start_step`, `duration_steps`, and `magnitude`. Targets, types, numeric bounds and UTC times are validated. Incidents are shared by all strategies in the chosen scenario, invalidate cached episodes and leave other scenarios unchanged. The cold-snap UI submits one canonical incident per reference zone. Custom incidents are process-local; restarting restores the three scripted scenarios.

## Data and model honesty

The supplied `_fake(1).parquet` is copied unchanged to `data/canonical/_fake.parquet`; `agents_baseline(1).py` is copied unchanged to the importable `agents_baseline.py`. Original schemas, simulator physics and baseline algorithms are unchanged. Scenario definitions follow the shared contract. Replay is deterministic, uses no random incidents, and selects 4 November 2026 UTC from the supplied synthetic data as the complete available November day with the highest Scottish evening wind.

- Demand/weather are synthetic. These are simulated results, not live telemetry.
- No trained agent checkpoint was supplied. `agents_is_placeholder=true`; agent frames replay the optimiser only as a clearly labelled preview. Their scoreboard/export totals are blank and they cannot win the comparison.
- No trained forecast model was supplied. The fallback uses historical-week/persistence demand, illustrative uncalibrated ranges and explicitly non-SHAP factors. Forecast metadata and the UI disclose this.
- The supplied optimiser is a heuristic and the simulator uses simplified flow physics. `generator_outage` reduces dispatchable capacity; the canonically named nuclear-outage scenario therefore does not literally remove nuclear output. The scenario description and incident controls state the actual dispatchable-capacity effect.
- The initial zone geometry is the contract's schematic boxes. Drop validated final polygons at `data/geo/zones.geojson` with the same `properties.zone_id` values to replace them.
- The current run does not reproduce the spec's illustrative 96% improvement. Headlines use measured results. Baseline unserved energy below 1 MWh produces no percentage claim; strategies within 0.1 MWh tie on energy and then compare known cost. Exact raw values remain in the data and exports.

## Switching data providers

The UI uses one API adapter; no chart/map code changes are needed when replacing the backend. `?mode=api&api=http://127.0.0.1:8000` or `window.JMAP_OPERATIONS_CONFIG = {mode:'api',apiBase:'...'}` selects an API base. Serve the UI and API together, or configure CORS on an external backend. `?mode=bundled` explicitly selects generated preview data; API errors never silently substitute a demo.

Server configuration:

| Environment variable | Meaning |
| --- | --- |
| `JMAP_BACKEND_MODE` | `simulation` (default) or read-only `stubs`. |
| `JMAP_DATA_PATH` | Alternate canonical parquet file, resolved relative to the repository. |
| `JMAP_DATA_IS_SYNTHETIC` | Explicit data provenance; defaults to `true`. |
| `JMAP_FORECAST_PROVIDER` | `module:factory` or `module:instance` exposing the shared forecasting interface. |
| `JMAP_POLICY_PROVIDER` | `module:factory` or `module:instance` exposing `act(obs, info)`. |

For read-only API replay:

```powershell
$env:JMAP_BACKEND_MODE = 'stubs'
.venv/Scripts/python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Set `JMAP_BACKEND_MODE` back to `simulation` to recompute custom incidents. Generated files in `stubs/` and `UI/assets/simulation-stubs.js` come from actual runs of the supplied simulator. Regenerate them with `scripts/make_api_stubs.py` after changing data or providers; the script works from any working directory. The root `make_api_stubs.py` remains a compatible wrapper.

## Validation

```powershell
python schemas.py
node --test tests/*.test.cjs
.venv/Scripts/python.exe -m pytest tests/test_api.py -q
python tests/operations-browser.py
python tests/browser-smoke.py
```

The operations browser check requires Python Playwright and the API on port 8000; `--base-url` selects another server. It verifies canonical topology, snapshot totals, timeline/forecast alignment, placeholder handling, scenario/strategy switching, incident recomputation, missing data/error behavior, exports, API/stub/file preview and responsive layouts. The context browser check exercises the preserved annual explorer. Browser screenshots go to the system temporary directory. No browser dependency is needed to run the application itself.

Use `--stub-url http://127.0.0.1:8001` to additionally test a second server started in read-only stub mode. The operations test intentionally injects a one-half-hour trip into the running simulation; restart the API afterwards to restore the scripted episodes. Re-record the demo with `python scripts/record_demo.py` against a fresh API process; this also injects a full boundary trip as part of the demonstration.
