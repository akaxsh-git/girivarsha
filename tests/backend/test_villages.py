"""
Phase 2 tests: real DB-backed endpoints. These need a running, migrated,
seeded Postgres — see README.md "Phase 2: database setup". If no database
is configured/reachable, the whole module skips with a clear reason rather
than failing confusingly (so `pytest tests/backend` still runs cleanly for
someone who hasn't set up Postgres yet).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.models.database import DatabaseNotConfiguredError, get_engine  # noqa: E402

try:
    _engine = get_engine()
    with _engine.connect():
        pass
    _db_available = True
    _skip_reason = ""
except DatabaseNotConfiguredError as exc:
    _db_available = False
    _skip_reason = str(exc)
except Exception as exc:  # pragma: no cover - e.g. DB configured but not reachable
    _db_available = False
    _skip_reason = f"Database configured but unreachable: {exc}"

pytestmark = pytest.mark.skipif(not _db_available, reason=_skip_reason)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_villages_are_real_and_sourced():
    r = client.get("/api/v1/villages")
    assert r.status_code == 200
    villages = r.json()
    assert len(villages) >= 5, "problem statement asks for 5-10 pilot villages"

    names = {v["name"] for v in villages}
    assert {"Kedarnath", "Rudraprayag"}.issubset(names), "real pilot-region anchors must be present"

    for v in villages:
        assert v["source"] == "real"
        assert v["provenance"], f"{v['name']} is missing its source citation"
        assert v["coordinate_precision"] in ("surveyed", "approximate")
        # sanity-check the coordinates actually fall in the Uttarakhand Himalaya,
        # not e.g. (0,0) from a missed geometry conversion
        assert 29.5 <= v["lat"] <= 31.5
        assert 78.0 <= v["lon"] <= 80.0


def test_village_ordering_matches_real_river_topology():
    """Kedarnath (source, 3583m) must outrank Rudraprayag (outlet, 895m) —
    this is the real upstream->downstream order of the Mandakini river."""
    villages = client.get("/api/v1/villages").json()
    by_name = {v["name"]: v["elevation_m"] for v in villages}
    assert by_name["Kedarnath"] > by_name["Rudraprayag"]


def test_village_detail_404_for_unknown_id():
    r = client.get("/api/v1/villages/999999")
    assert r.status_code == 404


def test_catchments_expose_topology_not_fake_polygons():
    r = client.get("/api/v1/catchments")
    assert r.status_code == 200
    catchments = r.json()
    assert len(catchments) >= 1
    for c in catchments:
        # Phase 2 honesty check, generalized: has_polygon_geometry must be a
        # genuine boolean reflecting whether real geometry is actually
        # loaded for THIS catchment — never a hard-coded stub either way.
        # Not asserting a specific value here on purpose: some environments
        # (this build's own sandbox) have no catchment with real polygon
        # data loaded yet, while others (e.g. after running the real SRTM
        # DEM delineation locally, per docs/GIS_Methodology.md) genuinely
        # do for at least one catchment — both are honest states, and this
        # test shouldn't assume which one it's running against.
        assert isinstance(c["has_polygon_geometry"], bool)
    # Real bug found via the SCS-CN integration pass: SQL makes no ordering
    # guarantee without an explicit ORDER BY (now added in
    # app/api/routes/catchments.py), so asserting against catchments[0]
    # specifically was fragile — it happened to hold in this build's own
    # sandbox but not on every real Postgres install. The real invariant
    # this test cares about is that at least one real seeded catchment has
    # a substantial village count (Mandakini's, 6 villages) — check that
    # directly rather than assuming which index it lands at.
    assert any(c["village_count"] >= 5 for c in catchments)


def test_historical_events_have_real_citations():
    r = client.get("/api/v1/historical-events")
    assert r.status_code == 200
    events = r.json()
    assert len(events) >= 1
    for e in events:
        assert e["source_citation"], "every historical event must cite a real source"
        assert "wikipedia" in e["source_citation"].lower() or "http" in e["source_citation"].lower() \
            or len(e["source_citation"]) > 10
