# JMap

A compact offline dashboard for inspecting UK electricity use, renewable capacity and national balances.

Open `UI/explorer.html` in a browser. No installation, API key or external map tiles are needed. The simulation dashboard is at `UI/operations.html`.

## Local authority dashboard

The default map has **361 real local-authority boundaries**, with **2024 metered electricity-use data for 350 Great Britain authorities** and renewable-capacity data for 359 UK authorities. Northern Ireland use is unavailable in this GB source and stays grey. ONS 2025 boundaries match the latest reporting codes. Actual boundary changes leave Barnsley and Sheffield unmatched in the older renewable table; no values are reassigned.

The desktop workspace fits the viewport: compact KPIs, map controls, map, searchable scrollable ranking and selected-area detail. Sources and national scenarios open in dialogs. Search by authority, region or ONS code; focus a nation; sort high/low/name; select a polygon or ranking row; zoom into individual boroughs. Selection, geographic detail, measure, filters and ranking order persist in the URL. Export view includes the matching local data, units and source references.

Local measures include total metered use, domestic use, non-domestic use, mean use per domestic meter (MWh), installed renewable capacity (MW), and complete published renewable output (GWh). More than 300 authority renewable-output totals exclude confidential technologies; those incomplete totals remain unknown in the output layer. Capacity and electricity use have much broader coverage. The map uses a fixed full-dataset colour scale capped at its 95th percentile, explicitly marked with `+` in the legend; exact values remain in details and exports. Only the selected authority is labelled at local resolution. Projected paths are cached and reused across updates.

Metered use is final electricity consumption, not gross demand. It excludes electricity generated and consumed directly on site. About 2.90 TWh of unallocated GB consumption is disclosed separately and is not assigned to arbitrary authorities. Local renewable capacity/output does not establish total local generation, supply adequacy or shortage risk. Source cells, definitions and coverage are in `UI/assets/local-energy.js`; ONS boundary attribution is in `UI/assets/README.md`.

Choose **UK nations / balance** for the four-nation official 2025 balance. Colour is `(generation − gross demand) / gross demand`, using a fixed −75% to +75% scale and end colours beyond those limits. Orange indicates deficit; teal indicates surplus. Generation/demand use 0–300 TWh and renewable share uses 0–100%. This coarser layer uses a different period and definition from local metered data.

Switch to Site markers for the original technology symbols and quantitative marker sizes. Search, nation and technology filters, output/capacity/utilisation measures, site labels, pan/zoom, touch and keyboard controls remain available. Fit results frames matching sites. On mobile, expand “Refine this view” for filters.

The analysis panel separates generation, storage discharge and imports, breaks supply down by technology, compares all four nations within the sample and ranks sites. Pin up to three sites for comparison. Site and comparison exports remain available. Site filters, map layer, measures, analysis tabs and pins persist in the URL.

## Official annual balance

The **National balance & scenarios** dialog compares 2025 official annual data for England, Scotland, Wales and Northern Ireland. It remains independent of local meter data and sample site filters.

The table shows gross generation, renewable share, gross demand, signed annual balance and generation divided by demand. Teal bars indicate a surplus and orange bars a deficit; both use the same TWh scale and central zero. Rank by generation/demand, deficit, generation or name. Explore sample sites links focus the corresponding nation on the map.

Gross demand is generation plus net imports, including network losses and generation/storage own use. It differs from final-user consumption. Baseline annual balance equals net exports; a deficit was covered by net imports, not unmet demand. Sources, exact definitions, final consumption figures and limitations are available below the table. The bundled data does not refresh automatically.

Source: [DESNZ electricity generation and supply, 2021 to 2025, published 29 September 2026](https://www.gov.uk/government/statistics/energy-trends-september-2026-special-feature-article-electricity-generation-and-supply-in-scotland-wales-northern-ireland-and-england-2021-to-2025). Dataset values, workbook links and cell provenance are in `UI/assets/regions.js`.

Expand the scenario controls to increase annual demand or reduce annual generation by up to 40%. The balance, generation and demand maps update with the table, retaining the same colour scales. These are uniform sensitivity calculations, not dispatch or outage forecasts. Renewable-share mode retains the published annual mix and its baseline details. Scenario values, labels and CSV exports are distinguished from the official baseline; headline insights retain the published figures. Scenario inputs and table sorting persist in the URL. Reset restores the baseline.

An annual deficit does not establish local shortage risk. That requires peak demand, available generation, storage duration, transfer availability and network constraints. Household electricity access and outage reliability need separate measurements. Northern Ireland is part of the all-island electricity market; UK totals would be accounting sums rather than one operational grid.

## Sample and geography

The 45-site map is a curated demonstration. Outputs are synthetic, and locations/capacities approximate. It is not live telemetry or a complete register. Storage output means discharge and interconnector output means imports. Low-carbon share excludes both and covers wind, solar, nuclear and conventional hydro generation. Do not compare the sample MW/GW snapshot with official annual TWh totals.

Geography is bundled from Natural Earth (public domain); attribution is in `UI/assets/README.md`. Site source references are documented in `UI/assets/sites.js`.

## Verification

Run the analytical and dataset checks with:

```sh
node --test tests/*.test.cjs
```

Optional browser checks require Python Playwright and an installed Chromium browser:

```sh
python tests/browser-smoke.py
```

The browser check covers all 361 local polygons, compact desktop layout, local search/selection/zoom, units, CSV, URL restoration, unknown values, national scenario maps, the sample explorer and responsive widths from 320 to 1440 pixels. It writes review screenshots to the system temporary directory. The application remains buildless.
