# Map geography

`geography.js` contains local outlines derived from Natural Earth's **1:50m Admin 0 – Countries** dataset. It covers the United Kingdom, Ireland, and nearby European land. No tile server or runtime download is required.

- Dataset: https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-countries-2/
- Source GeoJSON: https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson
- License: **Public domain**, as described at https://www.naturalearthdata.com/about/terms-of-use/
- Prepared: 7 November 2026.

The source exterior rings were filtered for the regional map, simplified with a Douglas–Peucker tolerance of 0.007 degrees for the United Kingdom/Ireland/Isle of Man and 0.018 degrees for other countries, and rounded to four decimal places. Small islands are retained where the simplified exterior has at least four points. Polygon holes are omitted. These are illustrative map outlines, not survey or navigational boundaries.

The script defines `window.JMAP_GEOGRAPHY = { features: [{ name, polygons }] }`. Each `polygons` entry is a closed exterior ring of `[longitude, latitude]` pairs in WGS84. Projection and viewport clipping are handled by the UI.
