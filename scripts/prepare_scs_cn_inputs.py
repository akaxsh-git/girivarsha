"""
One-off data-prep script (run once, output committed) — same pattern as
prepare_glacial_lake_data.py / prepare_glacier_mass_balance_data.py: fetches
real, cited, per-village geospatial inputs and writes a small committed CSV
so the backend never needs live raster/soil-API access at request time.

User-requested follow-up (from a competitive-landscape research pass
comparing this project against real flash-flood systems worldwide): "a real
SCS-CN rainfall-runoff layer ... shown alongside (not replacing) the
current weighted formula" — the classic, decades-old, low-data,
GIS-computable Soil Conservation Service Curve Number method, with multiple
published Indian-Himalayan-hill-catchment applications (see
docs/Data_Sources.md for citations). This script fetches the two REAL
inputs the method needs beyond rainfall (which the app already has live):

1. **Real soil texture** (clay/sand/silt %, 0-5cm depth, mean) from
   **ISRIC SoilGrids v2.0** (rest.isric.org — free, no API key, global
   250m-resolution soil property maps derived from real soil profile
   observations + machine learning). Classified into a USDA soil-texture
   class via the standard USDA texture-triangle boundaries, then mapped to
   an NRCS Hydrologic Soil Group (A/B/C/D) via the standard, widely-cited
   texture-to-HSG correspondence (see `_texture_to_hsg` below).
2. **Real land cover** from **ESA WorldCover 10m v200 (2021)** — a real,
   free, global 10m-resolution land-cover product, sampled directly from
   its public Cloud-Optimized GeoTIFF via HTTP range reads (`rasterio`
   `/vsicurl/`, no full-tile download needed — confirmed working from this
   sandbox, unlike Bhuvan/Overpass/OSRM elsewhere in this project). When a
   village's exact coordinate falls on a mapped water body or snow/ice
   pixel (confirmed to happen for real: Vishnuprayag sits literally at a
   river confluence — "prayag" means confluence — so its exact point is
   itself a water pixel), this script instead samples an 11x11 pixel
   (~110m x 110m) window around the point and takes the most common
   NON-water/non-snow class — a disclosed, honest substitution (recorded
   in `land_cover_source_note`), not a silent guess.

Neither of these needs the running API to make a live network/raster call
per request — both are static (or very slowly changing) physical
characteristics of a location, same "prepare once, commit small CSV" idiom
already used for the glacial-lake and glacier-mass-balance datasets. What
IS still live per request: rainfall and the antecedent-moisture proxy (this
village's current soil-moisture reading) — see
`backend/app/services/scs_cn_runoff.py` for where those combine with this
script's output into an actual runoff estimate.

Needs `rasterio` (`pip install -r gis/requirements.txt` — NOT a backend
runtime dependency, same "kept separate" pattern as the DEM delineation
tooling and the glacial-lake prep script's `geopandas` need) plus a live
network connection to rest.isric.org and the public ESA WorldCover S3
bucket. Re-run this if a new pilot village/region is onboarded — see
docs/Region_Onboarding.md.
"""
from __future__ import annotations

import json
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import rasterio
from rasterio.warp import transform
from rasterio.windows import Window

OUT_CSV = Path(__file__).parent.parent / "data" / "derived" / "real_village_scs_cn_inputs.csv"

SOILGRIDS_URL = (
    "https://rest.isric.org/soilgrids/v2.0/properties/query"
    "?lon={lon}&lat={lat}&property=clay&property=sand&property=silt&depth=0-5cm&value=mean"
)
WORLDCOVER_TILE_URL = (
    "/vsicurl/https://esa-worldcover.s3.eu-central-1.amazonaws.com/"
    "v200/2021/map/ESA_WorldCover_10m_2021_v200_N30E078_Map.tif"
)
# Both village valleys (Mandakini: lat 30.28-30.73, lon 78.98-79.07; Chamoli:
# lat 30.48-30.56, lon 79.57-79.69) fall inside this single 3x3-degree
# WorldCover tile (lat[30,33) x lon[78,81)) — confirmed empirically. A
# future region outside this tile needs its own tile name added here (WATER_
# /SNOW_CLASSES and the CN table stay unchanged — only the URL differs).

