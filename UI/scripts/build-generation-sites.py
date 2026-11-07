"""Build the bundled operational-site register from original DESNZ publications.

Run from any directory using this script's absolute path. Optional dependencies
are used only when rebuilding, never by the website:
  python -m pip install --target UI/scripts/.generation-vendor pyproj openpyxl
  python -B UI/scripts/build-generation-sites.py
After rebuilding, the temporary dependency directory can be removed.

The source versions below were the latest verified publications on 7 Nov 2026.
REPD supplies renewable/storage records. DUKES adds only fossil-fuel and nuclear
stations, a disjoint supplement which avoids double-counting renewable stations.
No output measurements, BM-unit matches or availability estimates are fabricated.
"""
from __future__ import annotations

import collections
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
import urllib.request

UI = Path(__file__).resolve().parents[1]
for vendor in (UI / "scripts" / ".generation-vendor", UI / ".vendor"):
    if vendor.is_dir():
        sys.path.insert(0, str(vendor))
try:
    import openpyxl
    from pyproj import Transformer
except ImportError as error:
    raise SystemExit("Rebuilding requires pyproj and openpyxl; install them into UI/scripts/.generation-vendor as documented at the top of this script.") from error

RAW = UI / "data" / "raw"
REPD_URL = "https://assets.publishing.service.gov.uk/media/6a6cbdc00c36759b5ccaa305/REPD_Publication_Q2_2026.csv"
DUKES_URL = "https://assets.publishing.service.gov.uk/media/6a6a365b0ddb7e4831c629f3/DUKES_5.11.xlsx"
REPD_PAGE = "https://www.gov.uk/government/publications/renewable-energy-planning-database-quarterly-extract"
DUKES_PAGE = "https://www.gov.uk/government/statistics/electricity-chapter-5-digest-of-united-kingdom-energy-statistics-dukes"
COUNTRIES = {"England", "Scotland", "Wales", "Northern Ireland"}
TYPE_MAP = {
    "Wind Onshore": "wind_onshore", "Wind Offshore": "wind_offshore",
    "Solar Photovoltaics": "solar", "Small Hydro": "hydro", "Large Hydro": "hydro",
    "Pumped Storage Hydroelectricity": "storage", "Battery": "storage",
    "Liquid Air Energy Storage": "storage", "Compressed Air Energy Storage": "storage", "Flywheels": "storage",
    "Biomass (dedicated)": "biomass", "Biomass (co-firing)": "biomass", "Anaerobic Digestion": "biomass",
    "Landfill Gas": "waste", "Sewage Sludge Digestion": "waste", "EfW Incineration": "waste", "Advanced Conversion Technologies": "waste"
}


def fetch(name, url):
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / name
    if not path.exists():
        request = urllib.request.Request(url, headers={"User-Agent": "JMap official-data build/1.0"})
        path.write_bytes(urllib.request.urlopen(request, timeout=60).read())
    return path


def numeric(value):
    try:
        result = float(str(value).replace(",", "").strip())
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def location(x, y, transformer):
    x, y = numeric(x), numeric(y)
    if x is None or y is None:
        return None
    # Both downloaded registers already encode NI in the British grid too;
    # treating their NI records as Irish Grid would displace them by ~200 km.
    longitude, latitude = transformer.transform(x, y)
    if not (math.isfinite(longitude) and math.isfinite(latitude)):
        return None
    # Includes offshore wind, Hebrides, Orkney and Shetland, but rejects zeros,
    # invalid projected coordinates and records outside the UK/offshore envelope.
    if not (-11 <= longitude <= 5 and 49 <= latitude <= 61.5):
        return None
    return round(latitude, 5), round(longitude, 5)


