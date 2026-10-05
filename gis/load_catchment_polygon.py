"""
Loads a real delineated catchment polygon (produced by
delineate_catchment.py) into the MicroCatchment.geom column.

This is the last mile of the Phase 3 GIS pipeline: DEM -> delineation ->
GeoJSON -> database. It is real, runnable code — it has not been run
end-to-end against a real DEM in this build sandbox because step 1 (DEM
download) is network-blocked here (see delineate_catchment.py's docstring).
Running it against a real polygon flips `has_polygon_geometry` to true on
GET /catchments, which the API and frontend already handle honestly either
way (see backend/app/api/routes/catchments.py, frontend CatchmentPanel.tsx).

Usage:
    python gis/load_catchment_polygon.py \
        --geojson data/derived/mandakini_catchment.geojson \
        --catchment-name "Mandakini Valley (Kedarnath -> Rudraprayag)" \
        --dem-source "SRTM GL1 30m, via OpenTopography"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(_BACKEND_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geojson", required=True, help="Output of delineate_catchment.py")
    parser.add_argument("--catchment-name", required=True, help="Must match an existing micro_catchments.name")
    parser.add_argument("--dem-source", required=True, help="Cited in the provenance field, e.g. 'SRTM GL1 30m, via OpenTopography, downloaded 2026-XX-XX'")
    args = parser.parse_args()

    geojson_path = Path(args.geojson)
    if not geojson_path.exists():
        raise SystemExit(f"No such file: {geojson_path}")

    from geoalchemy2.shape import from_shape
    from shapely.geometry import shape
    from shapely.ops import unary_union
    from sqlalchemy import select

    from app.models.database import session_scope
    from app.models.orm import DataSource, MicroCatchment

    data = json.loads(geojson_path.read_text())
    geoms = [shape(f["geometry"]) for f in data["features"]]
    if not geoms:
        raise SystemExit(f"{geojson_path} has no polygon features — nothing to load.")
    merged = unary_union(geoms)
    if merged.geom_type == "MultiPolygon":
        # Keep the largest ring only — small artifact polygons from the
        # polygonize step aren't part of the real catchment boundary.
        merged = max(merged.geoms, key=lambda g: g.area)

    with session_scope() as session:
        catchment = session.scalar(select(MicroCatchment).where(MicroCatchment.name == args.catchment_name))
        if catchment is None:
            raise SystemExit(
                f"No micro_catchments row named {args.catchment_name!r}. "
                "Run scripts/seed_pilot_region.py first, or check the name."
            )
        catchment.geom = from_shape(merged, srid=4326)
        catchment.source = DataSource.DERIVED
        catchment.provenance = (
            f"Polygon delineated {datetime.now(timezone.utc).date().isoformat()} via D8 flow "
            f"accumulation + watershed delineation (gis/delineate_catchment.py, pysheds) "
            f"from {args.dem_source}. Pour point: {data.get('properties', {}).get('pour_point')}."
        )
        session.commit()
        print(f"Updated micro_catchments.id={catchment.id} ({catchment.name}) with a real polygon.")


if __name__ == "__main__":
    main()