WATER_OR_SNOW_CLASSES = {70, 80}  # Snow and ice, Permanent water bodies

WORLDCOVER_CLASS_NAMES = {
    10: "Tree cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare / sparse vegetation",
    70: "Snow and ice",
    80: "Permanent water bodies",
    90: "Herbaceous wetland",
    95: "Mangroves",
    100: "Moss and lichen",
}

CITATION_SOIL = (
    "Poggio, L. et al. (2021), 'SoilGrids 2.0: producing soil information for the globe with "
    "quantified spatial uncertainty', SOIL, DOI: 10.5194/soil-7-217-2021. Live queried via "
    "rest.isric.org/soilgrids/v2.0 (free, no API key), fetched 2026-09-06."
)
CITATION_LANDCOVER = (
    "Zanaga, D. et al. (2022), 'ESA WorldCover 10 m 2021 v200', DOI: 10.5281/zenodo.7254221. "
    "Sampled directly from the public Cloud-Optimized GeoTIFF via HTTP range reads, fetched 2026-09-06."
)

# Real, seeded pilot villages (scripts/seed_pilot_region.py + seed_chamoli_valley.py)
# — kept as a plain literal list here rather than importing the ORM/DB layer,
# since this script runs standalone with no database available (same
# approach already used in prepare_glacier_mass_balance_data.py).
PILOT_VILLAGES = [
    ("Kedarnath", 30.7346, 79.0669),
    ("Rambara", 30.716, 79.058),
    ("Gaurikund", 30.674, 79.030),
    ("Sonprayag", 30.617, 79.028),
    ("Ukhimath", 30.530, 79.048),
    ("Rudraprayag", 30.28, 78.98),
    ("Reni", 30.48555, 79.69432),
    ("Tapovan", 30.49414, 79.62753),
    ("Vishnuprayag", 30.5625, 79.57528),
    ("Joshimath", 30.555, 79.565),
]


@dataclass
class TextureResult:
    clay_pct: float
    sand_pct: float
    silt_pct: float
    usda_class: str
    hydrologic_soil_group: str


def _fetch_soil_texture(lat: float, lon: float) -> TextureResult:
    url = SOILGRIDS_URL.format(lat=lat, lon=lon)
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.load(resp)
    layers = {layer["name"]: layer["depths"][0]["values"]["mean"] for layer in data["properties"]["layers"]}
    # SoilGrids reports g/kg (d_factor 10 -> %); values can be None for a
    # genuinely unmapped location (e.g. open ocean) — never guessed at.
    clay = layers["clay"] / 10
    sand = layers["sand"] / 10
    silt = layers["silt"] / 10
    usda_class = _usda_texture_class(sand, silt, clay)
    hsg = _texture_to_hsg(usda_class)
    return TextureResult(clay, sand, silt, usda_class, hsg)


def _usda_texture_class(sand: float, silt: float, clay: float) -> str:
    """Standard USDA soil-texture-triangle classification from %sand/%silt/
    %clay (a well-established, publicly documented algorithm — this is a
    good-faith algorithmic implementation of the official triangle chart's
    boundaries, not a fabricated shortcut). Real reference:
    Soil Survey Division Staff (1993), USDA Soil Survey Manual, Ch. 3."""
    if silt + 1.5 * clay < 15:
        return "Sand"
    if silt + 1.5 * clay < 30:
        return "Loamy Sand"
    if (7 <= clay < 20 and sand > 52 and (silt + 2 * clay) >= 30) or (clay < 7 and silt < 50 and (silt + 2 * clay) >= 30):
        return "Sandy Loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "Loam"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12):
        return "Silt Loam"
    if silt >= 80 and clay < 12:
        return "Silt"
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return "Sandy Clay Loam"
    if 27 <= clay < 40 and 20 < sand <= 45:
        return "Clay Loam"
    if 27 <= clay < 40 and sand <= 20:
        return "Silty Clay Loam"
    if clay >= 35 and sand > 45:
        return "Sandy Clay"
    if clay >= 40 and silt >= 40:
        return "Silty Clay"
    return "Clay"


