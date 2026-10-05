"""
Phase 10: prototype lead-time estimation (problem-statement item — "how much
warning time does a downstream village get").

Explicitly a PROTOTYPE, not a validated hydrological model. Two real
simplifications, both stated here rather than hidden in the formula:

1. **Upstream neighbor = elevation-order proxy**, the same simplification
   `risk_engine.py`'s `upstream_rainfall` component already uses (see its
   docstring) — not a walk of real, surveyed river-channel topology. For a
   village, its "upstream monitoring point" is the OTHER village in the
   same micro-catchment with the smallest elevation gap above it. This is
   already a documented, pre-existing limitation of the pilot data, not a
   new one introduced here.
2. **A single assumed flow velocity, not per-reach hydraulics.** Distance
   is computed as straight-line (haversine) between two points, not real
   river-course distance (same caveat `PilotMap.tsx`'s dashed line already
   carries), and divided by one constant velocity for the whole valley —
   not a channel-geometry/slope/discharge-aware routing model (that needs
   HEC-RAS or equivalent, tracked in docs/Future_Work.md).

ASSUMED_FLOW_VELOCITY_M_S is grounded in a real, citable published range —
not invented: Wikipedia's "Debris flow" article states debris flows
"descending steep channels commonly attain speeds that surpass 10 m/s"
(https://en.wikipedia.org/wiki/Debris_flow, citing the geohazard
literature). 5 m/s is used here as a deliberately CONSERVATIVE single
value for the whole valley (steep upper reaches can exceed 10 m/s; the
gentler lower valley moves slower) — a placeholder pending real
per-reach hydraulic modeling, not a Kedarnath-specific calibrated figure.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from app.models.orm import Village

ASSUMED_FLOW_VELOCITY_M_S = 5.0
VELOCITY_CITATION = (
    "Debris flows in steep channels commonly exceed 10 m/s (Wikipedia: Debris flow, "
    "citing published geohazard literature). 5 m/s used here as a deliberately "
    "conservative single-value placeholder for the whole valley, not a calibrated, "
    "site-specific figure — see app/services/lead_time.py."
)

_EARTH_RADIUS_M = 6_371_000.0


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Real great-circle distance — NOT real river-course distance (a river winds;
    this is a straight line), same caveat as the dashed line in PilotMap.tsx."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


@dataclass
class LeadTimeEstimate:
    minutes: float | None
    upstream_village_name: str | None
    straight_line_distance_km: float | None
    assumed_velocity_m_s: float
    note: str


def village_latlon(village: Village) -> tuple[float, float]:
    """Real (lat, lon) extracted from the village's PostGIS point. Public
    (no leading underscore) so other services — e.g.
    app/services/glacial_lake_proximity.py — can reuse the same extraction
    instead of duplicating the geoalchemy2 shape-conversion call."""
    from geoalchemy2.shape import to_shape

    p = to_shape(village.location)
    return p.y, p.x


# Back-compat alias for this module's own earlier internal name.
_village_latlon = village_latlon


def estimate_lead_time(village: Village, siblings_in_catchment: list[Village]) -> LeadTimeEstimate:
    """Nearest upstream neighbor (smallest positive elevation gap) -> straight-line
    distance -> minutes at ASSUMED_FLOW_VELOCITY_M_S. Returns minutes=None for a
    catchment-source village (nothing upstream to propagate a warning from) —
    never a fabricated number."""
    if village.catchment_id is None:
        return LeadTimeEstimate(
            minutes=None,
            upstream_village_name=None,
            straight_line_distance_km=None,
            assumed_velocity_m_s=ASSUMED_FLOW_VELOCITY_M_S,
            note="Village has no assigned micro-catchment — cannot estimate an upstream propagation time.",
        )

    village_elev = village.elevation_m or 0
    candidates = [
        v for v in siblings_in_catchment
        if v.id != village.id and v.catchment_id == village.catchment_id and (v.elevation_m or 0) > village_elev
    ]
    if not candidates:
        return LeadTimeEstimate(
            minutes=None,
            upstream_village_name=None,
            straight_line_distance_km=None,
            assumed_velocity_m_s=ASSUMED_FLOW_VELOCITY_M_S,
            note=(
                "This is the highest-elevation (source) village monitored in its micro-catchment — "
                "no upstream monitoring point exists to estimate propagation time from."
            ),
        )

    nearest = min(candidates, key=lambda v: (v.elevation_m or 0) - village_elev)

    lat1, lon1 = _village_latlon(village)
    lat2, lon2 = _village_latlon(nearest)
    distance_m = haversine_meters(lat1, lon1, lat2, lon2)
    minutes = round(distance_m / ASSUMED_FLOW_VELOCITY_M_S / 60, 1)

    return LeadTimeEstimate(
        minutes=minutes,
        upstream_village_name=nearest.name,
        straight_line_distance_km=round(distance_m / 1000, 2),
        assumed_velocity_m_s=ASSUMED_FLOW_VELOCITY_M_S,
        note=(
            f"Prototype estimate: straight-line distance to {nearest.name} (nearest upstream village "
            f"by elevation-order proxy — not real river-channel topology) divided by an assumed "
            f"{ASSUMED_FLOW_VELOCITY_M_S:.0f} m/s flow velocity ({VELOCITY_CITATION}). "
            "NOT a validated hydraulic model — treat as an order-of-magnitude figure, not a promise."
        ),
    )
