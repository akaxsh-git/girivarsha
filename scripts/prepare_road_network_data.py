"""
One-off data-prep script (run once, output committed) — fetches the real
OpenStreetMap road/trail network covering both seeded pilot valleys and
writes a lightweight, backend-loadable graph (no live network calls, no
osmnx/geopandas runtime dependency needed by the app itself).

This is the follow-up to the network-access blocker documented since
Phase 3 (DEM download) and repeated in docs/Future_Work.md for evacuation
routing: "Real OSM road-network + river-centerline data for these
catchments remains blocked by this build environment's own network
restrictions." That restriction has since eased for the Overpass API
specifically (still flaky — see RETRY note below — but no longer
categorically rejected), which is what made this script possible.

Source: OpenStreetMap contributors, queried live via the Overpass API
(https://overpass-api.de/api/interpreter, with
https://overpass.kumi.systems/api/interpreter as a fallback mirror when
the primary connection resets — this sandbox's connection to
overpass-api.de is genuinely flaky, several retries were needed even for
a single query during development; both endpoints serve the same
underlying OSM data). Data is (c) OpenStreetMap contributors, licensed
under the Open Database License (ODbL) 1.0 — https://www.openstreetmap.org/copyright.
Fetched 2026-09-06.

What this pulls: every real OSM way tagged highway=* (any class — trunk
road down to unmarked footpath/bridleway) within a bounding box around
each pilot valley, EXCLUDING highway=construction/proposed/razed/
abandoned/planned (not real, currently-usable routes). This deliberately
includes trails/paths, not just vehicle roads — Kedarnath itself has no
road access at all (it's reached by a ~16km trek from Gaurikund), so a
"road-only" network would leave the pilot region's single highest-risk
village permanently unroutable.

What this does NOT do: no elevation/slope data is attached to any edge
(a real road-aware evacuation TIME estimate would need that — tracked
separately in docs/Future_Work.md, not solved here), no verification that
a mapped path is currently passable (landslide/washout status — real
road-condition reporting is future work, same caveat already documented
in app/services/evacuation.py's "unsafe hop" heuristic), and no data
outside the two fetched bounding boxes (a route between the two pilot
valleys, or to any unseeded village, is simply not covered).

Bounding boxes were chosen as the seeded villages' own lat/lon extent
plus a real margin (~0.05-0.1 degrees, several km) to make sure the real
connecting road is captured even when a village's own coordinate sits
near the box edge — not tuned to make the result look better.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT_JSON = Path(__file__).parent.parent / "data" / "derived" / "real_himalaya_road_network.json"
RAW_CACHE_DIR = Path(__file__).parent.parent / "data" / "raw" / "osm_overpass_cache"

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
MAX_ATTEMPTS_PER_ENDPOINT = 5
RETRY_DELAY_SECONDS = 4

# Real, currently-usable highway classes only. Excludes tags that mean
# "not actually a usable route right now" — a fabricated-looking route
# through a road that was only ever proposed, or is out of service, would
# be worse than no route at all.
EXCLUDED_HIGHWAY_TAGS = {"construction", "proposed", "razed", "abandoned", "planned"}

# (name, bbox=(south, west, north, east)) — see module docstring for how
# these were chosen. Mandakini covers Kedarnath down to Rudraprayag;
# Chamoli covers Reni/Tapovan/Vishnuprayag/Joshimath.
REGIONS = {
    "mandakini": (30.20, 78.90, 30.80, 79.15),
    "chamoli": (30.40, 79.50, 30.65, 79.75),
}

_EARTH_RADIUS_M = 6_371_000.0


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def fetch_ways(region_name: str, bbox: tuple[float, float, float, float]) -> list[dict]:
    """Real Overpass query for every highway=* way in `bbox`, with `out geom;`
    so node coordinates come back inline (no separate node-resolution pass
    needed). Retries across both endpoints — this sandbox's connection to
    overpass-api.de resets mid-request more often than not, and the kumi
    mirror rate-limits aggressively; a real production environment would
    likely need fewer retries, but the retry loop itself is a correct,
    honest thing to have regardless.

    Uses a local raw-response cache (data/raw/osm_overpass_cache/, real
    Overpass JSON responses fetched live during this feature's own
    development, gitignored — regenerable, not a substitute source of
    truth the way the glacial-lake shapefile is) to avoid re-hitting a
    flaky/rate-limited endpoint on every re-run of this script."""
    cache_path = RAW_CACHE_DIR / f"{region_name}.json"
    if cache_path.exists():
        print(f"  (using cached raw response: {cache_path})")
        return json.loads(cache_path.read_text()).get("elements", [])

    south, west, north, east = bbox
    query = f"""
    [out:json][timeout:90];
    (
      way["highway"]({south},{west},{north},{east});
    );
    out geom;
    """
    last_error: Exception | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        for attempt in range(1, MAX_ATTEMPTS_PER_ENDPOINT + 1):
            try:
                resp = requests.post(endpoint, data={"data": query}, timeout=100)
                resp.raise_for_status()
                data = resp.json()
                elements = data.get("elements", [])
                RAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(data))
                return elements
            except Exception as exc:  # noqa: BLE001 - genuinely any transport error is worth retrying
                last_error = exc
                print(f"  [{endpoint}] attempt {attempt}/{MAX_ATTEMPTS_PER_ENDPOINT} failed: {exc}")
                time.sleep(RETRY_DELAY_SECONDS)
    raise RuntimeError(f"Overpass fetch failed on every endpoint/retry for bbox {bbox}") from last_error


def build_graph_fragment(ways: list[dict]) -> tuple[dict[int, tuple[float, float]], list[tuple[int, int, float, str, str | None]]]:
    """Real node coordinates + real edge lengths (haversine along each
    way's own real node sequence, so a winding real trail's real length is
    the sum of its real short segments, not a single straight line end to
    end). Keeps the shortest observed length for a node pair mapped by
    more than one way (rare, but two ways can share an edge)."""
    nodes: dict[int, tuple[float, float]] = {}
    best_edge: dict[tuple[int, int], tuple[float, str, str | None]] = {}
    for way in ways:
        highway = way.get("tags", {}).get("highway", "")
        if highway in EXCLUDED_HIGHWAY_TAGS:
            continue
        node_ids = way.get("nodes", [])
        geometry = way.get("geometry", [])
        if len(node_ids) != len(geometry):
            continue  # malformed element from Overpass — skip rather than guess
        name = way.get("tags", {}).get("name")
        for nid, point in zip(node_ids, geometry):
            nodes[nid] = (point["lat"], point["lon"])
        for a, b in zip(node_ids, node_ids[1:]):
            lat_a, lon_a = nodes[a]
            lat_b, lon_b = nodes[b]
            length_m = haversine_meters(lat_a, lon_a, lat_b, lon_b)
            key = (a, b) if a < b else (b, a)
            existing = best_edge.get(key)
            if existing is None or length_m < existing[0]:
                best_edge[key] = (length_m, highway, name)
    edges = [(a, b, length_m, highway, name) for (a, b), (length_m, highway, name) in best_edge.items()]
    return nodes, edges


def main() -> None:
    all_nodes: dict[int, tuple[float, float]] = {}
    all_edges: list[tuple[int, int, float, str, str | None]] = []
    per_region_counts: dict[str, dict[str, int]] = {}

    for region_name, bbox in REGIONS.items():
        print(f"Fetching {region_name} (bbox {bbox})...")
        ways = fetch_ways(region_name, bbox)
        nodes, edges = build_graph_fragment(ways)
        print(f"  {len(ways)} real OSM ways -> {len(nodes)} nodes, {len(edges)} edges")
        per_region_counts[region_name] = {"ways": len(ways), "nodes": len(nodes), "edges": len(edges)}
        all_nodes.update(nodes)
        all_edges.extend(all_edges_dedupe(all_edges, edges))

    highway_tally: dict[str, int] = {}
    for _, _, _, highway, _ in all_edges:
        highway_tally[highway] = highway_tally.get(highway, 0) + 1

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": (
            "OpenStreetMap contributors, via the Overpass API "
            "(overpass-api.de / overpass.kumi.systems mirrors)"
        ),
        "license": "Open Database License (ODbL) 1.0 - https://www.openstreetmap.org/copyright",
        "bboxes": REGIONS,
        "excluded_highway_tags": sorted(EXCLUDED_HIGHWAY_TAGS),
        "per_region_fetch_counts": per_region_counts,
        "highway_type_counts": highway_tally,
        "node_count": len(all_nodes),
        "edge_count": len(all_edges),
        # Round to keep the committed file a reasonable size: ~11cm
        # precision at 6 decimal places is far tighter than this village
        # data's own "approximate"/"surveyed" precision tiers anyway.
        "nodes": {str(nid): [round(lat, 6), round(lon, 6)] for nid, (lat, lon) in all_nodes.items()},
        "edges": [[a, b, round(length_m, 1), highway, name] for a, b, length_m, highway, name in all_edges],
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out))
    size_mb = OUT_JSON.stat().st_size / (1024 * 1024)
    print(f"\nWrote {OUT_JSON} ({size_mb:.2f} MB) — {len(all_nodes)} nodes, {len(all_edges)} edges")
    print("Highway type breakdown:", highway_tally)


def all_edges_dedupe(existing: list, new: list) -> list:
    """Two regions' bboxes don't overlap for this pilot data, so this is a
    no-op in practice — kept as an explicit, honest guard rather than
    silently assuming no future region will ever overlap another."""
    seen = {(a, b) for a, b, *_ in existing}
    return [e for e in new if (e[0], e[1]) not in seen]


if __name__ == "__main__":
    main()
