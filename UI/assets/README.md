# Map geography

`geography.js` contains local outlines derived from Natural Earth's **1:50m Admin 0 – Countries** dataset. It covers the United Kingdom, Ireland, and nearby European land. No tile server or runtime download is required.

- Dataset: https://www.naturalearthdata.com/downloads/50m-cultural-vectors/50m-admin-0-countries-2/
- Source GeoJSON: https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson
- License: **Public domain**, as described at https://www.naturalearthdata.com/about/terms-of-use/
- Prepared: 7 November 2026.

The source exterior rings were filtered for the regional map, simplified with a Douglas–Peucker tolerance of 0.007 degrees for the United Kingdom/Ireland/Isle of Man and 0.018 degrees for other countries, and rounded to four decimal places. Small islands are retained where the simplified exterior has at least four points. Polygon holes are omitted. These are illustrative map outlines, not survey or navigational boundaries.

The script defines `window.JMAP_GEOGRAPHY = { features: [{ name, polygons }] }`. Each `polygons` entry is a closed exterior ring of `[longitude, latitude]` pairs in WGS84. Projection and viewport clipping are handled by the UI.

## UK site sample

`sites.js` contains **45 representative UK sites**: the original 40-site Great Britain sample plus five Northern Ireland sites. Northern Ireland uses the region key `northern-ireland`; other region keys are `england`, `scotland`, and `wales`. Irish land is shown for geographic context, but the sample does not include Republic of Ireland generation sites.

All output values are synthetic demonstration figures in MW, not live or historical readings. Coordinates and capacities are approximate, and this is not a complete or representative census of generating assets. Regional shares describe only this curated sample. The data contains no demand measurements, transmission flows, distribution circuits, network constraints, losses, or dispatch schedules. UK totals are illustrative site aggregates, **not a measured power balance** across the GB and all-island systems. Northern Ireland is operated by [SONI](https://www.soni.ltd.uk/about-us/what-we-do) and is connected with Ireland and Great Britain; a site map must not imply that all UK output belongs to a single synchronous grid.

Northern Ireland sample references:

- [EPUKi: Ballylumford](https://www.epuki.co.uk/about/our-power-stations/ballylumford/) — gas technology and 688 MW station capacity.
- [EPUKi: Kilroot](https://www.epuki.co.uk/about/our-power-stations/kilroot/) — two 350 MW gas turbines. The sample represents these **700 MW gas units only**, excluding the site's separate oil-fired units.
- [SSE Renewables: Slieve Kirk Wind Park](https://www.sserenewables.com/onshore-wind/northern-ireland/slieve-kirk-wind-park/) — approximately 73.6 MW across the wind-farm cluster; the map uses one approximate cluster point.
- [ESB: Crockdun](https://esb.ie/what-we-do/generation-and-trading/crockdun---wind) — 12.5 MW wind farm and approximate coordinates.
- [RES: Ballygarvey solar O&M](https://www.res-group.com/resources/news/res-doubles-down-with-new-solar-om-contracts/) — 8.2 MW solar site; the map uses an approximate location near Ballymena and a descriptive asset-company label.

References establish site identity and approximate technology/capacity; **none supplies the synthetic output figures**. Checked 7 November 2026.
