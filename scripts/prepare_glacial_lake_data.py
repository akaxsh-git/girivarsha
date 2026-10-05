"""
One-off data-prep script (run once, output committed) — converts the raw
glacial lake inventory shapefile into a lightweight CSV the backend can
load without a geopandas/shapely runtime dependency.

Source: Zhang, G. et al. (2023), "Underestimated mass loss from
lake-terminating glaciers in the greater Himalaya", Nature Geoscience,
DOI: 10.1038/s41561-023-01150-1. Data: figshare 21708590, 2020 inventory
(the most recent of the dataset's 5 snapshots: 1990/2000/2010/2015/2020),
9,208 real, individually-mapped glacial lakes across the Hindu Kush-
Himalaya, downloaded 2026-09-04. See docs/Data_Sources.md.

This script needs geopandas (NOT a backend runtime dependency — see
gis/requirements.txt, same "kept separate" pattern as the DEM delineation
tooling). It is not re-run automatically; its output
(data/real_himalaya_glacial_lakes.csv) is committed and is what
backend/app/services/glacial_lake_proximity.py actually loads.

Filtered to the 3 Himalaya regions covering India's Himalayan hill states
(Western/Central/Eastern Himalaya, per the source dataset's own region
classification) — not the dataset's other regions (Hindu Kush, Karakoram,
Nyainqentanglha, Hengduan Shan), which fall outside India's Himalayan arc.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd

RAW_SHAPEFILE = (
    Path(__file__).parent.parent
    / "data"
    / "raw"
    / "glacial_lake_inventory"
    / "GlacialLake_20220726"
    / "GlacialLake_2020.shp"
)
OUT_CSV = Path(__file__).parent.parent / "data" / "derived" / "real_himalaya_glacial_lakes.csv"

INDIA_HIMALAYA_REGIONS = {"Western Himalaya", "Central Himalaya", "Eastern Himalaya"}

CITATION = (
    "Zhang, G. et al. (2023), 'Underestimated mass loss from lake-terminating "
    "glaciers in the greater Himalaya', Nature Geoscience, DOI: "
    "10.1038/s41561-023-01150-1. Data: figshare 21708590 (2020 inventory), "
    "fetched 2026-09-04."
)


def main() -> None:
    gdf = gpd.read_file(RAW_SHAPEFILE)
    sub = gdf[gdf["Region"].isin(INDIA_HIMALAYA_REGIONS)].copy()

    # Real centroid computation needs a projected (metric) CRS — the source
    # file's own Albers Equal Area projection — then reproject to WGS84 for
    # lat/lon storage. Never compute a centroid directly in a geographic CRS
    # (that silently distorts the result).
    centroids_projected = sub.geometry.centroid
    centroids_wgs84 = gpd.GeoSeries(centroids_projected, crs=sub.crs).to_crs(epsg=4326)

    import pandas as pd

    out = pd.DataFrame(
        {
            "lat": centroids_wgs84.y.round(6),
            "lon": centroids_wgs84.x.round(6),
            "area_km2": sub["Area"].round(4),
            "elevation_m": sub["Elevation"],
            "lake_type": sub["Type"],
            "region": sub["Region"],
            "source_dataset": "himalaya_glacial_lake_inventory_2020",
            "dataset_citation": CITATION,
        }
    )
    out = out.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    out.insert(0, "lake_id", [f"lake-{i:04d}" for i in range(len(out))])

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False)
    print(f"Wrote {len(out)} real glacial lakes (India Himalayan arc) -> {OUT_CSV}")
    print(out["region"].value_counts().to_string())


if __name__ == "__main__":
    main()
