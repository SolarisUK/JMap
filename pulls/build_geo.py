"""Stage 7: merge NESO's 14 DNO areas into the contract's 10 model zones.

Run from JMap: python pulls/build_geo.py --offline
The shapes represent approximate DNO service areas, not administrative regions.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from shapely.geometry import mapping, shape

from pull_neso import make_session


SOURCE_URL = ("https://api.neso.energy/dataset/0e377f16-95e9-4c15-a1fc-49e06a39cfa0/"
              "resource/1c6a7dc0-1b6c-443a-bc67-5f7125649434/download/"
              "gb-dno-license-areas-20240503-as-geojson.geojson")
SOURCE_PAGE = "https://www.neso.energy/data-portal/gis-boundaries-gb-dno-license-areas"

# NESO's source Name codes -> model zone. Source Area labels are checked below.
# North Wales is explicitly the DNO area including Merseyside and Cheshire.
SOURCE_TO_ZONE = {
    "_P": "NSCO", "_N": "SSCO", "_F": "NORT", "_G": "NORT", "_M": "YORK",
    "_D": "WALE", "_K": "WALE", "_E": "MIDL", "_B": "MIDL", "_A": "EAST",
    "_L": "SWES", "_C": "LOND", "_H": "SOUT", "_J": "SOUT",
}
SOURCE_NAMES = {
    "_P": "North Scotland", "_N": "South and Central Scotland",
    "_F": "North East England", "_G": "North West England", "_M": "Yorkshire",
    "_D": "North Wales, Merseyside and Cheshire", "_K": "South Wales",
    "_E": "West Midlands", "_B": "East Midlands", "_A": "East England",
    "_L": "South West England", "_C": "London", "_H": "Southern England", "_J": "South East England",
}
PROPERTIES = ("zone_id", "name", "demand_share", "storage_mwh", "dr_mw")
SIZE_LIMIT = 2_000_000


def load_zones(root, exported):
    if exported is not None:
        zones = json.loads(exported.read_text(encoding="utf-8"))
    else:
        spec = importlib.util.spec_from_file_location("_geo_contract", root / "schemas.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        zones = [{"zone_id": z.id, "name": z.name, "demand_share": float(z.demand_share),
                  "storage_mwh": float(z.storage_mwh), "dr_mw": float(z.dr_mw)} for z in module.ZONES]
        if [z["zone_id"] for z in zones] != list(module.ZONE_ORDER):
            raise ValueError("Contract ZONES and ZONE_ORDER disagree")
    if len({z["zone_id"] for z in zones}) != len(zones) or set(SOURCE_TO_ZONE.values()) != {z["zone_id"] for z in zones}:
        raise ValueError("Source mapping does not match the contract's zones")
    if not np.isclose(sum(z["demand_share"] for z in zones), 1, rtol=0, atol=1e-12):
        raise ValueError("Contract demand shares do not sum to one")
    return zones


def load_source(root, offline):
    folder = root / "data/raw/geo"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "gb_dno_20240503.geojson"
    metadata_path = path.with_suffix(".source.json")
    if not path.exists() and not offline:
        with make_session() as session:
            response = session.get(SOURCE_URL, timeout=(15, 90))
            response.raise_for_status()
        # Preserve the source response before any geometry parsing.
        path.write_bytes(response.content)
        metadata_path.write_text(json.dumps({
            "source_url": SOURCE_URL, "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(response.content).hexdigest(),
        }, indent=2)+"\n", encoding="utf-8")
    if not path.exists() or not metadata_path.exists():
        raise FileNotFoundError("Missing saved DNO boundaries; run without --offline to download them")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata["source_url"] != SOURCE_URL or metadata["sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError("Saved DNO source URL or hash does not match")
    frame = gpd.read_file(path)
    if frame.crs is None or frame.crs.to_epsg() != 27700:
        raise ValueError("Expected the source's British National Grid CRS, EPSG:27700")
    if len(frame) != len(SOURCE_TO_ZONE) or set(frame.Name) != set(SOURCE_TO_ZONE) or frame.Name.duplicated().any():
        raise ValueError("Source does not contain the 14 expected DNO groups")
    for code, name in zip(frame.Name, frame.Area):
        if SOURCE_NAMES[code] != name:
            raise ValueError(f"Unexpected source label for {code}: {name}")
    if not frame.is_valid.all() or frame.is_empty.any() or not frame.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError("Invalid or non-polygon source geometry")
    return frame, metadata


def feature_collection(frame, zones):
    geographic = frame.to_crs(4326)
    geographic.geometry = shapely.orient_polygons(geographic.geometry.to_numpy())
    features = []
    for zone in zones:
        geom = geographic.loc[zone["zone_id"], "geometry"]
        features.append({"type": "Feature", "properties": {key: zone[key] for key in PROPERTIES},
                         "geometry": mapping(geom)})
    return {"type": "FeatureCollection", "features": features}


def validate_geojson(payload, zones):
    if payload.get("type") != "FeatureCollection" or len(payload.get("features", [])) != len(zones):
        raise ValueError("Unexpected GeoJSON collection type or size")
    geometries = []
    for feature, zone in zip(payload["features"], zones):
        if feature.get("type") != "Feature" or set(feature["properties"]) != set(PROPERTIES):
            raise ValueError("GeoJSON properties must be exactly the five contract keys")
        if feature["properties"] != {key: zone[key] for key in PROPERTIES}:
            raise ValueError("Feature properties disagree with schemas.ZONES")
        geom = shape(feature["geometry"])
        if geom.is_empty or not geom.is_valid or geom.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"Invalid geometry for {zone['zone_id']}")
        x0, y0, x1, y1 = geom.bounds
        if not (-9.5 < x0 <= x1 < 2.5 and 49 < y0 <= y1 < 61.5):
            raise ValueError("Coordinates fall outside the GB longitude/latitude range")
        geometries.append(geom)
    if not shapely.coverage_is_valid(geometries):
        raise ValueError("Serialized zone geometries have overlapping or mismatched shared edges")
    return geometries


def preview(frame, zones, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    fig = plt.figure(figsize=(9, 10.5), facecolor="white")
    ax = fig.add_axes([.05, .14, .61, .72])
    colors = plt.get_cmap("tab10").colors
    order = [z["zone_id"] for z in zones]
    for i, zone in enumerate(zones):
        geom = frame.loc[zone["zone_id"], "geometry"]
        gpd.GeoSeries([geom], crs=27700).plot(ax=ax, color=colors[i], edgecolor="white", linewidth=.35)
        point = geom.representative_point()
        if zone["zone_id"] == "LOND":
            ax.annotate(zone["zone_id"], xy=(point.x, point.y), xytext=(42, -7), textcoords="offset points",
                        fontsize=9, weight="bold", arrowprops={"arrowstyle": "-", "color": "#36464e"},
                        bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.5})
        else:
            ax.text(point.x, point.y, zone["zone_id"], ha="center", va="center", fontsize=8.5,
                    weight="bold", bbox={"facecolor": "white", "alpha": .86, "edgecolor": "none", "pad": 1.5})
    ax.set_axis_off()
    ax.set_aspect("equal")
    handles = [Patch(facecolor=colors[i], label=z["zone_id"]+"  "+z["name"]) for i,z in enumerate(zones)]
    fig.legend(handles=handles, loc="center left", bbox_to_anchor=(.64, .57), frameon=False,
               fontsize=9, labelspacing=1.4, handlelength=1.2)
    fig.text(.07, .945, "GB model zones", fontsize=23, weight="bold", color="#172d36")
    fig.text(.07, .90, "Ten model zones merged from 14 approximate DNO service areas", fontsize=10.5, color="#53656f")
    fig.text(.07, .085, "Source: NESO DNO licence boundaries, 03 May 2024. Colours identify zones.", fontsize=9, color="#53656f")
    fig.text(.07, .058, "Service areas cross administrative borders; WALE includes Merseyside and Cheshire.", fontsize=9, color="#53656f")
    fig.savefig(path, dpi=160, facecolor="white")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--zones-file", type=Path, help="Optional exported zone metadata; default reads schemas.py")
    args = parser.parse_args()
    root = args.root.resolve()
    if not hasattr(shapely, "coverage_clean") or shapely.geos_version < (3,14,0):
        raise SystemExit("Upgrade GIS packages: python -m pip install --upgrade geopandas shapely pyproj")
    zones = load_zones(root, args.zones_file)
    source, source_meta = load_source(root, args.offline)
    source["zone_id"] = source.Name.map(SOURCE_TO_ZONE)
    dissolved = source.dissolve(by="zone_id").reindex([z["zone_id"] for z in zones])
    original = dissolved.geometry.to_numpy()
    # Repair only tiny overlaps / non-matching edges. Do not fill geographic gaps.
    cleaned = shapely.coverage_clean(original, gap_width=0, merge_strategy="longest_border")
    cleanup_m2 = sum(a.symmetric_difference(b).area for a,b in zip(original, cleaned))
    total_area = sum(g.area for g in original)
    if cleanup_m2 / total_area > .00001 or not shapely.coverage_is_valid(cleaned):
        raise ValueError("Source topology needs more than a tiny cleanup; inspect it before proceeding")
    for tolerance in [100.,150.,200.,300.]:
        simplified = shapely.coverage_simplify(cleaned, tolerance)
        candidate = dissolved.copy()
        candidate.geometry = simplified
        collection = feature_collection(candidate, zones)
        raw = json.dumps(collection, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        vertices = int(shapely.get_num_coordinates(simplified).sum())
        if len(raw) < SIZE_LIMIT and vertices < 50_000:
            break
    else:
        raise ValueError("GeoJSON remains too large at the permitted simplification tolerances")
    area_change = np.abs(shapely.area(simplified) - shapely.area(original)) / shapely.area(original)
    if (area_change > .01).any():
        raise ValueError("Simplification changed an individual zone's area by over one percent")
    validate_geojson(json.loads(raw), zones)
    folder = root / "data/geo"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "zones.geojson"
    temp = path.with_suffix(".geojson.tmp")
    temp.write_bytes(raw)
    temp.replace(path)
    results = root / "results"
    results.mkdir(parents=True, exist_ok=True)
    preview(candidate, zones, results / "zones_preview.png")
    centroids = gpd.GeoSeries(candidate.geometry.centroid, crs=27700).to_crs(4326)
    rows = [{"zone_id": z["zone_id"], "area_km2": float(candidate.loc[z["zone_id"]].geometry.area/1e6),
             "centroid_lon": float(centroids.loc[z["zone_id"]].x), "centroid_lat": float(centroids.loc[z["zone_id"]].y),
             "source_groups": [code for code, zone in SOURCE_TO_ZONE.items() if zone==z["zone_id"]]}
            for z in zones]
    lines = ["Stage 7 zone polygons: PASS", f"Zones: {len(zones)}; GeoJSON bytes: {len(raw):,}; coordinate pairs: {vertices:,}",
             "All geometries valid and non-empty; shared edges match; output CRS: WGS84 longitude/latitude.",
             "Properties exactly: "+", ".join(PROPERTIES),
             f"Topology cleanup changed {cleanup_m2:.2f} m2; simplification tolerance: {tolerance:g} m.",
             f"Maximum individual-zone area change: {100*area_change.max():.5f}%",
             "zone | area km2 (British National Grid) | centroid longitude | centroid latitude"]
    lines += [f"{r['zone_id']} | {r['area_km2']:,.2f} | {r['centroid_lon']:.5f} | {r['centroid_lat']:.5f}" for r in rows]
    lines += ["Approximate DNO service areas, not administrative regions or exact transmission-bus territories.",
              "WALE includes North Wales, Merseyside and Cheshire plus South Wales; LOND is the London DNO area.",
              "The existing demand allocation is unchanged and is not a measured load for these polygons."]
    report = "\n".join(lines)+"\n"
    (results / "stage7_checks.txt").write_text(report, encoding="utf-8")
    provenance = {"source_page": SOURCE_PAGE, "source_file": source_meta, "source_version": "2024-05-03",
                  "licence": "NESO Open Data Licence; see source dataset",
                  "source_crs": "EPSG:27700", "output_crs": "EPSG:4326",
                  "source_to_zone": SOURCE_TO_ZONE, "source_names": SOURCE_NAMES, "zones": zones,
                  "cleanup_symmetric_difference_m2": cleanup_m2, "simplification_tolerance_m": tolerance,
                  "maximum_zone_area_change_pct": float(100*area_change.max()), "output_bytes": len(raw),
                  "coordinate_pairs": vertices, "output_sha256": hashlib.sha256(raw).hexdigest(),
                  "geometry_checks": "valid, non-empty, edge-matched and non-overlapping after serialization",
                  "zone_statistics": rows, "boundary_kind": "approximate DNO service areas, not administrative borders"}
    (folder / "zones.provenance.json").write_text(json.dumps(provenance, indent=2)+"\n", encoding="utf-8")
    print(report, end="")
    print(f"Wrote: {path}")
    print(f"Wrote: {results / 'zones_preview.png'}")


if __name__ == "__main__":
    main()