def read_repd(path, transformer):
    excluded = collections.Counter()
    sites = []
    # This published CSV is Windows-1252, including non-breaking spaces and
    # accented names. Never silently replace undecodable station names.
    try:
        decoded = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = path.read_bytes().decode("cp1252")
    rows = list(csv.DictReader(io.StringIO(decoded, newline="")))
    operational = 0
    seen_ids = set()
    for row_number, row in enumerate(rows, start=2):
        if clean(row["Development Status (short)"]) != "Operational":
            excluded["notOperational"] += 1
            continue
        operational += 1
        source_id = clean(row["Ref ID"])
        if not source_id or source_id in seen_ids:
            excluded["missingOrDuplicateSourceId"] += 1
            continue
        country = clean(row["Country"])
        if country not in COUNTRIES:
            excluded["unknownCountry"] += 1
            continue
        capacity = numeric(row["Installed Capacity (MWelec)"])
        if capacity is None or capacity <= 0:
            excluded["missingOrNonpositiveCapacity"] += 1
            continue
        point = location(row["X-coordinate"], row["Y-coordinate"], transformer)
        if point is None:
            excluded["missingOrOutOfBoundsCoordinates"] += 1
            continue
        original_type = clean(row["Technology Type"])
        seen_ids.add(source_id)
        sites.append({
            "id": f"repd-{source_id}", "name": clean(row["Site Name"]),
            "type": TYPE_MAP.get(original_type, "other"), "capacityMW": capacity,
            "lat": point[0], "lon": point[1], "country": country,
            "operator": clean(row["Operator (or Applicant)"]), "status": "Operational",
            "sourceId": source_id, "sourceUrl": REPD_PAGE, "sourceDate": "2026-08-03",
            "source": "REPD", "sourceRow": row_number, "originalTechnology": original_type,
            "sourceRecordUpdated": clean(row["Record Last Updated (dd/mm/yyyy)"]),
            "region": clean(row["Region"]), "postcode": clean(row["Post Code"]),
            "coordinateSource": "OSGB36 / British National Grid (EPSG:27700)",
        })
    return sites, {"sourceRecords": len(rows), "sourceOperationalRecords": operational, "included": len(sites), "excluded": dict(excluded)}


def read_dukes(path, transformer):
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook["5.11 Full list"]
    sites = []
    excluded = collections.Counter()
    candidate_count = 0
    for row_number, row in enumerate(sheet.iter_rows(min_row=7, max_col=17, values_only=True), start=7):
        if not clean(row[1]) or numeric(row[7]) is None:
            continue
        technology, fuel = clean(row[2]), clean(row[5])
        if technology not in {"Fossil Fuel", "Nuclear"}:
            excluded["renewableOrStorageAlreadyCoveredByREPD"] += 1
            continue
        candidate_count += 1
        capacity = numeric(row[7])
        if capacity <= 0:
            excluded["nonpositiveCapacity"] += 1
            continue
        country = clean(row[9])
        if country not in COUNTRIES:
            excluded["unknownCountry"] += 1
            continue
        point = location(row[13], row[14], transformer)
        if point is None:
            excluded["missingOrOutOfBoundsCoordinates"] += 1
            continue
        name = clean(row[1])
        source_id = f"2026-5.11-row-{row_number}"
        sites.append({
            "id": f"dukes-{source_id}", "name": name,
            "type": "nuclear" if technology == "Nuclear" else "gas" if fuel == "Natural Gas" else "other",
            "capacityMW": capacity, "lat": point[0], "lon": point[1], "country": country,
            "operator": clean(row[0]), "status": "Operational",
            "sourceId": source_id, "sourceUrl": DUKES_PAGE, "sourceDate": "2026-07-30",
            "source": "DUKES", "sourceRow": row_number, "sourceSheet": "5.11 Full list",
            "originalTechnology": f"{technology} / {clean(row[3])} / {fuel}",
            "region": clean(row[10]), "postcode": clean(row[11]),
            "coordinateSource": "OSGB36 / British National Grid (EPSG:27700)",
        })
    workbook.close()
    return sites, {"conventionalCandidates": candidate_count, "included": len(sites), "excluded": dict(excluded)}


