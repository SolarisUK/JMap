# JMap

A minimalist interface for exploring Britain's energy infrastructure.

Open `UI/main.html` in a browser to explore the black-and-white energy map. It works directly from the filesystem and needs no install, API key, or external map tiles. The previous dashboard remains at `UI/overview.html`.

Search sites, filter by region and technology, switch marker sizes between output/capacity/utilisation, or use the sortable directory to locate an asset. Select a marker for details. Drag to pan, scroll/pinch to zoom, and use the map controls to reset. Keyboard help is available below the map. Export downloads the filtered dataset as CSV.

The 40-site dataset is a curated demonstration: output figures are synthetic, and locations/capacities approximate. It is not live telemetry or a complete register. Storage output means discharge and interconnector output means imports. Low-carbon share excludes both and covers wind, solar, nuclear and conventional hydro generation.

Geography is bundled from Natural Earth (public domain); attribution is in `UI/assets/README.md`. Dataset source references are documented in `UI/assets/sites.js`. Replace that data file with validated telemetry to connect a production data source.
