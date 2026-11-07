# JMap

An offline interface for understanding UK electricity supply and distribution.

Open `UI/main.html` in a browser. No installation, API key or external map tiles are needed. The operations overview is at `UI/overview.html`.

## Regional heatmap

The map opens with a choropleth of official annual electricity balances using actual boundaries for England, Scotland, Wales and Northern Ireland. Filled regions and numeric labels show where annual generation exceeds or falls short of gross demand. Colour measures `(generation − demand) / demand`, on a fixed scale from −75% to +75% with end colours for values beyond those limits. Orange indicates a deficit and teal a surplus. Normalising by demand makes the relative gap comparable across differently sized nations.

Switch the map measure to annual generation, gross demand, or renewable generation share. Generation and demand use the same fixed 0–300 TWh colour scale, while renewable share uses 0–100%. Each legend gives numeric units. Select a nation by clicking its polygon or label, using the ranking, or pressing Enter/Space on a focused nation. Its detail panel shows generation, gross demand, annual balance and coverage. The selected nation, measure and layer persist in the URL.

This is explicitly a **four-nation comparison**, with one value per nation. It does not claim to show local differences, electricity access, transmission routes or outage likelihood. The site sample is hidden in regional mode so synthetic site outputs cannot be confused with official annual figures. Natural Earth nation boundary provenance is in `UI/assets/README.md`.

Switch to Site markers for the original technology symbols and quantitative marker sizes. Search, nation and technology filters, output/capacity/utilisation measures, site labels, pan/zoom, touch and keyboard controls remain available. Fit results frames matching sites. On mobile, expand “Refine this view” for filters.

The analysis panel separates generation, storage discharge and imports, breaks supply down by technology, compares all four nations within the sample and ranks sites. Pin up to three sites for comparison. Site and comparison exports remain available. Site filters, map layer, measures, analysis tabs and pins persist in the URL.

## Official annual balance

The separate Surplus & deficit section compares **2025 official annual data** for England, Scotland, Wales and Northern Ireland. Headline insights identify the most generation relative to demand, the largest annual deficit and the largest electricity generator. This section is independent of sample site filters.

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

The browser check covers regional polygons and selection, map metrics, scenario colours and baseline separation, annual ranking, CSV contents, reset, URL restoration, linked sample filtering, layer persistence, runtime errors and responsive widths from 320 to 1440 pixels. It writes review screenshots to the system temporary directory. The application remains buildless.
