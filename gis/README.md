# gis/

DEM/terrain processing and micro-catchment delineation. See `docs/GIS_Methodology.md` for full status and honesty notes.

- `delineate_catchment.py` — real D8 flow-direction/accumulation/watershed delineation (pysheds), tested against a synthetic DEM in `tests/gis/test_delineation.py`. Also has a real SRTM downloader (`download_srtm_dem`) that needs network access and an OpenTopography API key this build sandbox doesn't have.
- `load_catchment_polygon.py` — loads a delineated polygon GeoJSON into the `micro_catchments.geom` column.
- `requirements.txt` — the geospatial libraries these two scripts need (`pip install -r gis/requirements.txt`). Kept separate from `backend/requirements.txt` since the running API never imports them.

Large raster files (`*.tif`) are gitignored — see `.gitignore` — regenerate them via `delineate_catchment.py` rather than committing them. Output GeoJSON polygons land in `data/derived/`.
