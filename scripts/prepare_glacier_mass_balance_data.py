"""
One-off data-prep script (run once, output committed) — same pattern as
prepare_glacial_lake_data.py: downloads a real, cited, global dataset,
filters it to the pilot region, and writes a small committed CSV so the
backend never needs the ~50MB global archive or network access at runtime.

Source: Dussaillant, I. et al. (2025), "Annual mass changes for each
glacier in the world from 1976 to 2023" (Earth System Science Data, in
review/preprint at time of writing:
https://essd.copernicus.org/preprints/essd-2024-323/), published via the
World Glacier Monitoring Service (WGMS) as the "Annual Mass-Change
Estimates" (AMCE) product, an update/extension of the widely-cited
Hugonnet et al. (2021) "Accelerated global glacier mass loss in the early
twenty-first century" (Nature) methodology. Data downloaded from
https://wgms.ch/downloads/wgms-amce-2026-02-10.zip (version 2026-02-10,
fetched 2026-09-06) — see docs/Data_Sources.md for the full citation.

This is a REAL, per-glacier, geolocated (RGI 6.0 ID + centroid lat/lon)
annual mass-balance time series (1957-2025, in m water equivalent/year),
not a raster/GeoTIFF product — no geopandas/rasterio needed, just stdlib
csv/zipfile. This directly supersedes the earlier attempt (see git history
/ Build_Status.md) to use Hugonnet et al. 2021's own data portal, which
dead-ended at a SEDOO/Theia landing page with no visible download link —
WGMS's own re-published, updated version of the same underlying methodology
turned out to be the actually-downloadable real source.

RGI regions used: "ASW" (region 14, South Asia West) and "ASE" (region 15,
South Asia East) — the two RGI first-order regions whose glaciers actually
fall in and around Uttarakhand's Garhwal Himalaya (confirmed empirically:
region 14 and 15 glacier centroids both appear within 100km of this
project's seeded pilot villages; the adjacent "ASC"/"ASN" region files were
checked and contain none).

Filtered to glaciers within MAX_RELEVANT_DISTANCE_KM (matching
glacial_lake_proximity.py's own cutoff, for consistency) of ANY seeded
pilot village (Mandakini valley + Chamoli valley) — not the whole of RGI
14+15 (41,117 glaciers globally), which would bloat the repo with
irrelevant Karakoram/Nepal/Bhutan glaciers this pilot has no reason to
carry. Re-run this script (with a fresh village list) if a future region
onboarding (docs/Region_Onboarding.md) adds pilot villages outside this
radius.
"""
from __future__ import annotations

import csv
import io
import math
import urllib.request
import zipfile
from pathlib import Path

DOWNLOAD_URL = "https://wgms.ch/downloads/wgms-amce-2026-02-10.zip"
RAW_ZIP_PATH = Path(__file__).parent.parent / "data" / "raw" / "glacier_mass_balance" / "wgms-amce-2026-02-10.zip"
OUT_CSV = Path(__file__).parent.parent / "data" / "derived" / "real_himalaya_glacier_mass_balance.csv"

REGION_FILES = {
    "ASW": "South Asia West (RGI region 14)",
    "ASE": "South Asia East (RGI region 15)",
}

MAX_RELEVANT_DISTANCE_KM = 100.0

# Real, seeded pilot villages (scripts/seed_pilot_region.py + seed_chamoli_valley.py)
# — kept as a plain literal list here rather than importing the ORM/DB layer,
# since this script runs standalone with no database available.
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

RECENT_YEARS = [str(y) for y in range(2021, 2026)]  # 2021-2025, most recent 5 years with data
PRIOR_YEARS = [str(y) for y in range(2016, 2021)]  # 2016-2020, the preceding 5-year window

CITATION = (
    "Dussaillant, I. et al. (2025), 'Annual mass changes for each glacier in the "
    "world from 1976 to 2023', Earth System Science Data (preprint: "
    "https://essd.copernicus.org/preprints/essd-2024-323/), published via the World "
    "Glacier Monitoring Service (WGMS) Annual Mass-Change Estimates product — an "
    "update of the Hugonnet et al. (2021, Nature) global glacier elevation-change "
    "methodology. Downloaded from https://wgms.ch/downloads/wgms-amce-2026-02-10.zip "
    "(version 2026-02-10), fetched 2026-09-06."
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _ensure_raw_zip() -> Path:
    if RAW_ZIP_PATH.exists():
        return RAW_ZIP_PATH
    print(f"Downloading {DOWNLOAD_URL} ...")
    RAW_ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(DOWNLOAD_URL, RAW_ZIP_PATH)
    return RAW_ZIP_PATH


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def main() -> None:
    zip_path = _ensure_raw_zip()
    rows_out: list[dict] = []

    with zipfile.ZipFile(zip_path) as zf:
        for region_code, region_name in REGION_FILES.items():
            with zf.open(f"glacier/{region_code}_metadata.csv") as f:
                meta_reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
                meta_by_id = {row["outline_id"]: row for row in meta_reader}

            with zf.open(f"glacier/{region_code}_mwe.csv") as f:
                mwe_reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
                for row in mwe_reader:
                    rgi_id = row["outline_id"]
                    meta = meta_by_id.get(rgi_id)
                    if meta is None:
                        continue  # a mass-balance row with no matching metadata row is skipped, never guessed at
                    lat, lon = float(meta["latitude"]), float(meta["longitude"])

                    nearest_km = min(
                        haversine_km(lat, lon, vlat, vlon) for _, vlat, vlon in PILOT_VILLAGES
                    )
                    if nearest_km > MAX_RELEVANT_DISTANCE_KM:
                        continue

                    recent_vals = [float(row[y]) for y in RECENT_YEARS if row.get(y)]
                    prior_vals = [float(row[y]) for y in PRIOR_YEARS if row.get(y)]
                    recent_mean = _mean(recent_vals)
                    prior_mean = _mean(prior_vals)
                    trend = (
                        round(recent_mean - prior_mean, 4)
                        if recent_mean is not None and prior_mean is not None
                        else None
                    )

                    rows_out.append(
                        {
                            "glacier_id": rgi_id,
                            "lat": round(lat, 6),
                            "lon": round(lon, 6),
                            "area_km2": meta.get("area_km2", ""),
                            "region": region_name,
                            "recent_mean_mwe_per_yr": recent_mean,
                            "recent_years": f"{RECENT_YEARS[0]}-{RECENT_YEARS[-1]}",
                            "prior_mean_mwe_per_yr": prior_mean,
                            "prior_years": f"{PRIOR_YEARS[0]}-{PRIOR_YEARS[-1]}",
                            "mass_balance_trend_mwe_per_yr": trend,
                            "source_dataset": "wgms_amce_2026_02_10",
                            "dataset_citation": CITATION,
                        }
                    )

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows_out[0].keys()) if rows_out else []
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"Wrote {len(rows_out)} real glaciers (within {MAX_RELEVANT_DISTANCE_KM:.0f}km of the pilot region) -> {OUT_CSV}")
    by_region: dict[str, int] = {}
    for r in rows_out:
        by_region[r["region"]] = by_region.get(r["region"], 0) + 1
    for region, count in by_region.items():
        print(f"  {region}: {count}")
    missing_recent = sum(1 for r in rows_out if r["recent_mean_mwe_per_yr"] is None)
    if missing_recent:
        print(f"  ({missing_recent} glaciers had no {RECENT_YEARS[0]}-{RECENT_YEARS[-1]} data — recent_mean_mwe_per_yr left blank for those, never guessed at)")


if __name__ == "__main__":
    main()
