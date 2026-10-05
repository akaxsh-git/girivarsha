"""
Phase 11: seeds a SECOND real, fully-sourced pilot valley — the Chamoli
disaster valley (Rishiganga/Dhauliganga rivers -> Alaknanda at
Vishnuprayag/Joshimath), Chamoli district, Uttarakhand. Real site of the
7 February 2021 flash flood: a ~27 million m3 rock-ice avalanche detached
from a hanging glacier near Ronti Peak (Nanda Devi region), ran down Ronti
Gad into the Rishiganga, then the Dhauliganga, destroying the Rishiganga
and Tapovan-Vishnugad hydropower projects and killing roughly 200 people.

This exists to prove the region-registry architecture (scripts/seed_regions.py)
actually generalizes — a genuinely different, independently-sourced valley,
not a copy-pasted second Mandakini.

DATA HONESTY (see docs/Data_Sources.md):
  - All 4 villages/settlements below have SURVEYED-PRECISION coordinates —
    every one is backed by either a Wikipedia infobox or a peer-reviewed
    engineering reconnaissance report (cited per-row in `provenance`).
    This valley is actually better-sourced on coordinates than Mandakini
    (which had 4-of-6 villages at 'approximate' precision).
  - Population figures are NOT included (left null) — no figure for these
    specific settlements could be verified through the sources available
    during this build; better to leave it honestly unset than guess.
  - KNOWN LIMITATION, stated explicitly rather than hidden: Joshimath's
    Wikipedia elevation (1,875m) reflects the TOWN's position on a terrace
    above the river, not the river's true elevation at the Vishnuprayag
    confluence immediately upstream of it (1,372m) — so this valley is a
    concrete, real example of why the app's elevation-order upstream/
    downstream proxy (documented in app/services/risk_engine.py and
    app/services/lead_time.py) is a simplification, not real hydrological
    routing. Joshimath's `provenance` field flags this explicitly.

Run: cd backend && source .venv/bin/activate && python ../scripts/seed_chamoli_valley.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select
from sqlalchemy import text

from app.models.database import session_scope
from app.models.orm import DataSource, EventType, HistoricalEvent, MicroCatchment, Village

WIKI = "https://en.wikipedia.org/wiki/{}"
CATCHMENT_NAME = "Rishiganga-Dhauliganga Valley (Reni -> Vishnuprayag)"

# Ordered strictly upstream -> downstream, matching the real, verified river
# topology: Rishiganga (from near Reni) joins the Dhauliganga at Reni, which
# flows past Tapovan and terminates at Vishnuprayag, joining the Alaknanda
# right next to Joshimath. See module docstring re: Joshimath's elevation caveat.
VILLAGES = [
    dict(
        name="Reni",
        elevation_m=1973,
        lat=30.48555, lon=79.69432,  # 30°29'7.95"N, 79°41'39.56"E
        coordinate_precision="surveyed",
        provenance=(
            "Elevation & coordinates: GEER Association Chamoli disaster reconnaissance report "
            "(https://geerassociation.org/components/com_geer_reports/geerfiles/Chamoli_Report.pdf), "
            "a peer-reviewed engineering survey — Wikipedia's own 'Rini, Uttarakhand' article has no "
            "infobox coordinates, so this authoritative survey source was used instead (fetched 2026-09-04). "
            "Also known as 'Raini' — site of the 1974 Chipko Andolan (Gaura Devi) and the Rishiganga "
            "Hydropower Project destroyed in the 2021 disaster."
        ),
    ),
    dict(
        name="Tapovan",
        elevation_m=1787,
        lat=30.49414, lon=79.62753,  # 30°29'38.9"N, 79°37'39.1"E (intake sill)
        coordinate_precision="surveyed",
        provenance=(
            f"Elevation & coordinates (intake sill): {WIKI.format('Tapovan_Vishnugad_Hydropower_Plant')} "
            "(fetched 2026-09-04). Site of the Tapovan-Vishnugad Hydropower Plant on the Dhauliganga, "
            "destroyed in the 7 February 2021 disaster with 140 workers killed/missing."
        ),
    ),
    dict(
        name="Vishnuprayag",
        elevation_m=1372,
        lat=30.5625, lon=79.57528,
        coordinate_precision="surveyed",
        provenance=(
            f"Elevation & coordinates: {WIKI.format('Vishnuprayag')} (fetched 2026-09-04). Real "
            "confluence point of the Dhauliganga and Alaknanda rivers — first of the five Panch "
            "Prayag — modelled here as this catchment's outlet."
        ),
    ),
    dict(
        name="Joshimath",
        elevation_m=1875,
        lat=30.555, lon=79.565,
        coordinate_precision="surveyed",
        provenance=(
            f"Elevation & coordinates: {WIKI.format('Joshimath')} (fetched 2026-09-04). Major town "
            "immediately downstream of the Vishnuprayag confluence on the Alaknanda; gateway to "
            "Badrinath, now also known for 2023 land subsidence. "
            "KNOWN LIMITATION, stated explicitly: this elevation (1,875m) is the TOWN's position on a "
            "terrace above the river, not the river's true elevation at the adjacent Vishnuprayag "
            "confluence (1,372m) — so this row's elevation is HIGHER than the actually-downstream "
            "Vishnuprayag despite Joshimath being the real river's next point past that confluence. "
            "This is a concrete, real example of why the app's elevation-order upstream/downstream "
            "proxy (see app/services/risk_engine.py) is a simplification, not real hydrological "
            "routing — surfaced here rather than silently reordered to look cleaner."
        ),
    ),
]

HISTORICAL_EVENTS = [
    dict(
        village_name="Reni",
        event_type=EventType.FLASH_FLOOD,
        event_date=datetime(2021, 2, 7, tzinfo=timezone.utc),
        severity="catastrophic",
        description=(
            "A ~27 million m3 rock-ice avalanche (roughly 80% rock, 20% glacier ice) detached from a "
            "hanging glacier near Ronti Peak (6,029-6,063m) in the Nanda Devi region on 7 February "
            "2021, running down Ronti Gad into the Rishiganga, then the Dhauliganga, as a "
            "catastrophic debris flow/flash flood. It destroyed the Rishiganga Hydropower Project "
            "near Reni and the Tapovan-Vishnugad Hydropower Plant, killing roughly 200 people "
            "(over 140 of them workers at Tapovan)."
        ),
        source_citation=(
            f"{WIKI.format('2021_Uttarakhand_flood')} (fetched 2026-09-04); "
            "ESA, 'Satellites reveal cause of Chamoli disaster' "
            "(https://www.esa.int/Applications/Observing_the_Earth/Satellites_reveal_cause_of_Chamoli_disaster); "
            "GEER Association Chamoli reconnaissance report."
        ),
    ),
]


def interpolated_point(lat: float, lon: float):
    return from_shape(Point(lon, lat), srid=4326)


def main() -> None:
    with session_scope() as db:
        existing = db.scalar(select(MicroCatchment).where(MicroCatchment.name == CATCHMENT_NAME))
        if existing is not None:
            print(f"Catchment '{CATCHMENT_NAME}' already seeded — refusing to double-seed. "
                  f"Delete it manually first if you want to reseed.")
            return

        catchment = MicroCatchment(
            name=CATCHMENT_NAME,
            watershed_name="Alaknanda basin",
            river_name="Dhauliganga",
            source=DataSource.DERIVED,
            provenance=(
                "Topology (Rishiganga -> Dhauliganga -> Alaknanda confluence at Vishnuprayag) "
                f"derived from {WIKI.format('Dhauliganga_River')} and {WIKI.format('Rishiganga')} "
                "(fetched 2026-09-04). Polygon geometry not yet delineated — see docs/GIS_Methodology.md "
                "(same real-DEM-delineation path used for Mandakini Valley could be re-run against "
                "this valley's real coordinates)."
            ),
        )
        db.add(catchment)
        db.flush()

        village_rows: dict[str, Village] = {}
        for v in VILLAGES:
            row = Village(
                name=v["name"],
                district="Chamoli",
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

        print(f"Seeded 1 catchment, {len(VILLAGES)} villages, {len(HISTORICAL_EVENTS)} historical event(s) "
              f"for the Chamoli disaster valley. Run scripts/seed_regions.py next to link it into the region registry.")


if __name__ == "__main__":
    main()
