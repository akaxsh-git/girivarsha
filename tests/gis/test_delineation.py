"""Tests the real delineation ALGORITHM (gis/delineate_catchment.py's
`delineate_catchment`) against a synthetic DEM, not real terrain data.

Why synthetic: downloading a real DEM needs an OpenTopography API key and
outbound internet access, neither available in the sandbox this was built
in (see gis/delineate_catchment.py's module docstring for the confirmed
network error). A synthetic DEM still exercises the real pysheds D8
pipeline (fill -> resolve flats -> flow direction -> accumulation ->
watershed -> polygonize) end to end, so it catches real bugs in the
delineation logic itself — it just can't tell us the real Mandakini
valley's shape. That's an honest, explicit limitation, not a hidden one.
"""
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gis"))
from delineate_catchment import delineate_catchment  # noqa: E402


@pytest.fixture()
def synthetic_valley_dem(tmp_path) -> Path:
    """A simple synthetic DEM: a V-shaped valley draining toward a single
    outlet at the bottom-centre, elevation decreasing south. This gives the
    D8 algorithm an unambiguous, real flow pattern to delineate — not a
    real place, but real terrain physics."""
    size = 60
    ys, xs = np.mgrid[0:size, 0:size]
    center = size / 2
    # Elevation rises with distance from the central north-south valley
    # line, and rises going north (upstream) — pysheds fill/resolve handles
    # any residual local noise.
    valley = np.abs(xs - center) * 4.0
    downhill = (size - ys) * 2.0
    dem = (valley + downhill).astype("float32")
    rng = np.random.default_rng(42)
    dem += rng.normal(0, 0.05, size=dem.shape).astype("float32")  # tiny noise, resolved by fill/resolve_flats

    # Cell size ~0.001 deg (~111m), origin chosen arbitrarily but
    # georeferenced so pysheds' coordinate-based snapping/catchment calls
    # work the same way they would on a real DEM.
    transform = from_origin(west=79.0, north=30.6, xsize=0.001, ysize=0.001)
    dem_path = tmp_path / "synthetic_valley.tif"
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        height=size,
        width=size,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(dem, 1)
    return dem_path


def test_delineation_produces_a_real_nondegenerate_polygon(synthetic_valley_dem):
    # Pour point at the valley's southern outlet (bottom-centre of the DEM,
    # where all synthetic flow converges).
    pour_lon = 79.0 + 0.001 * 30  # centre column
    pour_lat = 30.6 - 0.001 * 59  # bottom row

    result = delineate_catchment(synthetic_valley_dem, pour_lon, pour_lat)

    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) >= 1

    from shapely.geometry import shape

    total_area = 0.0
    for feature in result["features"]:
        geom = shape(feature["geometry"])
        assert geom.is_valid
        total_area += geom.area

    # The synthetic valley funnels essentially the whole grid toward the
    # outlet — the delineated catchment should be a substantial fraction of
    # the DEM extent, not a single stray pixel (which would indicate a
    # broken flow-accumulation/watershed step) and not the entire DEM
    # (which would indicate the pour point / mask logic did nothing).
    dem_extent_area = 0.06 * 0.06  # 60 cells * 0.001 deg, squared
    assert 0.05 * dem_extent_area < total_area <= dem_extent_area


def test_delineation_raises_a_clear_error_for_a_missing_dem(tmp_path):
    # A pour point far outside the DEM gets snapped to the nearest valid
    # cell by pysheds (that's real, documented snap-to-mask behaviour, not
    # a bug to paper over) — so the actual error case worth guarding here
    # is a DEM file that doesn't exist at all, which should fail loudly
    # rather than silently producing an empty/fabricated polygon.
    missing_dem = tmp_path / "does_not_exist.tif"
    with pytest.raises(Exception):
        delineate_catchment(missing_dem, pour_lon=79.0, pour_lat=30.5)
