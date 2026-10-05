"""
Real glacial-lake-proximity indicator (`docs/Future_Work.md` follow-up,
user-requested).

Real, coordinate-located data: Zhang, G. et al. (2023), "Underestimated
mass loss from lake-terminating glaciers in the greater Himalaya", Nature
Geoscience (DOI: 10.1038/s41561-023-01150-1) — 4,881 real, individually
satellite-mapped glacial lakes across India's Himalayan arc (Western/
Central/Eastern Himalaya regions, 2020 snapshot), pre-processed by
`scripts/prepare_glacial_lake_data.py` into `data/derived/real_himalaya_glacial_lakes.csv`.
See `docs/Data_Sources.md` for the full citation.

**Deliberately an ADVISORY field, not a new weighted risk-engine
component.** For each village, this computes the real great-circle
distance to the nearest lake in the inventory — a real, honest number.
What it does NOT do: turn that distance into a risk contribution folded
into `risk_score`. Two real reasons, stated plainly rather than papered
over:

1. **Raw distance is a weak proxy for actual GLOF hazard.** A large,
   moraine-dammed lake 20km away down a steep channel is a real hazard; a
   small, bedrock-dammed lake 2km away with no downstream village in its
   flow path may not be. Distance alone, without lake type, dam
   material, volume, and downstream slope/channel analysis, would be a
   plausible-looking but scientifically unjustified number to fold into
   a weighted score.
2. **No real calibration data exists** to say how much weight proximity
   should carry relative to the baseline's existing 4 components — the
   same honesty problem `docs/ML_Methodology.md` already documents for
   the ML layer. An uncalibrated 5th weight would look precise without
   being validated.

So this is exposed as `glacial_lake_distance_km` / `glacial_lake_note` —
visible next to the risk score, real and useful context, but explicitly
not part of the score or level. If real lake-attribute-aware GLOF hazard
research becomes available, that's the path to a real weighted
component — tracked in `docs/Future_Work.md`.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services.lead_time import haversine_meters

DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "derived" / "real_himalaya_glacial_lakes.csv"

# A lake more than this far away isn't a meaningfully "nearby" GLOF concern
# for a village-level indicator — keeps the note honest rather than always
# reporting the technically-nearest lake even when it's 300km away.
MAX_RELEVANT_DISTANCE_KM = 100.0


@dataclass
class GlacialLakeRecord:
    lake_id: str
    lat: float
    lon: float
    area_km2: float | None
    elevation_m: float | None
    lake_type: str
    region: str


@dataclass
class GlacialLakeProximity:
    distance_km: float | None
    nearest_lake: GlacialLakeRecord | None
    note: str


@lru_cache(maxsize=1)
def _load_lakes() -> tuple[GlacialLakeRecord, ...]:
    """Loads the real, pre-processed lake inventory once per process. If the
    data file is missing (e.g. a checkout that hasn't run the prep script),
    this returns an empty tuple rather than crashing the risk engine —
    every caller must handle the "no data available" case honestly, same
    discipline as a provider outage elsewhere in this app."""
    if not DATA_PATH.exists():
        return ()
    with DATA_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        records = []
        for row in reader:
            try:
                records.append(
                    GlacialLakeRecord(
                        lake_id=row["lake_id"],
                        lat=float(row["lat"]),
                        lon=float(row["lon"]),
                        area_km2=float(row["area_km2"]) if row.get("area_km2") else None,
                        elevation_m=float(row["elevation_m"]) if row.get("elevation_m") else None,
                        lake_type=row.get("lake_type", ""),
                        region=row.get("region", ""),
                    )
                )
            except (KeyError, ValueError):
                continue  # a malformed row is skipped, never guessed at
        return tuple(records)


def nearest_glacial_lake(lat: float, lon: float) -> GlacialLakeProximity:
    """Real nearest-neighbor search (linear scan — ~4,900 rows, well under a
    millisecond; no spatial index needed at this data volume) over the real
    lake inventory. Returns distance_km=None with an honest note if the
    data file isn't available or nothing is within MAX_RELEVANT_DISTANCE_KM
    — never a fabricated "no lakes nearby" claim dressed up as a real 0."""
    lakes = _load_lakes()
    if not lakes:
        return GlacialLakeProximity(
            distance_km=None,
            nearest_lake=None,
            note="Glacial lake inventory not available in this environment — run scripts/prepare_glacial_lake_data.py.",
        )

    best: tuple[float, GlacialLakeRecord] | None = None
    for lake in lakes:
        dist_km = haversine_meters(lat, lon, lake.lat, lake.lon) / 1000
        if best is None or dist_km < best[0]:
            best = (dist_km, lake)

    assert best is not None
    dist_km, lake = best

    if dist_km > MAX_RELEVANT_DISTANCE_KM:
        return GlacialLakeProximity(
            distance_km=round(dist_km, 2),
            nearest_lake=lake,
            note=(
                f"Nearest real, mapped glacial lake ({lake.lake_id}, {lake.region}) is "
                f"{dist_km:.1f} km away — beyond the {MAX_RELEVANT_DISTANCE_KM:.0f} km "
                "range this app treats as a meaningfully nearby GLOF concern."
            ),
        )

    area_note = f", ~{lake.area_km2:.3f} km²" if lake.area_km2 else ""
    elev_note = f" at {lake.elevation_m:.0f}m elevation" if lake.elevation_m else ""
    return GlacialLakeProximity(
        distance_km=round(dist_km, 2),
        nearest_lake=lake,
        note=(
            f"Nearest real, satellite-mapped glacial lake ({lake.region}, {lake.lake_type}{area_note}"
            f"{elev_note}) is {dist_km:.1f} km away (straight-line, not flow-path distance). "
            "Distance alone is not a validated GLOF hazard score — see app/services/"
            "glacial_lake_proximity.py's module docstring for why this is advisory context, "
            "not a weighted risk-engine input."
        ),
    )
