# JMap UI

Open `main.html` or `generation.html` for the main UK generating-site map. `transfers.html` shows live GB interconnector flows, `explorer.html` contains historical local energy statistics, and `operations.html` is the separate simulator. The pages are buildless and can be opened directly or served by any static HTTP server.

All dashboard pages use the shared minimalist black and charcoal palette in `theme-dark.css`, including native controls, dialogs and scrollbars. Interface highlights are neutral grey; colour is reserved for data and status.

Navigation, header sizing and map controls are shared through `site-shell.css`. `map-interactions.js` prevents accidental text selection during map gestures while keeping ordinary text copying and field editing available. Map buttons use the same zoom step and reset behavior; Ctrl/Meta + wheel retains browser zoom. Live-transfer labels, endpoints and direction arrows remain screen-sized when zooming. Cancelled gestures release their drag state; Escape or a blank-map click clears an inspected site or zone.

`map-motion.js` eases zoom, reset and keyboard pan across the four maps; direct dragging and pinching stay under the pointer. Small chevrons travel along observed live transfers and enabled simulation flows, following the signed direction. Their shared screen speed is decorative and does not encode MW or travel time. Zero, unknown and unavailable simulation corridors never animate. Sources contains the motion toggle (simulation also retains `motion=0` in its URL). Animation stops in hidden/off-screen views and follows reduced-motion changes immediately; static direction arrows remain available.

Short fades soften diagram focus changes, selected labels and newly opened details, and pause during map dragging. Measured values update immediately. Reduced-motion preferences disable these effects and hide moving simulation markers, including when the preference changes during a session.

The generation map uses `assets/generation-sites.js`, imported from the official DESNZ REPD July 2026 and DUKES May 2026 operating-asset registers. It includes renewable/storage projects and conventional gas/nuclear stations, with published capacities, coordinates, operators and source links. The original CSV/XLSX publications and their hashes are retained in `data/raw/`; `scripts/build-generation-sites.py` reproduces the import. Source coverage and excluded records are documented in the bundle and the Data & method dialog. Extensions and co-located units can be separate register records.

The generation map opens with 13 source-region summaries using small, subdued capacity markers. One region name and capacity appears on hover or keyboard focus; the side panel keeps the full named comparison. Hovering or focusing a panel row identifies its map marker. Every circle represents total installed capacity on one fixed scale; offshore projects form an explicitly UK-wide summary. Selecting a region opens its actual sites and scopes the totals, list and export. Overview and Reset map return to the regional comparison while preserving search, country and technology filters. Reset filters restores the full catalogue.

Sites mode uses technology colours and one MW scale for individual sites and nearby groups. Groups show combined capacity at their members' capacity-weighted locations; record counts appear in the panel, never as numbers on the map. Bubble area scales with capacity within bounded screen sizes and shrinks when zooming out. Search Enter or Fit results opens and frames matching sites, while typing alone preserves the camera. Filters and exports operate on actual register records, independently of grouping. No site output or capacity factor is fabricated. The separate GB snapshot requests signed Elexon national fuel observations, preserving missing values and stale/error states; these totals are never allocated to individual sites.

The live transfer page requests the public [Elexon FUELINST dataset](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELINST) from the browser. No API key or backend change is required. It preserves signed imports/exports, selects one five-minute observation interval for all ten links, refreshes every 60 seconds, and identifies missing or stale observations. Routes join approximate terminal areas; they are not surveyed cable paths. Cross-border imports do not determine local shortage risk. The Data & method dialog links to source definitions and terminal references.

The operations page reads its simulation values from the API at runtime. The current release uses historical NESO/Elexon demand and Open-Meteo day-ahead weather; dispatch and grid outcomes remain simulated. Small zone markers show shortage status; curved routes show transfer direction, loading colour and a fixed width scale for absolute MW. The map shows at most one corridor value, on hover, keyboard focus or selection. Full readings stay in a compact side-panel table; selecting a zone or route reveals its details. Blank-map clicks, Escape and Clear focus return to the whole network. Snapshot exports preserve the original signed measurements. Route-value and animation controls are under Sources, and their settings are retained in the URL; motion respects reduced-motion settings.

Start the local API from the repository root with `uvicorn api:app --port 8000`. Use the complete exporter-generated root `stubs/` folder, including `replay.json`; keep `api.py` and the loader unchanged. After refreshing data, restart the API and hard-refresh the dashboard. See `LP_STUB_UPDATE.md` for the data audit and validation commands.

Refresh the archived regression fixture after changes to `GridEnv`, scenario inputs or baseline policies:

```powershell
python -B UI/scripts/build-simulation-stubs.py
```

The builder reads the backend's `scenarios/*.json`, calls `make_scenario_env(name)` separately for each strategy, and writes only `UI/assets/simulation-stubs.js`. It uses each scenario's `episode_start_utc` and `selected_from`, discovers additional scenario files, and retains the two response strategies and illustrative-forecast labels. Scenario-specific forecasts use that scenario's recorded start. Source hashes accompany the generated data. The simulator dependencies and selected data files must be available; missing inputs leave the existing fixture unchanged. If the baseline module was supplied under another name, use `--agents-file "agents_baseline(1).py"`. Use `--backend-root` or `--scenarios-dir` to read a separate backend checkout without modifying it.

