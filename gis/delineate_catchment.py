"""
Real DEM-based micro-catchment delineation (problem-statement item 7 /
docs/GIS_Methodology.md).

Two separate, honestly-labelled pieces:

1. `download_srtm_dem()` — fetches a real SRTM 30m tile for the pilot region
   from OpenTopography's public REST API. **This step could not be verified
   in the sandbox this project was built in** — outbound HTTPS to
   opentopography.org is blocked by that sandbox's egress policy
   (confirmed: `urlopen(...)` raises "Tunnel connection failed: 403
   Forbidden"). It needs an OpenTopography API key
   (https://opentopography.org/blog/introducing-api-keys) set as
   `OPENTOPOGRAPHY_API_KEY`. Run it from a machine with normal internet
   access.

2. `delineate_catchment()` — the actual flow-direction / flow-accumulation /
   watershed-delineation algorithm (D8 flow model via pysheds), which takes
   any DEM GeoTIFF and a pour point and returns a real catchment polygon.
   This part IS verified in this sandbox: see
   `tests/gis/test_delineation.py`, which runs it end-to-end against a
   small synthetic DEM (a numpy-generated valley, not a real place) and
   checks the output is a sane, non-degenerate polygon containing the pour
   point. That test does not prove the *pilot region's* catchment shape —
   only that the delineation code itself is correct. Producing the real
   Mandakini-valley polygon still requires step 1 to run somewhere with
   network access.

Usage (once you have a DEM, real or downloaded):
    python gis/delineate_catchment.py \
        --dem path/to/dem.tif \
        --pour-lon 78.98 --pour-lat 30.28 \
        --out data/derived/mandakini_catchment.geojson
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np


def download_srtm_dem(
    south: float,
    north: float,
    west: float,
    east: float,
    out_path: str | Path,
    api_key: str | None = None,
) -> Path:
    """Download a real SRTM GL1 (30m) DEM tile covering the given bounding box
    from OpenTopography's public Global DEM API. Requires network access and
    an API key — see module docstring. Raises RuntimeError with a clear
    message rather than silently producing a fake/empty file if it fails."""
    import urllib.parse
    import urllib.request

    api_key = api_key or os.environ.get("OPENTOPOGRAPHY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENTOPOGRAPHY_API_KEY is not set. Get a free key at "
            "https://opentopography.org/blog/introducing-api-keys and set it "
            "as an environment variable before running this."
        )
    params = {
        "demtype": "SRTMGL1",
        "south": south,
        "north": north,
        "west": west,
        "east": east,
        "outputFormat": "GTiff",
        "API_Key": api_key,
    }
    url = "https://portal.opentopography.org/API/globaldem?" + urllib.parse.urlencode(params)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, out_path)
    except Exception as exc:  # noqa: BLE001 — we want to surface network failures plainly
        raise RuntimeError(
            f"DEM download failed ({exc!r}). This is expected if you're running in a "
            "network-restricted environment — run this script from a machine with normal "
            "internet access instead."
        ) from exc
    return out_path


def delineate_catchment(dem_path: str | Path, pour_lon: float, pour_lat: float) -> dict:
    """Run D8 flow-direction + flow-accumulation + watershed delineation on a
    real DEM GeoTIFF, using pysheds. Returns a GeoJSON-style dict (single
    Polygon feature) in the DEM's CRS. This is the part that's actually
    tested in this sandbox (tests/gis/test_delineation.py) — it has no
    dependency on where the DEM came from."""
    from pysheds.grid import Grid

    grid = Grid.from_raster(str(dem_path))
    dem = grid.read_raster(str(dem_path))

    # Standard pysheds D8 pipeline: fill pits/depressions, resolve flats,
    # compute flow direction, then flow accumulation.
    pit_filled = grid.fill_pits(dem)
    flooded = grid.fill_depressions(pit_filled)
    inflated = grid.resolve_flats(flooded)
    fdir = grid.flowdir(inflated)
    acc = grid.accumulation(fdir)

    # Snap the requested pour point onto the nearest high-accumulation cell
    # (a real stream cell) rather than trusting the raw coordinate, which is
    # standard practice — pour points rarely land exactly on the digitised
    # stream line.
    x, y = grid.snap_to_mask(acc > np.percentile(acc[acc > 0], 95) if (acc > 0).any() else acc > 0, (pour_lon, pour_lat))

    catchment = grid.catchment(x=x, y=y, fdir=fdir, xytype="coordinate")
    grid.clip_to(catchment)
    shapes = grid.polygonize()

    polygons = [
        {"type": "Feature", "geometry": geom, "properties": {"value": value}}
        for geom, value in shapes
        if value == 1  # pysheds/rasterio polygonize marks catchment cells as 1
    ]
    if not polygons:
        raise RuntimeError(
            "Delineation produced no catchment polygon — check that the pour point "
            "lies within the DEM extent and on/near the real stream network."
        )
    return {
        "type": "FeatureCollection",
        "features": polygons,
        "properties": {"pour_point": {"lon": pour_lon, "lat": pour_lat}},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem", required=True, help="Path to a DEM GeoTIFF")
    parser.add_argument("--pour-lon", type=float, required=True)
    parser.add_argument("--pour-lat", type=float, required=True)
    parser.add_argument("--out", required=True, help="Output GeoJSON path")
    args = parser.parse_args()

    result = delineate_catchment(args.dem, args.pour_lon, args.pour_lat)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(f"Wrote {out_path} ({len(result['features'])} polygon feature(s))")


if __name__ == "__main__":
    main()
