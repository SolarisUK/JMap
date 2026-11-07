# JMap UI

Open `main.html` or `generation.html` for the main UK generating-site map. `transfers.html` shows live GB interconnector flows, `explorer.html` contains historical local energy statistics, and `operations.html` is the separate simulator. The pages are buildless and can be opened directly or served by any static HTTP server.

All dashboard pages use the shared minimalist black and charcoal palette in `theme-dark.css`, including native controls, dialogs and scrollbars. Interface highlights are neutral grey; colour is reserved for data and status.

Navigation, header sizing and map controls are shared through `site-shell.css`. `map-interactions.js` prevents accidental text selection during map gestures while keeping ordinary text copying and field editing available. Map buttons use the same zoom step and reset behavior; Ctrl/Meta + wheel retains browser zoom. Live-transfer labels, endpoints and direction arrows remain screen-sized when zooming. Cancelled gestures release their drag state; Escape or a blank-map click clears an inspected site or zone.

The generation map uses `assets/generation-sites.js`, imported from the official DESNZ REPD July 2026 and DUKES May 2026 operating-asset registers. It includes renewable/storage projects and conventional gas/nuclear stations, with published capacities, coordinates, operators and source links. The original CSV/XLSX publications and their hashes are retained in `data/raw/`; `scripts/build-generation-sites.py` reproduces the import. Source coverage and excluded records are documented in the bundle and the Data & method dialog. Extensions and co-located units can be separate register records.

The generation map opens with 13 named source-region summaries. Every circle represents total installed capacity on one fixed scale; offshore projects form an explicitly UK-wide summary. Selecting a region opens its actual sites and scopes the totals, list and export. Overview and Reset map return to the regional comparison while preserving search, country and technology filters. Reset filters restores the full catalogue.

Sites mode uses technology colours and one MW scale for individual sites and nearby groups. Groups show combined capacity at their members' capacity-weighted locations; record counts appear in the panel, never as numbers on the map. Bubble area scales with capacity within bounded screen sizes and shrinks when zooming out. Search Enter or Fit results opens and frames matching sites, while typing alone preserves the camera. Filters and exports operate on actual register records, independently of grouping. No site output or capacity factor is fabricated. The separate GB snapshot requests signed Elexon national fuel observations, preserving missing values and stale/error states; these totals are never allocated to individual sites.

The live transfer page requests the public [Elexon FUELINST dataset](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELINST) from the browser. No API key or backend change is required. It preserves signed imports/exports, selects one five-minute observation interval for all ten links, refreshes every 60 seconds, and identifies missing or stale observations. Routes join approximate terminal areas; they are not surveyed cable paths. Cross-border imports do not determine local shortage risk. The Data & method dialog links to source definitions and terminal references.

The operations page defaults to the existing UI-contained simulation bundle. These episodes are explicitly labelled synthetic and simulated. Small zone markers show shortage status; curved routes show transfer direction, loading colour and a fixed width scale for absolute MW. The map shows at most one corridor value, on hover, keyboard focus or selection. Full readings stay in a compact side-panel table; selecting a zone or route reveals its details. Blank-map clicks, Escape and Clear focus return to the whole network. Snapshot exports preserve the original signed measurements. `Focused MW` and `Motion` settings are retained in the URL; motion respects reduced-motion settings.

To connect the operations page to a separately managed contract-compatible API, open:

```text
operations.html?mode=api&api=http://127.0.0.1:8000
```

Alternatively, set `window.JMAP_OPERATIONS_CONFIG = { mode: 'api', apiBase: 'http://127.0.0.1:8000' }` before loading `operations-api.js`. Endpoint failures remain visible; an API failure never silently replaces observations with simulated data. The API must allow your UI origin through CORS when hosted separately. The UI consumes `/reference`, `/zones`, `/edges`, `/scenarios`, `/state/series`, `/state`, `/compare`, `/forecast/{zone}`, and `/incident` as specified by the project contract. Read-only stub APIs should identify `backend_mode: 'stubs'` in `/reference`.

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
```

The live browser suite can additionally check Elexon itself when `JMAP_LIVE_NETWORK_TEST=1` and outbound network access is available.
