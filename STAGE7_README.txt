Stage 7: real zone polygons

Extract this ZIP into C:\Users\ranya\JMap. The pulls, data and results folders
belong directly inside JMap, beside schemas.py and the earlier stage files.

Run from a fresh PowerShell prompt in JMap:

    python .\pulls\build_geo.py --offline

Expected: Stage 7 zone polygons: PASS. The saved raw source is included, so
this command makes no network requests. It reads all five output properties
from your current schemas.ZONES and keeps features in schemas.ZONE_ORDER.

The GIS packages were installed in Stage 0 and matplotlib in Stage 6. If the
script reports that the GIS libraries need upgrading, run:

    python -m pip install --upgrade geopandas shapely pyproj

The topology cleanup requires Shapely 2.2+ with GEOS 3.14+. Do not skip its
version check: older coverage simplification tools can retain overlapping edges.

Outputs
-------
data/geo/zones.geojson             Ten zone polygons for Leonard's map
data/geo/zones.provenance.json     Mapping, source, geometry checks and hashes
results/zones_preview.png          Visually checked static map preview
results/stage7_checks.txt          Areas, centroids, sizes and validation results
pulls/build_geo.py                 Reusable builder with explicit mapping dict
data/raw/geo/gb_dno_20240503.*      Original source response and metadata

GeoJSON contract
----------------
FeatureCollection, with one Polygon or MultiPolygon for each contract zone.
Every feature has exactly these properties:

    zone_id, name, demand_share, storage_mwh, dr_mw

The output is WGS84 longitude/latitude (EPSG:4326), as required for GeoJSON maps.
The source is British National Grid (EPSG:27700); it is reprojected before export.
The prepared file has 1,081,648 bytes and 27,199 coordinate pairs, below 2 MB.
All geometries are valid, non-empty, non-overlapping and share matching edges.

Source-to-zone mapping
----------------------
NSCO <- _P, North Scotland
SSCO <- _N, South and Central Scotland
NORT <- _F + _G, North East England + North West England
YORK <- _M, Yorkshire
WALE <- _D + _K, North Wales/Merseyside/Cheshire + South Wales
MIDL <- _E + _B, West Midlands + East Midlands
EAST <- _A, East England
SWES <- _L, South West England
LOND <- _C, London
SOUT <- _H + _J, Southern England + South East England

These are source DNO group codes, not Carbon Intensity API numeric region IDs.
All 14 source codes and their source Area labels are checked before merging.

Geometry processing
-------------------
The source is dissolved into the ten zones in a projected CRS. Its tiny overlaps
and non-matching shared edges are cleaned, with gap filling disabled. The total
changed area is about 633.65 square metres. Shared boundaries are simplified
together at a 100 m tolerance, so simplification does not create mismatched edges.
The maximum individual-zone area change is about 0.00698%.

The file is checked again after JSON serialization, including property values,
geometry validity, GB coordinate bounds and shared-edge consistency. The preview
was inspected to confirm that it looks like Britain and the labels are placed
correctly. Area calculations use EPSG:27700; centroids are printed in longitude
and latitude. Map labels use interior points so islands do not pull labels offshore.

Geographic interpretation
--------------------------
This follows the DNO-boundary route suggested in the runbook. The shapes are
approximate electricity-service areas, not administrative regions or exact
transmission-bus catchments. The model names remain the contract names.

In particular, WALE includes the North Wales, Merseyside and Cheshire DNO area,
and LOND is the London DNO licence area rather than the Greater London boundary.
Other DNO areas also cross administrative borders. NESO describes this dataset
as approximate. The geometry uses the published 03 May 2024 boundary snapshot;
it does not claim to reconstruct changing boundaries through the training window.

Demand shares, estimated demand values, storage and demand-response assumptions
are unchanged. The map does not turn the allocation into measured regional load.

The preparatory build used zone metadata printed in the supplied schemas.py
history. Your local rebuild reads your full current schemas.py as authority.

Attribution
-----------
Source: National Energy System Operator, GB DNO Licence Areas 20240503.
Licence: NESO Open Data Licence; see the dataset page.
https://www.neso.energy/data-portal/gis-boundaries-gb-dno-license-areas

Next: Stage 8, regenerate the API stubs and prepare the handover.
