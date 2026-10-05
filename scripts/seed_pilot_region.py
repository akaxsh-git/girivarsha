"""
Seeds the Phase 2 pilot region: the Mandakini valley, Rudraprayag district,
Uttarakhand — the real Himalayan catchment behind the 16-17 June 2013
Kedarnath flash flood/debris-flow disaster (one of India's deadliest
flash-flood events, ~5,700 people declared dead/missing). This is a
deliberate, defensible pilot choice, not an arbitrary one: it is a real,
well-documented, extensively-researched hilly flash-flood catchment.

DATA HONESTY (see docs/Data_Sources.md):
  - Village names, real-world existence, river-order topology, and the
    listed elevations are REAL, sourced from Wikipedia articles fetched
    during this build (citations recorded per-row in `provenance`).
  - Kedarnath and Rudraprayag have SURVEYED-PRECISION coordinates (their
    Wikipedia infoboxes state them directly: 30.73N/79.07E and
    30.28N/78.98E respectively).
  - Rambara, Gaurikund, and Sonprayag do NOT have precise coordinates
    available through the tools this build had access to (no outbound
    access to OSM/Nominatim/Overpass from this sandbox — verified, see
    docs/Architecture.md). Their positions here are APPROXIMATED by
    interpolating along the real, documented river corridor between the
    two surveyed anchor points. `coordinate_precision` is set to
    'approximate' on every such row — never silently presented as
    surveyed. Replacing these with verified coordinates (OSM extract or
    Survey of India data) is explicitly flagged in docs/Limitations.md as
    Phase-2-followup work, not swept under the rug.

Run: cd backend && source .venv/bin/activate && python ../scripts/seed_pilot_region.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import text

from app.models.database import session_scope
from app.models.orm import DataSource, EventType, HistoricalEvent, MicroCatchment, Village

WIKI = "https://en.wikipedia.org/wiki/{}"

# Ordered strictly upstream -> downstream, matching the real Mandakini River
# path (source: en.wikipedia.org/wiki/Mandakini_River, fetched during this
# build): Chorabari Glacier -> Kedarnath -> Rambara -> Gaurikund -> Ukhimath
# area -> Sonprayag (confluence w/ Songanga) -> ... -> Rudraprayag
# (confluence w/ Alaknanda).
VILLAGES = [
    dict(
        name="Kedarnath",
        elevation_m=3583,
        lat=30.7346, lon=79.0669,
        coordinate_precision="surveyed",
        provenance=f"Elevation & coordinates: {WIKI.format('Kedarnath')} (fetched 2026-09-03).",
    ),
    dict(
        name="Rambara",
        elevation_m=2740,
        lat=30.716, lon=79.058,  # interpolated between Kedarnath and Gaurikund along the river corridor
        coordinate_precision="approximate",
        provenance=(
            f"Elevation: {WIKI.format('Mandakini_River')} (fetched 2026-09-03), "
            "which lists Rambara at 2,740m on the Kedarnath->Gaurikund river path. "
            "Historically almost entirely destroyed in the June 2013 flood. "
            "Coordinates interpolated along the documented river corridor — NOT surveyed."
        ),
    ),
    dict(
        name="Gaurikund",
        elevation_m=1982,  # 6502 ft per Wikipedia
        lat=30.674, lon=79.030,
        coordinate_precision="approximate",
        provenance=(
            f"Elevation (6502 ft = 1982m): {WIKI.format('Gaurikund')} (fetched 2026-09-03). "
            "Coordinates interpolated along the documented river corridor — NOT surveyed."
        ),
    ),
    dict(
        name="Sonprayag",
        elevation_m=1360,  # approximate — not directly sourced; between Gaurikund (1982m) and valley floor
        lat=30.617, lon=79.028,
        coordinate_precision="approximate",
        provenance=(
            f"{WIKI.format('Sonprayag')} (fetched 2026-09-03) confirms it sits on the Mandakini "
            "at the confluence with the Songanga River, ~73km from Rudraprayag by road. "
            "Elevation is an unsourced estimate (interpolated between Gaurikund and the valley "
            "floor) — flagged in docs/Limitations.md for replacement with a real source."
        ),
    ),
    dict(
        name="Ukhimath",
        elevation_m=1311,
        lat=30.530, lon=79.048,
        coordinate_precision="approximate",
        provenance=(
            f"Elevation: {WIKI.format('Ukhimath')} (fetched 2026-09-03). "
            "Coordinates interpolated along the documented river corridor — NOT surveyed. "
            "Note: some sources place Ukhimath on a side valley rather than directly on the "
            "Mandakini mainstem; treat this row's position as indicative pending GIS verification."
        ),
    ),
    dict(
        name="Rudraprayag",
        elevation_m=895,
        lat=30.28, lon=78.98,
        coordinate_precision="surveyed",
        provenance=(
            f"Elevation & coordinates: {WIKI.format('Rudraprayag')} (fetched 2026-09-03). "
            "Sits at the real confluence of the Mandakini and Alaknanda rivers — modelled here "
            "as the pilot catchment's outlet."
        ),
    ),
]

HISTORICAL_EVENTS = [
    dict(
        village_name="Kedarnath",
        event_type=EventType.FLASH_FLOOD,
        event_date=datetime(2013, 6, 16, tzinfo=timezone.utc),
        severity="catastrophic",
        description=(
            "Cloudburst-triggered glacial lake/moraine failure above Kedarnath caused a major "
            "flash flood and debris flow down the Mandakini valley on 16-17 June 2013, destroying "
            "Kedarnath township and Rambara and causing devastation as far downstream as "
            "Rudraprayag. Widely regarded as one of India's deadliest flash-flood disasters."
        ),
        source_citation=(
            "Mandakini River, Kedarnath, Rudraprayag (Wikipedia, fetched 2026-09-03); "
            "'A Tragic Flash Flood in Kedarnath Valley' (ResearchGate); "
            "Down To Earth, 'Remembering 2013 Uttarakhand Floods'."
        ),
    ),
]


def interpolated_point(lat: float, lon: float):
    return from_shape(Point(lon, lat), srid=4326)


def main() -> None:
    with session_scope() as db:
        existing = db.execute(text("SELECT count(*) FROM villages")).scalar()
        if existing:
            print(f"villages table already has {existing} row(s) — refusing to double-seed. "
                  f"Truncate manually first if you want to reseed.")
            return

        catchment = MicroCatchment(
            name="Mandakini Valley (Kedarnath -> Rudraprayag)",
            watershed_name="Alaknanda basin",
            river_name="Mandakini",
            source=DataSource.DERIVED,
            provenance=(
                "Topology (upstream/downstream order) derived from "
                f"{WIKI.format('Mandakini_River')} (fetched 2026-09-03). Polygon geometry not "
                "yet delineated — real DEM-based catchment boundaries are Phase 3 GIS work."
            ),
        )
        db.add(catchment)
        db.flush()

        village_rows: dict[str, Village] = {}
        for v in VILLAGES:
            row = Village(
                name=v["name"],
                district="Rudraprayag",
                state="Uttarakhand",
                elevation_m=v["elevation_m"],
                catchment_id=catchment.id,
                location=interpolated_point(v["lat"], v["lon"]),
                coordinate_precision=v["coordinate_precision"],
                source=DataSource.REAL,
                provenance=v["provenance"],
            )
            db.add(row)
            village_rows[v["name"]] = row
        db.flush()

        for e in HISTORICAL_EVENTS:
            db.add(HistoricalEvent(
                village_id=village_rows[e["village_name"]].id,
                catchment_id=catchment.id,
                event_type=e["event_type"],
                event_date=e["event_date"],
                severity=e["severity"],
                description=e["description"],
                source_citation=e["source_citation"],
            ))

        print(f"Seeded 1 catchment, {len(VILLAGES)} villages, {len(HISTORICAL_EVENTS)} historical event(s).")


if __name__ == "__main__":
    main()