Every refresh checks all 48 half-hours, aligned strategy/snapshot timelines, forecast issue times, and scoreboard totals against final snapshots before replacing the bundle. It supports the simulator's post-step timestamps without shifting measurements to another interval. Updating the root `stubs/` alone does not update the archived regression fixture. A complete exported replay bundle can also be validated and packaged:

```powershell
python -B UI/scripts/build-simulation-stubs.py --import-bundle path/to/replay.json
python -B UI/scripts/build-simulation-stubs.py --import-bundle UI/assets/simulation-stubs.js --check-only
python -B UI/tests/simulation-bundle.test.py
```

The operations dashboard defaults to the local API on file/localhost previews and to same-origin endpoints on hosted deployments. To select a different API, open:

```text
operations.html?mode=api&api=http://127.0.0.1:8000
```

Alternatively, set `window.JMAP_OPERATIONS_CONFIG = { apiBase: 'http://127.0.0.1:8000' }` before loading `operations-api.js`. Endpoint failures remain visible; archived replay data is never used as a runtime fallback. The API must allow your UI origin through CORS when hosted separately. The UI consumes `/reference`, `/zones`, `/edges`, `/scenarios`, `/state/series`, `/state`, `/compare`, `/forecast/{zone}`, and `/incident` as specified by the project contract. Read-only stub APIs should identify `backend_mode: 'stubs'` in `/reference`.

Refresh the root API stubs and archived regression fixture from the supplied simulator with `python -B UI/scripts/export-api-stubs.py --backend-root dhruv_latest`. This writes a complete `stubs/replay.json` with all 48 full snapshots for every scenario and strategy, alongside the conventional JSON files. The source checkout is read-only. Scenarios with no configured date use UTC midnight of the day selected by reset seed 1; the chosen start and source hashes are recorded. `/state` looks up the exact requested UTC interval and returns 404 for absent times instead of substituting another snapshot. Forecasts also retain their actual scenario, zone and issue time. Custom incident injection is unavailable on the read-only replay API.

Episode cost uses `cost_gbp` alone. Model penalty uses `penalty_gbp` in its own KPI, result detail and CSV column; it never increases displayed cost or changes the cost tie-break. `decision_time_utc` does not change the map or slider labels. API-mode results always come from `GET /compare`; the archived fixture is reserved for automated regressions.

All code, source configuration and tests for these views are inside `UI/`. The backend, simulator inputs and dependency management are maintained separately.

Run the UI data checks from the repository root:

```powershell
node --test UI/tests/*.test.cjs
```

Browser regression checks in `UI/tests/` use Python Playwright and Chromium. They include controlled feed responses so an external outage does not fabricate a test result.

```powershell
python -B UI/tests/transfers-browser.py
python -B UI/tests/live-transfers-browser.py
python -B UI/tests/map-presentation-browser.py
python -B UI/tests/generation-browser.py
python -B UI/tests/site-workflow-browser.py
python -B UI/tests/simulation-refresh-browser.py
python -B UI/tests/area-render-browser.py
python -B UI/tests/motion-browser.py
```

With the root Uvicorn API running, `python -B UI/tests/api-replay.test.py` checks all 288 displayed scenario/strategy snapshots, final scoreboard totals, invalid requests and forecast identity. `python -B UI/tests/api-replay-browser.py` checks the API-only dashboard, separate cost/penalty values and CSVs, map data, time labels and mobile layout.

The live browser suite can additionally check Elexon itself when `JMAP_LIVE_NETWORK_TEST=1` and outbound network access is available.

The response screen always compares `none` (No response (network-blind dispatch)) with `optimiser` (Optimiser). The scoreboard has exactly these two strategy columns and ignores any additional strategy returned by the backend. The historical footnote refers to RL policies and appears only under that table. CSV exports also contain just the two strategies. Numerical results come from `/state`, `/state/series`, `/forecast/{zone}` and `/compare` at runtime; result percentages are calculated from those returned totals. Map legend scales and control limits remain fixed display configuration.

The dominant outcome is the optimiser's full-episode unserved MWh from `/compare`, separate from the time slider's cumulative KPI values. Overload colour classification tolerates LP feasibility residue up to `1e-6` of capacity consistently in the maps, Transfers and Inspect; raw measurements are preserved. Run `python -B UI/tests/lp-demo-browser.py` for the B6 release check. Incident descriptions and selected-scenario tooltips derive trip and shortage times from recorded API frames rather than contradictory source prose. Export validation rejects a replay whose first interval is shifted after its configured episode start.

The timed backup capture and rehearsal guide are in `recordings/README.md`. `scripts/record-b6-demo.py` records the actual dashboard against the running API and regenerates captions from its current results. It stops if the supplied Scottish supply story or optimiser guarantees change.