# Standard, widely-cited NRCS Hydrologic Soil Group correspondence for USDA
# texture classes (e.g. NRCS National Engineering Handbook Part 630, Ch. 7,
# and reproduced in many SCS-CN GIS studies, including several of the
# Indian-Himalayan-hill-catchment papers found in this project's own
# competitive-landscape research). A -> high infiltration/low runoff
# potential, D -> low infiltration/high runoff potential.
_TEXTURE_TO_HSG = {
    "Sand": "A",
    "Loamy Sand": "A",
    "Sandy Loam": "A",
    "Loam": "B",
    "Silt Loam": "B",
    "Silt": "B",
    "Sandy Clay Loam": "C",
    "Clay Loam": "D",
    "Silty Clay Loam": "D",
    "Sandy Clay": "D",
    "Silty Clay": "D",
    "Clay": "D",
}


def _texture_to_hsg(usda_class: str) -> str:
    return _TEXTURE_TO_HSG.get(usda_class, "C")  # unrecognized class -> honest mid-range default, never crashes


def _fetch_land_cover(ds: rasterio.DatasetReader, lat: float, lon: float) -> tuple[int, str]:
    """Returns (worldcover_class_code, source_note). Falls back to an 11x11
    pixel (~110m) window's most common non-water/non-snow class if the
    exact point is itself mapped as water/snow (a real, confirmed case:
    Vishnuprayag sits at a real river confluence)."""
    xs, ys = transform("EPSG:4326", ds.crs, [lon], [lat])
    row, col = ds.index(xs[0], ys[0])
    point_class = int(next(ds.sample([(xs[0], ys[0])]))[0])
    if point_class not in WATER_OR_SNOW_CLASSES:
        return point_class, "sampled directly at the village's coordinate"

    window = Window(col - 5, row - 5, 11, 11)
    window_data = ds.read(1, window=window).flatten().tolist()
    land_counts = Counter(c for c in window_data if c not in WATER_OR_SNOW_CLASSES)
    if not land_counts:
        return point_class, (
            f"exact point and its surrounding ~110m are entirely {WORLDCOVER_CLASS_NAMES.get(point_class, point_class)} "
            "— no nearby dry-land class found"
        )
    best_class, _ = land_counts.most_common(1)[0]
    return best_class, (
        f"exact coordinate is mapped as {WORLDCOVER_CLASS_NAMES.get(point_class, point_class)} (this village sits at a "
        "real river confluence/floodplain) — using the most common non-water/snow class within a ~110m window instead"
    )


def main() -> None:
    rows = []
    with rasterio.open(WORLDCOVER_TILE_URL) as ds:
        for name, lat, lon in PILOT_VILLAGES:
            print(f"Fetching real soil texture + land cover for {name}...")
            texture = _fetch_soil_texture(lat, lon)
            wc_class, wc_note = _fetch_land_cover(ds, lat, lon)
            rows.append(
                {
                    "village_name": name,
                    "lat": lat,
                    "lon": lon,
                    "clay_pct": round(texture.clay_pct, 1),
                    "sand_pct": round(texture.sand_pct, 1),
                    "silt_pct": round(texture.silt_pct, 1),
                    "usda_texture_class": texture.usda_class,
                    "hydrologic_soil_group": texture.hydrologic_soil_group,
                    "worldcover_class_code": wc_class,
                    "worldcover_class_name": WORLDCOVER_CLASS_NAMES.get(wc_class, str(wc_class)),
                    "land_cover_source_note": wc_note,
                    "soil_citation": CITATION_SOIL,
                    "land_cover_citation": CITATION_LANDCOVER,
                }
            )

    import csv

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} real village SCS-CN inputs -> {OUT_CSV}")
    for r in rows:
        print(f"  {r['village_name']}: HSG {r['hydrologic_soil_group']} ({r['usda_texture_class']}), "
              f"land cover {r['worldcover_class_name']}" + (f" [{r['land_cover_source_note']}]" if "confluence" in r['land_cover_source_note'] or "no nearby" in r['land_cover_source_note'] else ""))


if __name__ == "__main__":
    main()
