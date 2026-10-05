# GIS Methodology

## Status as of Phase 3

**Topology: real, since Phase 2.** District → Watershed → Micro-catchment → upstream/downstream links exist in the database (`MicroCatchment.upstream_catchment_id`), derived from documented river-order research for the Mandakini valley (see `docs/Data_Sources.md`). This is what lets risk propagate along a real flow path rather than being assigned per village in isolation (problem-statement item 7) — and it doesn't require a DEM.

**Polygon boundaries: real, verified end-to-end (2026-09-04) — outside this build sandbox, on a normal internet connection.** Concretely:

- `gis/delineate_catchment.py` implements the actual delineation algorithm — D8 flow direction → flow accumulation → watershed delineation → polygonize, via [pysheds](https://github.com/mdbartos/pysheds), against any DEM GeoTIFF and a pour point. **Tested twice**: `tests/gis/test_delineation.py` runs it end-to-end on a synthetic DEM (a numpy-generated valley) and passes, and it was subsequently run against a *real* SRTM tile for the pilot region and produced a real polygon (see below).
- The same file's `download_srtm_dem()` fetches a real SRTM GL1 (30m) tile for a bounding box from OpenTopography's public API. **This step could not be run inside this project's build sandbox** — outbound HTTPS to `opentopography.org` is blocked by that environment's egress policy (confirmed error: `Tunnel connection failed: 403 Forbidden`) — but it does not need to be: it was run successfully from a normal machine with a free OpenTopography API key, downloading a real 3.2MB SRTM tile covering the Mandakini valley.
- `gis/load_catchment_polygon.py` loads a produced polygon GeoJSON into `MicroCatchment.geom`, tagging it `source=derived` with a provenance string citing the DEM source and processing date. **Run successfully against the real polygon above** — `GET /api/v1/catchments` now reports `has_polygon_geometry: true` for the Mandakini Valley catchment, with provenance: *"Polygon delineated 2026-09-04 via D8 flow accumulation + watershed delineation (gis/delineate_catchment.py, pysheds) from SRTM GL1 30m, via OpenTopography, downloaded 2026-09-04. Pour point: {lon: 78.98, lat: 30.28}."*

This closes the one gap in the GIS pipeline that this project's own build sandbox couldn't verify itself — the delineation *code* was always real and tested; what was missing was purely the outbound network access to fetch elevation data, and that turned out to be a sandbox limitation, not a limitation of the approach or the code.

**To reproduce this on your own machine:**
```bash
pip install -r gis/requirements.txt
export OPENTOPOGRAPHY_API_KEY=...   # free key: https://opentopography.org/blog/introducing-api-keys
python -c "from gis.delineate_catchment import download_srtm_dem; download_srtm_dem(south=30.25, north=30.75, west=78.9, east=79.15, out_path='data/derived/mandakini_dem.tif')"
python gis/delineate_catchment.py --dem data/derived/mandakini_dem.tif --pour-lon 78.98 --pour-lat 30.28 --out data/derived/mandakini_catchment.geojson
python gis/load_catchment_polygon.py --geojson data/derived/mandakini_catchment.geojson --catchment-name "Mandakini Valley (Kedarnath -> Rudraprayag)" --dem-source "SRTM GL1 30m, via OpenTopography, downloaded $(date +%F)"
```
After that, `GET /api/v1/catchments` will report `has_polygon_geometry: true` for real, and the frontend catchment panel picks that up automatically (`frontend/src/components/CatchmentPanel.tsx`) — no code changes needed on either side.

## Planned, not yet built (later phases)

- Slope, aspect, drainage density, distance-to-stream, topographic wetness index — derivable from the same DEM once downloaded, feeding the Phase 4/5 risk engine as terrain features.
- Historical hazard layer: ISRO Landslide Atlas / NRSC or another authoritative dataset where accessible, producing historical event density, susceptibility, and distance-to-event features.
- Storage of derived rasters/vectors: PostgreSQL + PostGIS, per `docs/Architecture.md`.

## Why this is sequenced before the risk engine

A village downstream of a rapidly-changing upstream catchment should get a different risk signal than one outside that flow path, even under identical local rainfall. The topology needed for that (District → Watershed → Micro-catchment → Stream → Village) is real as of Phase 2; the risk engine (Phase 4) can start consuming it today via `MicroCatchment.upstream_catchment_id` without waiting on polygon geometry, which only sharpens boundaries — it doesn't gate the topology-based logic.
