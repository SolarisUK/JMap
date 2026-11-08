# Optimisation-engine presentation changes

Slides are excluded at the user's request. This change modifies UI files only. The API, its endpoint names, query field names and root stub files are not modified by this change.

## Dashboard and wording

- `operations.html`: removed the archived numerical-data script and offline fallback button; titled the panels No response and Optimiser; changed the scoreboard to exactly two strategy columns; added the requested historical footnote; removed fixed episode-length copy from the scoreboard/timeline placeholders.
- `operations.js`: fixed the right-hand series and snapshots to `optimiser`, retained `none` on the left, restricted the response selector, removed the retired response/placeholder branches and export metadata, and replaced response-layer descriptions with optimisation-engine wording. The scoreboard and CSV now contain only the two requested strategies. Episode counts use the returned series length.
- `operations-analysis.js`: compares only `none` and `optimiser`; removed placeholder handling. Existing arithmetic, treatment of unknown values, cost/penalty separation and ranking rules are preserved. The forecast renderer is unchanged.
- `operations-api.js`: all dashboard data now comes from HTTP requests at runtime. File/localhost previews default to the local API; hosted deployments use the same origin unless an API base is configured. Removed archive reads and fallback logic. All endpoint paths and query/JSON field names are preserved.
- `assets/simulation-stubs.js`: retained only the two strategies in this unused runtime archive, and removed obsolete placeholder flags. The remaining measurements are unchanged; this file is used solely by offline regression fixtures.
- `scripts/build-simulation-stubs.py`: generates only the two requested strategies and no longer creates a copied third run or its placeholder metadata. Backend source filenames and import interfaces are retained for compatibility.
- `README.md`: documents API-only runtime data, the two-strategy presentation, archived test-fixture usage and updated checks.

## Verification changes

- `tests/replay_fixture.py`: new HTTP fixture adapter so offline regressions test the same API-only client as production.
- `tests/operations-api.test.cjs`: tests runtime API defaults, existing endpoint/query fields, configured API bases and visible API failures.
- `tests/operations-analysis.test.cjs`: tests two-strategy arithmetic and verifies that extra API strategies cannot appear or win.
- `tests/api-replay-browser.py`: checks the ordinary API-backed entry point, both runs, exactly two scoreboard columns, the requested footnote, complete CSV values, endpoint-driven forecasts and changed API responses with no numerical archive loaded.
- `tests/api-replay.test.py`: checks only the two displayed strategies, covering 288 full snapshots across the supplied three scenarios.
- `tests/simulation-bundle.test.py`: checks two-strategy generated fixtures and final totals.
- `tests/simulation-refresh-browser.py`: verifies updated two-strategy scoreboards and CSVs across six fixture scenarios.
- `tests/map-presentation-browser.py`, `tests/transfers-browser.py`, `tests/site-workflow-browser.py`, `tests/motion-browser.py`: use the HTTP fixture adapter; their map, forecast, gesture and layout assertions are retained.
- `OPTIMISER_CHANGES.md`: this complete change list and numerical-data audit.

## Numerical-data audit

No fixed measured values or performance results remain in the operations runtime. Full-episode scoreboard values come from `GET /compare`; map/snapshot values come from `/state` and `/state/series`; forecast quantiles come from `/forecast/{zone}`. Percentages and summaries are calculated from those responses. Cost and model penalty remain separate. API failures do not select archived values.

The unchanged map contains fixed **scale labels**, not result figures: the 0.05 MW shortage display tolerance, 1,000 MW ramp endpoint, 75%/100% loading boundaries, and 100/1,000/5,000 MW flow-width references. Incident controls likewise retain parameter examples (one-half-hour minimum, demand multiplier 1.18 and 90% capacity loss). These are display/configuration constants; `/compare` does not return them. They remain intact because the map and styling were explicitly excluded from changes. No slide figures were modified.

Other retained configuration numbers are the incident start/duration defaults (34/12), their input bounds (0–47 and 1–48), the initial selected frame index (38), and reporting thresholds (1 MWh for a substantive baseline and 0.1 MWh for a numerical tie). These select or explain API measurements; they are not reported performance figures. Forecast percentile identifiers and the forecast renderer remain unchanged.

Source URLs/legal titles, the HTTP `User-Agent` header, official operator names in source data, upstream baseline-module filenames and provenance keys retain their original identifiers. They do not describe the project's response layer and changing them would alter unrelated data or interfaces.

At the time of this presentation-only change, the API reported legacy heuristic implementation metadata. The subsequent upgraded LP data and current server setup are documented in `LP_STUB_UPDATE.md`.

## Upgraded optimiser dashboard fixes

- `operations.html`, `operations.css`, `operations.js`: keep the API-driven full-episode unserved figure prominent above the map, label slider-dependent cost as Cost so far, clear the outcome during loading/errors, suppress rounded negative zero and show penalty reduction separately. The scoreboard still has only No response and Optimiser.
- `operations-analysis.js`: guard percentage calculations against zero, unknown and non-finite inputs. Derive line-trip descriptions from the first recorded unavailable/derated corridor and no-response shortage frames, preserving API timestamps.
- `operations-map.js`, `operations-transfers.js`, `operations.js`: apply the same `1e-6` loading tolerance in the maps, Transfers and Inspect. Preserve raw values and meaningful baseline overloads.
- `scripts/build-simulation-stubs.py`: reject replays shifted after their configured start; retain the existing deterministic seeded-start option. `scripts/export-api-stubs.py` fingerprints the conventional files alongside the complete replay. Backend source files remain read-only.
- `tests/lp-demo-browser.py`: verify the B6 release scoreboard, all 48 map and Inspect frames, incident-description timestamps, dominant outcome, zero baselines, signed zero and compact layouts. Updated analysis, corridor, replay and refresh tests cover the same behavior and prevent the old half-hour offset.
- `README.md`, `LP_STUB_UPDATE.md`: document standard `api:app` startup, exporter-only data refresh, current verification results and the recording guide. Compatibility-loader files are unchanged and excluded from this dashboard update.

Validation passed: all 85 Node tests; three API replay tests covering 288 snapshots; seven replay/export validation tests; API and B6 browser checks; six-scenario refresh checks; site workflows on all four pages; and six motion tests. No API code or loader changes are included.
