"""
Unit tests for app/services/road_network.py — the real OpenStreetMap
road/trail network used by evacuation.py. Loads the committed derived
dataset (data/derived/real_himalaya_road_network.json), no live network
calls, no database needed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services import road_network  # noqa: E402


def setup_function(_):
    road_network._reset_cache_for_tests()


def teardown_function(_):
    road_network._reset_cache_for_tests()


def test_loads_the_committed_real_dataset():
    net = road_network.load_road_network()
    assert net is not None
    assert net.node_count > 1000
    assert net.edge_count > 1000
    assert "OpenStreetMap" in net.source
    assert "ODbL" in net.license or "Open Database License" in net.license


def test_nearest_node_snaps_kedarnath_to_a_real_nearby_trail_node():
    net = road_network.load_road_network()
    result = net.nearest_node(30.7346, 79.0669)  # real seeded Kedarnath coordinate
    assert result is not None
    _node_id, distance_m = result
    # Kedarnath's own coordinate sits right on a mapped OSM trail node —
    # a tight snap, not a coincidence of the search radius.
    assert distance_m < 100


def test_nearest_node_returns_none_far_from_any_fetched_extent():
    net = road_network.load_road_network()
    # The middle of the Arabian Sea — nowhere near either fetched bounding
    # box. Must return None (an honest "nothing nearby"), never a distant
    # match presented as if it were real coverage.
    result = net.nearest_node(15.0, 68.0)
    assert result is None


def test_find_real_route_between_well_covered_chamoli_villages():
    net = road_network.load_road_network()
    # Real seeded coordinates: Reni, Tapovan (scripts/seed_chamoli_valley.py)
    route = net.find_real_route(30.48555, 79.69432, 30.49414, 79.62753)
    assert route is not None
    assert 8000 < route.distance_m < 15000  # real road distance, order-of-magnitude sanity bound
    assert route.from_snap_distance_m < 100
    assert route.to_snap_distance_m < 100
    assert len(route.polyline) >= 2
    # Every polyline point is a real (lat, lon) pair, not a placeholder.
    for lat, lon in route.polyline:
        assert 30.0 < lat < 31.0
        assert 79.0 < lon < 80.0


def test_find_real_route_honestly_returns_none_for_a_disconnected_village():
    """Rambara's own seeded 'approximate' coordinate lands on a real OSM
    trail segment that this build's fetched Mandakini extent shows as
    disconnected from Kedarnath's component — this must come back None,
    never a fabricated route stitched across the gap."""
    net = road_network.load_road_network()
    kedarnath = (30.7346, 79.0669)
    rambara = (30.716, 79.058)
    route = net.find_real_route(*kedarnath, *rambara)
    assert route is None


def test_find_real_route_honestly_returns_none_beyond_max_snap_distance():
    net = road_network.load_road_network()
    # A point genuinely near Gaurikund's real road, but well past a very
    # tight snap tolerance — must be rejected rather than silently
    # accepted with a larger, unstated tolerance.
    route = net.find_real_route(30.674, 79.030, 30.617, 79.028, max_snap_m=10.0)
    assert route is None


def test_missing_dataset_degrades_honestly_to_none():
    """If the committed dataset file is ever absent on a deployment,
    load_road_network() must return None (letting evacuation.py fall back
    to the straight-line proxy) rather than raising or fabricating an
    empty-but-successful network."""
    original_path = road_network.DATA_PATH
    try:
        road_network.DATA_PATH = Path("/nonexistent/real_himalaya_road_network.json")
        road_network._reset_cache_for_tests()
        assert road_network.load_road_network() is None
    finally:
        road_network.DATA_PATH = original_path
        road_network._reset_cache_for_tests()


def test_network_is_cached_across_calls():
    net1 = road_network.load_road_network()
    net2 = road_network.load_road_network()
    assert net1 is net2
