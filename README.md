# JMap

A minimalist interface for exploring the UK's energy infrastructure.

Open `UI/main.html` in a browser to explore the black-and-white energy map. It works directly from the filesystem and needs no install, API key, or external map tiles. The operations overview is at `UI/overview.html`; both pages use the same light, monochrome layout and shared stylesheet. Site directory links open the map's list view directly.

Search sites, choose a nation or technology preset, and switch marker sizes between output/capacity/utilisation. The quantitative marker scale stays fixed across filters. Fit results frames the matching sites; choosing a nation frames that area. Site labels, pan/zoom, full-UK reset, touch gestures and keyboard controls are available. On mobile, expand “Refine this view” for filters.

The analysis panel separates generation, storage discharge and imports; breaks supply down by technology; compares all four nations with the current technology/search filters; and ranks matching sites. Nation comparisons use site location, not electricity transfers. Select a site to inspect it and pin up to three sites for a side-by-side comparison. Pins persist outside current filters and are labelled accordingly. The directory supports sorting and comparison. Export downloads the filtered summary and site rows; comparison has its own CSV export. Filters, measure, labels, analysis tab and comparison pins are retained in the page URL.

The 45-site dataset is a curated demonstration across England, Scotland, Wales and Northern Ireland. Output figures are synthetic, and locations/capacities approximate. It is not live telemetry or a complete register. Storage output means discharge and interconnector output means imports. Low-carbon share excludes both and covers wind, solar, nuclear and conventional hydro generation. UK aggregates describe this portfolio, not a single electricity-system balance. Demand, transmission flows and constraints are not included, so the map cannot infer local supply adequacy or transfers between nations.

Geography is bundled from Natural Earth (public domain); attribution is in `UI/assets/README.md`. Dataset source references are documented in `UI/assets/sites.js`. Replace that data file with validated telemetry to connect a production data source.

Run the analytical checks with `node --test tests/analysis.test.cjs`. The UI remains buildless and can be opened directly in a browser.
