"""
Phase 12: evacuation routing + priority ranking (problem-statement item —
"shortest path to shelters, unsafe-road flagging, evacuation priority
ranking"). Like lead_time.py, this is a transparent PROTOTYPE, not a
validated routing engine, and every simplification is stated here rather
than hidden in the formula.

Real components used:
  - The real per-catchment village topology (Phase 2/11) and real elevation
    values.
  - **As of the road-network follow-up below: a real OpenStreetMap
    road/trail network** (app/services/road_network.py,
    data/derived/real_himalaya_road_network.json, built by
    scripts/prepare_road_network_data.py) — a real Dijkstra shortest path
    over real mapped road/trail geometry, used for a hop WHENEVER both
    endpoint villages snap close enough to the real network (see
    `ROAD_SNAP_MAX_METERS` below) and a real path connects them within
    the fetched extent.
  - Real haversine (straight-line) distances between real village
    coordinates, still used as the honest FALLBACK for any hop where the
    real road network doesn't cover it (see "what is NOT real" below).
  - Real, live-computed risk levels (Phase 4) for the "unsafe hop" flag.

What is NOT real, stated plainly:
  - **Real road/trail coverage is not universal even within this pilot
    data.** A hop falls back to the straight-line proxy whenever either
    endpoint village's own coordinate doesn't snap within
    `ROAD_SNAP_MAX_METERS` of a real mapped road/trail node, or no real
    path connects the two within the fetched bounding boxes. This
    genuinely happens here: Rambara's own seeded coordinate is an
    "approximate" interpolation (see scripts/seed_pilot_region.py), not a
    surveyed point, and it lands on a real trail segment that the fetched
    Mandakini-valley extent shows as disconnected from the rest of the
    network — see docs/Limitations.md for the concrete detail. Each hop's
    own `distance_source` field says honestly which case applies; nothing
    is silently blended.
  - **The road/trail network itself only covers the two pilot valleys'
    fetched bounding boxes** — see road_network.py's module docstring.
    No elevation/slope is attached to any real edge, and no real-time
    road-condition/blockage/landslide data exists for any of it.
  - **The evacuation "destination" is the catchment's real, lowest-
    elevation seeded settlement** (e.g. Rudraprayag for the Mandakini
    valley, Vishnuprayag for the Chamoli valley) — a real, named place,
    never a fabricated "shelter" building. The `shelters` table
    (app/models/orm.py::Shelter) stays empty rather than populated with
    invented shelter locations; see docs/Region_Onboarding.md for what
    real shelter sourcing (NDMA/district shelter registries, on-ground
    survey) would need to look like before that table gets used for real.
  - **Route hops still connect consecutive villages in elevation order
    within the same catchment** (unchanged from before this follow-up) —
    only the DISTANCE computed for each hop changed (real road/trail
    routing where available, the same elevation-order-proxy straight line
    where not), not which villages are treated as consecutive waypoints.
  - **"Unsafe hop" is still a derived heuristic**, not real road-hazard/
    landslide-blockage data: a hop is flagged unsafe if either endpoint
    village's CURRENT live risk level is HIGH or CRITICAL. This is an
    honest, transparent proxy, now applied to a real road-segment hop
    where one exists — real road-condition reporting (e.g. an actual
    reported washout/blockage) remains future work.
  - **Estimated evacuation time uses a single assumed on-foot pace**,
    grounded in Naismith's Rule's base rate (5 km/h on the flat — a real,
    long-published hillwalking-pace rule of thumb; see
    https://en.wikipedia.org/wiki/Naismith%27s_rule), not a
    terrain-aware, congestion-aware, or vehicle-based estimate — this is
    unchanged by the road-network follow-up; a real per-route timing
    estimate would need real elevation/slope data per road segment, which
    the fetched OSM data does not include.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from app.models.orm import RiskLevel, Village
from app.services.lead_time import haversine_meters
from app.services.road_network import load_road_network

# A village's own coordinate is often "approximate" (interpolated/derived,
# not surveyed — see Village.coordinate_precision), so some slack is
# needed between "this is really on the mapped road" and "this coordinate
# just happens to be a few hundred metres from any road at all, like every
# point in a river valley eventually is". 1.5km is generous enough to
# accept every well-covered village in this pilot data (largest genuine
# snap seen: Sonprayag at ~1.04km) while still rejecting a village that
# isn't really near the fetched network (e.g. one entirely outside both
# bounding boxes).
ROAD_SNAP_MAX_METERS = 1500.0

ASSUMED_WALKING_SPEED_KMH = 5.0
WALKING_SPEED_CITATION = (
    "Naismith's Rule's base hillwalking pace (5 km/h on the flat) — "
    "https://en.wikipedia.org/wiki/Naismith%27s_rule — used here as a single, "
    "citable, order-of-magnitude assumption. Does not account for terrain "
    "difficulty, congestion, ascent/descent, or vehicle evacuation, all of which "
    "would change real evacuation time meaningfully."
)
UNSAFE_RISK_LEVELS = {RiskLevel.HIGH, RiskLevel.CRITICAL}


def _village_latlon(village: Village) -> tuple[float, float]:
    from geoalchemy2.shape import to_shape

    p = to_shape(village.location)
    return p.y, p.x


@dataclass
class RouteHop:
    from_village_id: int
    from_village_name: str
    to_village_id: int
    to_village_name: str
    distance_km: float
    unsafe: bool
    unsafe_reason: str | None
    # Road-network follow-up: which distance calculation actually produced
    # `distance_km` for this hop — never blended silently.
    distance_source: str = "straight_line_proxy"  # or "real_road_network"
    road_note: str | None = None
    # Ordered [lat, lon] points along the real road/trail path, only when
    # distance_source == "real_road_network" — lets the frontend draw the
    # real route instead of a straight line. None for a straight-line hop.
    polyline: list[tuple[float, float]] | None = None


@dataclass
class EvacuationRoute:
    origin_village_id: int
    origin_village_name: str
    destination_village_id: int | None
    destination_village_name: str | None
    hops: list[RouteHop] = field(default_factory=list)
    total_distance_km: float = 0.0
    estimated_minutes: float | None = None
    note: str = ""


def build_catchment_graph(villages_in_catchment: list[Village]) -> nx.DiGraph:
    """Real networkx DiGraph: one node per village, directed edges between
    CONSECUTIVE villages in elevation order (highest -> next-highest, i.e.
    toward the outlet) — same proxy as PilotMap.tsx's per-catchment dashed
    line, not real trail/road geometry. Edge weight = real haversine
    distance in metres."""
    graph = nx.DiGraph()
    ordered = sorted(villages_in_catchment, key=lambda v: -(v.elevation_m or 0))
    for v in ordered:
        graph.add_node(v.id, village=v)
    for a, b in zip(ordered, ordered[1:]):
        lat1, lon1 = _village_latlon(a)
        lat2, lon2 = _village_latlon(b)
        distance_m = haversine_meters(lat1, lon1, lat2, lon2)
        graph.add_edge(a.id, b.id, distance_m=distance_m)
    return graph


def evacuation_route(
    origin: Village,
    villages_in_catchment: list[Village],
    risk_levels: dict[int, RiskLevel],
) -> EvacuationRoute:
    """Real shortest-path search (networkx Dijkstra) from `origin` to its
    catchment's real, lowest-elevation seeded village — see module
    docstring for exactly what is real vs. a stated simplification.
    `risk_levels` maps village_id -> its CURRENT live risk level (computed
    by the caller via risk_engine.py) and drives the 'unsafe hop' flag."""
    if origin.catchment_id is None:
        return EvacuationRoute(
            origin_village_id=origin.id,
            origin_village_name=origin.name,
            destination_village_id=None,
            destination_village_name=None,
            note="Village has no assigned micro-catchment — cannot compute an evacuation route.",
        )

    siblings = [v for v in villages_in_catchment if v.catchment_id == origin.catchment_id]
    graph = build_catchment_graph(siblings)
    outlet = min(siblings, key=lambda v: (v.elevation_m or 0))

    if origin.id == outlet.id:
        return EvacuationRoute(
            origin_village_id=origin.id,
            origin_village_name=origin.name,
            destination_village_id=outlet.id,
            destination_village_name=outlet.name,
            note=(
                f"{origin.name} is already this catchment's lowest-elevation seeded settlement "
                "(the modelled evacuation destination) — no route to compute."
            ),
        )

    try:
        node_path = nx.shortest_path(graph, source=origin.id, target=outlet.id, weight="distance_m")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return EvacuationRoute(
            origin_village_id=origin.id,
            origin_village_name=origin.name,
            destination_village_id=outlet.id,
            destination_village_name=outlet.name,
            note=(
                f"No path found from {origin.name} to {outlet.name} in this catchment's "
                "elevation-order graph — this shouldn't happen for a single-chain catchment; "
                "check the seeded topology."
            ),
        )

    by_id = {v.id: v for v in siblings}
    road_network = load_road_network()
    hops: list[RouteHop] = []
    total_m = 0.0
    real_hop_count = 0
    fallback_reasons: list[str] = []
    for a_id, b_id in zip(node_path, node_path[1:]):
        edge = graph.edges[a_id, b_id]
        straight_line_m = edge["distance_m"]
        a_village, b_village = by_id[a_id], by_id[b_id]

        distance_m = straight_line_m
        distance_source = "straight_line_proxy"
        road_note: str | None = None
        polyline: list[tuple[float, float]] | None = None

        if road_network is not None:
            lat_a, lon_a = _village_latlon(a_village)
            lat_b, lon_b = _village_latlon(b_village)
            real_route = road_network.find_real_route(lat_a, lon_a, lat_b, lon_b, max_snap_m=ROAD_SNAP_MAX_METERS)
            if real_route is not None:
                distance_m = real_route.distance_m
                distance_source = "real_road_network"
                polyline = real_route.polyline
                road_note = (
                    f"Real OpenStreetMap road/trail path ({real_route.node_count} mapped points), "
                    f"snapped {real_route.from_snap_distance_m:.0f}m from {a_village.name}'s own "
                    f"coordinate and {real_route.to_snap_distance_m:.0f}m from {b_village.name}'s."
                )
                real_hop_count += 1
            else:
                road_note = (
                    f"No real road/trail path found connecting {a_village.name} and {b_village.name} "
                    f"within {ROAD_SNAP_MAX_METERS:.0f}m of either coordinate in the fetched OSM extent "
                    "— using the straight-line elevation-order proxy for this hop instead."
                )
                fallback_reasons.append(f"{a_village.name}→{b_village.name}: {road_note}")
        else:
            road_note = (
                "Road-network dataset not found on this deployment — using the straight-line "
                "elevation-order proxy for this hop (see app/services/road_network.py)."
            )
            fallback_reasons.append(road_note)

        total_m += distance_m
        a_level = risk_levels.get(a_id)
        b_level = risk_levels.get(b_id)
        unsafe = a_level in UNSAFE_RISK_LEVELS or b_level in UNSAFE_RISK_LEVELS
        unsafe_reason = None
        if unsafe:
            flagged = a_village.name if a_level in UNSAFE_RISK_LEVELS else b_village.name
            level = a_level if a_level in UNSAFE_RISK_LEVELS else b_level
            unsafe_reason = (
                f"{flagged} currently at {level.value if level else '?'} risk — derived heuristic, "
                "not real road-condition/landslide-blockage data (see app/services/evacuation.py)."
            )
        hops.append(
            RouteHop(
                from_village_id=a_id,
                from_village_name=a_village.name,
                to_village_id=b_id,
                to_village_name=b_village.name,
                distance_km=round(distance_m / 1000, 2),
                unsafe=unsafe,
                unsafe_reason=unsafe_reason,
                distance_source=distance_source,
                road_note=road_note,
                polyline=polyline,
            )
        )

    total_km = round(total_m / 1000, 2)
    estimated_minutes = round(total_m / 1000 / ASSUMED_WALKING_SPEED_KMH * 60, 1)

    if real_hop_count == len(hops):
        coverage_note = f"all {len(hops)} hop(s) used real OpenStreetMap road/trail routing"
    elif real_hop_count == 0:
        coverage_note = (
            f"none of the {len(hops)} hop(s) had real road/trail coverage — the straight-line "
            "elevation-order proxy was used throughout, see each hop's own road_note"
        )
    else:
        coverage_note = (
            f"{real_hop_count}/{len(hops)} hop(s) used real OpenStreetMap road/trail routing, "
            f"{len(hops) - real_hop_count} fell back to the straight-line proxy — see each hop's "
            "own road_note for why"
        )

    return EvacuationRoute(
        origin_village_id=origin.id,
        origin_village_name=origin.name,
        destination_village_id=outlet.id,
        destination_village_name=outlet.name,
        hops=hops,
        total_distance_km=total_km,
        estimated_minutes=estimated_minutes,
        note=(
            f"Prototype route: {len(hops)} hop(s) along the real elevation-order chain from "
            f"{origin.name} to {outlet.name} (this catchment's real, lowest-elevation seeded "
            f"settlement), {total_km} km total distance ({coverage_note}), at an assumed "
            f"{ASSUMED_WALKING_SPEED_KMH:.0f} km/h on-foot pace ({WALKING_SPEED_CITATION})."
        ),
    )


@dataclass
class PriorityEntry:
    village_id: int
    village_name: str
    risk_level: str
    risk_score: float
    lead_time_minutes: int | None
    rank: int


_SEVERITY_RANK = {
    RiskLevel.CRITICAL: 0,
    RiskLevel.HIGH: 1,
    RiskLevel.MODERATE: 2,
    RiskLevel.LOW: 3,
}


def evacuation_priority(
    entries: list[tuple[Village, RiskLevel, float, int | None]],
) -> list[PriorityEntry]:
    """Transparent sort, not a fabricated composite urgency score: rank by
    risk level severity first (CRITICAL > HIGH > MODERATE > LOW), then by
    LESS lead time (less warning = more urgent) with no-upstream-estimate
    villages sorted last within their level, then by higher risk score as a
    final tie-break. Every input here is already real/derived elsewhere
    (Phase 4 risk engine, Phase 10 lead-time estimator) — this function
    only orders them; it invents no new number."""
    sortable = sorted(
        entries,
        key=lambda e: (
            _SEVERITY_RANK.get(e[1], 99),
            e[3] if e[3] is not None else float("inf"),
            -e[2],
        ),
    )
    return [
        PriorityEntry(
            village_id=v.id,
            village_name=v.name,
            risk_level=level.value,
            risk_score=score,
            lead_time_minutes=lead_time,
            rank=i + 1,
        )
        for i, (v, level, score, lead_time) in enumerate(sortable)
    ]