def main():
    repd = fetch("REPD_Publication_Q2_2026.csv", REPD_URL)
    dukes = fetch("DUKES_5.11_2026.xlsx", DUKES_URL)
    transformer = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    repd_sites, repd_coverage = read_repd(repd, transformer)
    conventional_sites, dukes_coverage = read_dukes(dukes, transformer)
    sites = sorted(repd_sites + conventional_sites, key=lambda site: (-site["capacityMW"], site["name"], site["id"]))
    assert len({site["id"] for site in sites}) == len(sites), "Duplicate source IDs"
    assert all(site["capacityMW"] > 0 and site["name"] for site in sites)
    assert len([site for site in sites if site["type"] == "nuclear"]) == 5
    metadata = {
        "asOf": "2026-07", "asOfLabel": "REPD July 2026 · conventional stations May 2026",
        "builtOn": datetime.now(timezone.utc).date().isoformat(),
        "title": "Official operational electricity generation and storage sites",
        "sources": [
            {"id": "REPD", "title": "DESNZ Renewable Energy Planning Database, July 2026", "url": REPD_PAGE, "downloadUrl": REPD_URL, "published": "2026-08-03", "period": "July 2026", "sha256": hashlib.sha256(repd.read_bytes()).hexdigest()},
            {"id": "DUKES", "title": "DESNZ DUKES 5.11, operational major power producers at end May 2026", "url": DUKES_PAGE, "downloadUrl": DUKES_URL, "published": "2026-07-30", "period": "May 2026", "sheet": "5.11 Full list", "sha256": hashlib.sha256(dukes.read_bytes()).hexdigest()}
        ],
        "coverage": {
            "siteCount": len(sites), "byType": dict(collections.Counter(site["type"] for site in sites)),
            "byCountry": dict(collections.Counter(site["country"] for site in sites)),
            "REPD": repd_coverage, "DUKES": dukes_coverage,
            "outputAvailable": False, "bmUnitMatchesAvailable": False,
            "notes": [
                "Registered operational sites at the stated source dates, not a live availability register. Some may have changed since publication.",
                "REPD is a planning register for renewable and storage projects generally above 150 kW; it excludes most rooftop solar and is not a complete census.",
                "DUKES supplements only fossil-fuel and nuclear major power producers. Renewable and pumped-storage DUKES rows are deliberately omitted to prevent cross-register duplication.",
                "Each REPD source record is retained as published: extensions, phases and co-located technologies may be separate records. This is a register-record count, not necessarily distinct physical premises.",
                "Coordinates are transformed from supplied OSGB36 X/Y to WGS84 using pyproj. Locations and capacities reflect source quality; DUKES says generator-supplied geography has not been independently verified by DESNZ.",
                "The Northern Ireland coordinates in these particular source files are already encoded in the British grid. They are not reinterpreted as Irish Grid.",
                "Known positive installed capacity is shown in MW, not actual output, available capacity or guaranteed generation. No current site output or capacity factor is inferred.",
                "There is no audited BM-unit-to-site linkage in these sources. No name matching is used to imply live site measurements.",
                "This catalogue does not establish local demand, supply surplus/deficit, network constraints or power-shortage risk."
            ]
        },
        "definitions": {
            "capacityMW": "Published installed electrical capacity in megawatts; storage values are power, not stored energy.",
            "status": "Operational in the cited publication, not guaranteed online now.",
            "sourceId": "REPD Ref ID, or the DUKES 2026 workbook/sheet row identifier where no persistent station ID is published.",
            "sourceDate": "Publication date of the corresponding source; source data period is recorded separately in sources.",
            "other": "Includes conventional diesel/gas-oil plant and smaller marine, hydrogen, geothermal or other technologies. See originalTechnology.",
            "waste": "Energy from waste, landfill gas, sewage digestion and advanced conversion; this grouping does not imply zero-carbon generation."
        },
        "license": {"title": "Open Government Licence v3.0", "url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"}
    }
    content = "/* Generated from original DESNZ registers by UI/scripts/build-generation-sites.py. No synthetic output. */\n(function(root,factory){'use strict';const data=factory();if(typeof module==='object'&&module.exports)module.exports=data;else root.JMAP_GENERATION_SITES=data;})(typeof globalThis==='object'?globalThis:this,function(){'use strict';const data="
    content += json.dumps({**metadata, "sites": sites}, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    content += ";data.sites.forEach(Object.freeze);Object.freeze(data.sites);return Object.freeze(data);});\n"
    output = UI / "assets" / "generation-sites.js"
    output.write_text(content, encoding="utf-8", newline="\n")
    print(json.dumps(metadata["coverage"], indent=2))
    print(f"Wrote {output}: {output.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
