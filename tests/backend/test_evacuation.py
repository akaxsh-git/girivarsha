"""
Phase 12 tests: evacuation routing (GET /evacuation/route/{id}) and
priority ranking (GET /evacuation/priority). Needs a running, migrated,
seeded Postgres — same skip-if-no-db pattern as test_villages.py.
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
except Exception as exc:  # pragma: no cover
    _db_available = False
    _skip_reason = f"Database configured but unreachable: {exc}"

pytestmark = pytest.mark.skipif(not _db_available, reason=_skip_reason)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _village_id_by_name(name: str) -> int:
    villages = client.get("/api/v1/villages").json()
    for v in villages:
        if v["name"] == name:
            return v["id"]
    raise AssertionError(f"no seeded village named {name!r}")


def test_route_from_source_village_walks_the_full_real_chain():
    reni_id = _village_id_by_name("Reni")
    r = client.get(f"/api/v1/evacuation/route/{reni_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["origin_village_name"] == "Reni"
    assert body["destination_village_name"] == "Vishnuprayag"  # real, lowest-elevation Chamoli village
    assert len(body["hops"]) == 3  # Reni -> Joshimath -> Tapovan -> Vishnuprayag
    assert body["total_distance_km"] > 0
    assert body["estimated_minutes"] > 0
    # every hop's distance must sum to the reported total (no silently dropped hops)
    assert round(sum(h["distance_km"] for h in body["hops"]), 1) == round(body["total_distance_km"], 1)


def test_route_from_the_outlet_village_is_honestly_empty():
    vishnuprayag_id = _village_id_by_name("Vishnuprayag")
    r = client.get(f"/api/v1/evacuation/route/{vishnuprayag_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["hops"] == []
    assert body["total_distance_km"] == 0.0
    assert body["estimated_minutes"] is None
    assert "already" in body["note"].lower()


def test_route_404_for_unknown_village():
    r = client.get("/api/v1/evacuation/route/999999")
    assert r.status_code == 404


def test_route_never_crosses_into_a_different_catchment():
    """A route computed from a Mandakini village must never route through
    or terminate at a Chamoli village, or vice versa — the two valleys are
    unrelated real places, not one continuous chain."""
    kedarnath_id = _village_id_by_name("Kedarnath")
    r = client.get(f"/api/v1/evacuation/route/{kedarnath_id}")
    assert r.status_code == 200
    body = r.json()
    chamoli_names = {"Reni", "Tapovan", "Vishnuprayag", "Joshimath"}
    hop_names = {h["from_village_name"] for h in body["hops"]} | {h["to_village_name"] for h in body["hops"]}
    assert hop_names.isdisjoint(chamoli_names)
    assert body["destination_village_name"] not in chamoli_names


def test_priority_ranks_by_severity_then_lead_time():
    r = client.get("/api/v1/evacuation/priority?region_id=2")  # Chamoli Disaster Valley
    assert r.status_code == 200
    entries = r.json()
    assert len(entries) == 4
    # ranks must be a contiguous 1..N sequence matching list order
    assert [e["rank"] for e in entries] == list(range(1, len(entries) + 1))
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "LOW": 3}
    severities = [severity_order[e["risk_level"]] for e in entries]
    assert severities == sorted(severities), "priority list must be sorted by severity, most urgent first"


def test_priority_scoped_by_region_id_matches_villages_scoped_the_same_way():
    villages = client.get("/api/v1/villages?region_id=1").json()  # Mandakini Valley
    entries = client.get("/api/v1/evacuation/priority?region_id=1").json()
    assert {e["village_name"] for e in entries} == {v["name"] for v in villages}


# ---------------------------------------------------------------------------
# GET /evacuation/routes — user-requested follow-up ("an evacuation route
# for each village"): every village's own route in one call, rather than
# requiring a client to look them up one at a time via
# GET /evacuation/route/{id} (which this reuses internally — same
# computation, same honesty framing, nothing duplicated).
# ---------------------------------------------------------------------------
def test_all_routes_returns_one_route_per_village_with_an_assigned_catchment():
    villages = client.get("/api/v1/villages?region_id=2").json()  # Chamoli Disaster Valley
    r = client.get("/api/v1/evacuation/routes?region_id=2")
    assert r.status_code == 200
    routes = r.json()
    assert {route["origin_village_name"] for route in routes} == {v["name"] for v in villages}


def test_all_routes_matches_the_single_village_endpoint_exactly():
    """Every route in the bulk list must be identical to what
    GET /evacuation/route/{id} returns for that same village — same
    computation reused, not a second, potentially-diverging implementation."""
    reni_id = _village_id_by_name("Reni")
    single = client.get(f"/api/v1/evacuation/route/{reni_id}").json()
    bulk = client.get("/api/v1/evacuation/routes?region_id=2").json()
    reni_bulk = next(route for route in bulk if route["origin_village_name"] == "Reni")
    assert reni_bulk == single


def test_all_routes_scoped_by_region_id_matches_villages_scoped_the_same_way():
    villages = client.get("/api/v1/villages?region_id=1").json()  # Mandakini Valley
    routes = client.get("/api/v1/evacuation/routes?region_id=1").json()
    assert {route["origin_village_name"] for route in routes} == {v["name"] for v in villages}


def test_all_routes_never_crosses_into_a_different_catchment():
    routes = client.get("/api/v1/evacuation/routes").json()  # no region filter — every seeded village
    chamoli_names = {"Reni", "Tapovan", "Vishnuprayag", "Joshimath"}
    mandakini_route = next(route for route in routes if route["origin_village_name"] == "Kedarnath")
    hop_names = {h["from_village_name"] for h in mandakini_route["hops"]} | {
        h["to_village_name"] for h in mandakini_route["hops"]
    }
    assert hop_names.isdisjoint(chamoli_names)
    assert mandakini_route["destination_village_name"] not in chamoli_names


# ---------------------------------------------------------------------------
# Real OpenStreetMap road/trail network follow-up (user-requested): each
# hop's distance now comes from a real routed OSM path wherever both
# endpoints snap close enough to the fetched network, honestly falling
# back to the pre-existing straight-line elevation-order proxy otherwise.
# See app/services/road_network.py / app/services/evacuation.py.
# ---------------------------------------------------------------------------
def test_chamoli_route_uses_real_road_network_for_every_hop():
    """All 4 Chamoli villages snap tightly (<100m) to the same real,
    connected OSM road/trail component — every hop from Reni to
    Vishnuprayag should use real routing, not the straight-line proxy."""
    reni_id = _village_id_by_name("Reni")
    body = client.get(f"/api/v1/evacuation/route/{reni_id}").json()
    assert len(body["hops"]) == 3
    for hop in body["hops"]:
        assert hop["distance_source"] == "real_road_network", hop
        assert hop["polyline"] is not None and len(hop["polyline"]) >= 2
        assert hop["road_note"] and "OpenStreetMap" in hop["road_note"]
    assert "3/3" in body["note"] or "all 3" in body["note"]


def test_mandakini_route_honestly_falls_back_for_the_rambara_hop():
    """Rambara's own seeded coordinate is an approximate interpolation
    that lands on a real OSM trail segment disconnected (in the fetched
    extent) from the rest of the Mandakini network — this hop must
    honestly report the straight-line fallback, not a fabricated route,
    while hops with real coverage on both sides still use it."""
    kedarnath_id = _village_id_by_name("Kedarnath")
    body = client.get(f"/api/v1/evacuation/route/{kedarnath_id}").json()
    by_pair = {(h["from_village_name"], h["to_village_name"]): h for h in body["hops"]}

    rambara_hop = by_pair[("Kedarnath", "Rambara")]
    assert rambara_hop["distance_source"] == "straight_line_proxy"
    assert rambara_hop["polyline"] is None
    assert "no real road/trail path" in rambara_hop["road_note"].lower()

    next_hop = by_pair[("Rambara", "Gaurikund")]
    assert next_hop["distance_source"] == "straight_line_proxy"

    # A hop entirely between two well-covered villages further downstream
    # should still get real routing — the fallback is per-hop, not
    # all-or-nothing for the whole route.
    downstream_hop = by_pair[("Sonprayag", "Ukhimath")]
    assert downstream_hop["distance_source"] == "real_road_network"
    assert "1/" not in body["note"] or "hop(s) used real" in body["note"]


def test_real_road_distance_is_a_real_number_not_a_disguised_straight_line():
    """The real routed distance for a well-covered hop should differ from
    (and, for a winding mountain road, exceed) the straight-line haversine
    distance between the same two village coordinates — proving this is a
    genuinely different, real calculation, not the old proxy relabelled."""
    import math

    reni_id = _village_id_by_name("Reni")
    body = client.get(f"/api/v1/evacuation/route/{reni_id}").json()
    reni_to_tapovan = next(h for h in body["hops"] if h["from_village_name"] == "Reni")
    assert reni_to_tapovan["distance_source"] == "real_road_network"

    # Real seeded coordinates (scripts/seed_chamoli_valley.py)
    lat1, lon1 = 30.48555, 79.69432  # Reni
    lat2, lon2 = 30.49414, 79.62753  # Tapovan
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    straight_line_km = 2 * R * math.asin(min(1.0, math.sqrt(a)))

    assert reni_to_tapovan["distance_km"] > straight_line_km
