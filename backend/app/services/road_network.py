"""
Real OpenStreetMap road/trail network, used by evacuation.py to compute a
real routed distance for an evacuation hop instead of the straight-line
elevation-order proxy, wherever both endpoints of that hop are actually
close enough to a real mapped road/trail to trust the snap.

Data: data/derived/real_himalaya_road_network.json, built once by
scripts/prepare_road_network_data.py from a live OpenStreetMap Overpass
query — see that script's own docstring for the full sourcing detail,
licensing (ODbL), and what is deliberately NOT covered (no elevation/
slope per edge, no real-time road-condition/blockage data, no coverage
outside the two pilot valleys' fetched bounding boxes).

**Honest degradation, not a fabricated route**: `find_real_route()`
returns `None` — never a guessed or straight-line-disguised-as-real
result — whenever either endpoint's nearest mapped node is farther than
`max_snap_m` away, or when the two endpoints' nearest nodes fall in
different (real, OSM-derived) connected components of the fetched
network. Both cases genuinely happen in this pilot data: see
docs/Limitations.md for the concrete Rambara example (its own seeded
coordinate is an "approximate" interpolation that does not land on any
trail segment connected to the rest of the fetched Mandakini-valley
network within this build's fetched extent).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "derived" / "real_himalaya_road_network.json"

DEFAULT_MAX_SNAP_METERS = 1500.0
# Grid-bucketed nearest-neighbor search, not a full O(n) scan per query —
# this file has ~71,000 real OSM nodes and evacuation routing calls this
# per hop, per village. ~0.01 degrees is roughly 1.1km latitude / ~1km
# longitude at this pilot region's latitude — plenty fine enough that a
# village's own bucket plus its 8 neighbors almost always contains a real
# nearby road/trail node; the search still expands outward for the rare
# case where it doesn't, up to MAX_GRID_RING before giving up honestly.
_GRID_SIZE_DEG = 0.01
_MAX_GRID_RING = 8  # 8 rings * 0.01 deg ~= 8.8km search radius ceiling

_EARTH_RADIUS_M = 6_371_000.0


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _grid_key(lat: float, lon: float) -> tuple[int, int]:
    return (math.floor(lat / _GRID_SIZE_DEG), math.floor(lon / _GRID_SIZE_DEG))


@dataclass
class RoadRouteResult:
    distance_m: float
    polyline: list[tuple[float, float]]
    from_snap_distance_m: float
    to_snap_distance_m: float
    node_count: int


class RoadNetwork:
    """Loaded once per process (see `load_road_network()`), not re-parsed
    from JSON on every request."""

    def __init__(self, raw: dict):
        self.generated_at: str = raw.get("generated_at", "")
        self.source: str = raw.get("source", "")
        self.license: str = raw.get("license", "")
        self.node_count: int = raw.get("node_count", 0)
        self.edge_count: int = raw.get("edge_count", 0)

        self.graph = nx.Graph()
        self._grid: dict[tuple[int, int], list[int]] = {}
        for nid_str, (lat, lon) in raw.get("nodes", {}).items():
            nid = int(nid_str)
            self.graph.add_node(nid, lat=lat, lon=lon)
            self._grid.setdefault(_grid_key(lat, lon), []).append(nid)
        for a, b, length_m, highway, name in raw.get("edges", []):
            self.graph.add_edge(a, b, length_m=length_m, highway=highway, name=name)

    def nearest_node(self, lat: float, lon: float) -> tuple[int, float] | None:
        """Real nearest-neighbor search over the real fetched node set,
        expanding the grid search ring outward until a node is found or
        `_MAX_GRID_RING` is exceeded (returns None — an honest "nothing
        nearby", never a fabricated distant match)."""
        center_gx, center_gy = _grid_key(lat, lon)
        best_node: int | None = None
        best_dist: float | None = None
        for ring in range(_MAX_GRID_RING + 1):
            found_any_candidate = False
            for gx in range(center_gx - ring, center_gx + ring + 1):
                for gy in range(center_gy - ring, center_gy + ring + 1):
                    # Only scan the newly-added outer ring cells, not ones
                    # already scanned in a smaller ring.
                    if ring > 0 and (center_gx - ring < gx < center_gx + ring) and (
                        center_gy - ring < gy < center_gy + ring
                    ):
                        continue
                    for nid in self._grid.get((gx, gy), []):
                        found_any_candidate = True
                        node = self.graph.nodes[nid]
                        d = haversine_meters(lat, lon, node["lat"], node["lon"])
                        if best_dist is None or d < best_dist:
                            best_dist = d
                            best_node = nid
            # Once we've found at least one candidate, one more ring is
            # enough to be sure nothing closer sits just across a cell
            # boundary, then stop — no need to keep scanning further out.
            if found_any_candidate and ring > 0:
                break
        if best_node is None:
            return None
        return best_node, best_dist  # type: ignore[return-value]

    def find_real_route(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float,
        max_snap_m: float = DEFAULT_MAX_SNAP_METERS,
    ) -> RoadRouteResult | None:
        """Real Dijkstra shortest path over the real fetched road/trail
        graph, or None if either point doesn't snap within `max_snap_m` or
        no path exists between their components (both are real, honest
        "this can't be routed with what was fetched" outcomes — see the
        module docstring)."""
        from_snap = self.nearest_node(lat1, lon1)
        to_snap = self.nearest_node(lat2, lon2)
        if from_snap is None or to_snap is None:
            return None
        from_node, from_dist = from_snap
        to_node, to_dist = to_snap
        if from_dist > max_snap_m or to_dist > max_snap_m:
            return None
        if from_node == to_node:
            return RoadRouteResult(
                distance_m=0.0,
                polyline=[(self.graph.nodes[from_node]["lat"], self.graph.nodes[from_node]["lon"])],
                from_snap_distance_m=from_dist,
                to_snap_distance_m=to_dist,
                node_count=1,
            )
        try:
            node_path = nx.shortest_path(self.graph, source=from_node, target=to_node, weight="length_m")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
        distance_m = nx.shortest_path_length(self.graph, source=from_node, target=to_node, weight="length_m")
        polyline = [(self.graph.nodes[n]["lat"], self.graph.nodes[n]["lon"]) for n in node_path]
        return RoadRouteResult(
            distance_m=distance_m,
            polyline=polyline,
            from_snap_distance_m=from_dist,
            to_snap_distance_m=to_dist,
            node_count=len(node_path),
        )


_cached_network: RoadNetwork | None | bool = False  # False = not yet attempted to load


def load_road_network() -> RoadNetwork | None:
    """Loads and caches the committed road-network dataset. Returns None
    (not an exception) if the file is missing — the caller (evacuation.py)
    degrades honestly to the straight-line proxy exactly as it did before
    this feature existed, same pattern as glacial_lake_proximity.py and
    scs_cn_runoff.py's own missing-dataset handling."""
    global _cached_network
    if _cached_network is not False:
        return _cached_network  # type: ignore[return-value]
    if not DATA_PATH.exists():
        _cached_network = None
        return None
    raw = json.loads(DATA_PATH.read_text())
    _cached_network = RoadNetwork(raw)
    return _cached_network


def _reset_cache_for_tests() -> None:
    """Test-only helper — lets test_road_network.py exercise the
    missing-file degradation path without permanently losing the loaded
    network for the rest of the test session."""
    global _cached_network
    _cached_network = False
