"""
Takes the three previously 'planned' regions to 'active' with real,
cited village-level data (docs/Region_Onboarding.md, Step 2):

  1. South Lhonak / Teesta Valley (Sikkim)      — 4 Oct 2023 GLOF
  2. Jhelum Basin / Kashmir Valley (J&K)        — Sept 2014 floods
  3. Beas River Basin (Kullu-Manali) (H.P.)     — July 2023 floods

Every coordinate and elevation below comes from the place's English
Wikipedia article (infobox, or article text where stated), fetched
2026-10-06. Villages whose elevation could not be sourced were LEFT OUT
rather than guessed (Dikchu, Bhuntar, Sopore). Population is left null, as
for the existing valleys.

Known limitations, stated rather than hidden:
  - Mangan and Naggar are hillside/ridge towns; their elevations are the
    town's, not the river's at that point (same caveat as Joshimath).
  - Bijbehara's infobox coordinate is given only to 0.1 degree (~5 km), so
    it is tagged 'approximate', not 'surveyed'.
  - The Kashmir Valley floor is nearly flat (~1,570-1,600 m for 100+ km),
    so recorded town elevations do not decrease monotonically downstream.
    The app orders villages upstream->downstream by elevation, so Pampore
    (1,573 m, upstream of Srinagar at 1,585 m) and Baramulla (1,593 m,
    downstream) were left out: including them would make that proxy put
    Baramulla upstream of Srinagar. This is a real weakness of the
    elevation-order proxy on valley floors, documented in
    docs/Data_Sources.md, not something the data was edited to hide.

Idempotent: a catchment that already exists is skipped.

Run: cd backend && source .venv/bin/activate && python ../scripts/seed_new_regions.py
     then: python ../scripts/seed_regions.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select

from app.models.database import session_scope
from app.models.orm import DataSource, EventType, HistoricalEvent, MicroCatchment, Village

WIKI = "https://en.wikipedia.org/wiki/{}"
FETCHED = "fetched 2026-10-06"


def _src(page: str, extra: str = "") -> str:
    base = f"Elevation & coordinates: {WIKI.format(page)} infobox ({FETCHED})."
    return f"{base} {extra}".strip()


CATCHMENTS = [
    dict(
        name="Lachen Chu-Teesta Valley (Lachen -> Rangpo)",
        watershed_name="Teesta basin",
        river_name="Teesta",
        provenance=(
            "Topology: the Teesta flows past Chungthang, Mangan and Singtam to Rangpo "
            f"({WIKI.format('Teesta_River')}); Lachen lies upstream of Chungthang on the Lachen river, the route "
            f"the 2023 South Lhonak flood took to the Teesta III dam ({WIKI.format('2023_Sikkim_flash_floods')}) "
            f"({FETCHED}). "
            "Polygon geometry not delineated."
        ),
        state="Sikkim",
        villages=[
            dict(name="Lachen", district="Mangan", elevation_m=2600, lat=27.71668, lon=88.557755,
                 precision="surveyed", provenance=_src("Lachen,_Sikkim", "Upstream of Chungthang on the Lachen river. KNOWN DATA CONFLICT: the "
                                 "same article's text says 'about 9,600 feet (2,900 meters)' and places it near the "
                                 "Lachen-Lachung confluence (which is Chungthang); the infobox value (2,600 m) is used. "
                                 "Either way it is the highest village in this valley, so the ordering is unaffected.")),
            dict(name="Chungthang", district="Mangan", elevation_m=1790, lat=27.6045, lon=88.645583,
                 precision="surveyed",
                 provenance=_src("Chungthang", "Confluence of the Lachen Chu and Lachung Chu; site of the Teesta III "
                                 "dam destroyed by the 2023 GLOF.")),
            dict(name="Mangan", district="Mangan", elevation_m=956, lat=27.52, lon=88.53,
                 precision="surveyed",
                 provenance=_src("Mangan,_India", "Infobox coordinate given to 0.01 degree (~1 km). KNOWN LIMITATION: "
                                 "Mangan sits on a ridge above the Teesta, so this is the town's elevation, not the "
                                 "river's at this point.")),
            dict(name="Singtam", district="Gangtok", elevation_m=426, lat=27.2331, lon=88.4961,
                 precision="surveyed",
                 provenance=_src("Singtam", "Elevation stated as 1,396 ft (426 m); on the Teesta at its confluence "
                                 "with the Rani Khola. Heavily damaged in 2023.")),
            dict(name="Rangpo", district="Pakyong", elevation_m=333, lat=27.175, lon=88.53,
                 precision="surveyed",
                 provenance=_src("Rangpo", "Infobox coordinate given to 0.005 degree. On the Teesta at the "
                                 "Sikkim-West Bengal border; heavily damaged in 2023.")),
        ],
        events=[
            dict(village_name="Chungthang", event_type=EventType.FLASH_FLOOD,
                 event_date=datetime(2023, 10, 4, tzinfo=timezone.utc), severity="catastrophic",
                 description=(
                     "On 4 October 2023 heavy rain caused moraine-dammed South Lhonak Lake to breach, a glacial lake "
                     "outburst flood. It reached the Teesta III dam at Chungthang around midnight and destroyed it "
                     "within minutes; Teesta water levels downstream rose 15-20 ft. Fifteen bridges were washed away, "
                     "Chungthang, Dikchu, Singtam and Rangpo were very heavily damaged, and at least 92 people were "
                     "confirmed dead by 18 October."
                 ),
                 source_citation=f"{WIKI.format('2023_Sikkim_flash_floods')} ({FETCHED})."),
        ],
    ),
    dict(
        name="Upper Jhelum Valley (Verinag -> Srinagar)",
        watershed_name="Jhelum basin",
        river_name="Jhelum",
        provenance=(
            "Topology: the Jhelum rises at Verinag spring in the south-east of the Kashmir Valley, is joined by "
            "tributaries at Sangam in Anantnag district, and flows north-west past Bijbehara to Srinagar — "
            f"{WIKI.format('Jhelum_River')} ({FETCHED}). Pampore and Baramulla were deliberately left "
            "out because their recorded elevations break the app's elevation-order upstream proxy on this flat "
            "valley floor (see scripts/seed_new_regions.py). Polygon geometry not delineated."
        ),
        state="Jammu and Kashmir",
        villages=[
            dict(name="Verinag", district="Anantnag", elevation_m=1851, lat=33.55, lon=75.25,
                 precision="surveyed",
                 provenance=_src("Verinag", "Infobox coordinate given to 0.01 degree (~1 km). Spring source of the "
                                 "Jhelum.")),
            dict(name="Anantnag", district="Anantnag", elevation_m=1601, lat=33.73527778, lon=75.14777778,
                 precision="surveyed",
                 provenance=_src("Anantnag", "In 2014 the Jhelum ran 33 ft above the danger mark at nearby Sangam.")),
            dict(name="Bijbehara", district="Anantnag", elevation_m=1591, lat=33.8, lon=75.1,
                 precision="approximate",
                 provenance=_src("Bijbehara", "Infobox coordinate is given only to 0.1 degree (~5 km), so it is "
                                 "tagged approximate rather than surveyed.")),
            dict(name="Srinagar", district="Srinagar", elevation_m=1585, lat=34.09, lon=74.79,
                 precision="surveyed",
                 provenance=_src("Srinagar", "Infobox coordinate given to 0.01 degree (~1 km); a city, so this is a "
                                 "single representative point.")),
        ],
        events=[
            dict(village_name="Srinagar", event_type=EventType.OTHER,
                 event_date=datetime(2014, 9, 5, tzinfo=timezone.utc), severity="catastrophic",
                 description=(
                     "Riverine monsoon flood (not a flash flood): torrential rain from 2 September 2014 drove the "
                     "Jhelum to 22.4 ft at Srinagar on 5 September, 4.4 ft above the danger mark, with discharge of "
                     "about 70,000 cusecs against a normal 25,000. Water stood about 12 ft deep in parts of Srinagar "
                     "on 8 September; around 2,600 villages in Jammu and Kashmir were affected, 390 completely "
                     "submerged, and about 277 people died in India."
                 ),
                 source_citation=f"{WIKI.format('2014_India%E2%80%93Pakistan_floods')} ({FETCHED})."),
        ],
    ),
    dict(
        name="Upper Beas Valley (Manali -> Mandi)",
        watershed_name="Beas basin",
        river_name="Beas",
        provenance=(
            "Topology: the Beas rises near Rohtang Pass and forms the Kullu Valley, with Manali at its northern end, "
            "Naggar on its left bank and Kullu on its banks further south; it then enters Mandi district, where "
            f"Mandi stands on it — {WIKI.format('Beas_River')} and each town's article ({FETCHED}). Bhuntar was left out (no sourced "
            "elevation). Polygon geometry not delineated."
        ),
        state="Himachal Pradesh",
        villages=[
            dict(name="Manali", district="Kullu", elevation_m=2050, lat=32.243177, lon=77.189246,
                 precision="surveyed",
                 provenance=_src("Manali,_Himachal_Pradesh", "Roads were swept away here in the July 2023 floods.")),
            dict(name="Naggar", district="Kullu", elevation_m=1800, lat=32.12, lon=77.17,
                 precision="surveyed",
                 provenance=_src("Naggar,_Himachal_Pradesh", "Infobox coordinate given to 0.01 degree (~1 km). "
                                 "KNOWN LIMITATION: Naggar is on the hillside above the Beas's left bank, so this is "
                                 "the town's elevation, not the river's.")),
            dict(name="Kullu", district="Kullu", elevation_m=1279, lat=31.95, lon=77.11,
                 precision="surveyed",
                 provenance=_src("Kullu", "Infobox coordinate given to 0.01 degree (~1 km).")),
            dict(name="Mandi", district="Mandi", elevation_m=760, lat=31.70694444, lon=76.93166667,
                 precision="surveyed", provenance=_src("Mandi,_Himachal_Pradesh", "On the Beas below Pandoh.")),
        ],
        events=[
            dict(village_name="Manali", event_type=EventType.FLASH_FLOOD,
                 event_date=datetime(2023, 7, 9, tzinfo=timezone.utc), severity="severe",
                 description=(
                     "Part of the 2023 North India monsoon floods: in July 2023 intense rain over a two-week period "
                     "caused flash flooding and landslides across Himachal Pradesh, the hardest-hit state. In Manali, "
                     "roads were swept away and tourists and vehicles were stranded; about 70,000 tourists were "
                     "evacuated from the state. Himachal recorded at least 330 deaths across the 2023 monsoon."
                 ),
                 source_citation=f"{WIKI.format('2023_North_India_floods')} ({FETCHED})."),
        ],
    ),
]


def main() -> None:
    with session_scope() as db:
        for c in CATCHMENTS:
            if db.scalar(select(MicroCatchment).where(MicroCatchment.name == c["name"])) is not None:
                print(f"'{c['name']}' already seeded — skipping.")
                continue
            catchment = MicroCatchment(
                name=c["name"],
                watershed_name=c["watershed_name"],
                river_name=c["river_name"],
                source=DataSource.DERIVED,
                provenance=c["provenance"],
            )
            db.add(catchment)
            db.flush()
            rows: dict[str, Village] = {}
            for v in c["villages"]:
                row = Village(
                    name=v["name"],
                    district=v["district"],
                    state=c["state"],
                    elevation_m=v["elevation_m"],
                    catchment_id=catchment.id,
                    location=from_shape(Point(v["lon"], v["lat"]), srid=4326),
                    coordinate_precision=v["precision"],
                    source=DataSource.REAL,
                    provenance=v["provenance"],
                )
                db.add(row)
                rows[v["name"]] = row
            db.flush()
            for e in c["events"]:
                db.add(HistoricalEvent(
                    village_id=rows[e["village_name"]].id,
                    catchment_id=catchment.id,
                    event_type=e["event_type"],
                    event_date=e["event_date"],
                    severity=e["severity"],
                    description=e["description"],
                    source_citation=e["source_citation"],
                ))
            print(f"Seeded '{c['name']}': {len(c['villages'])} villages, {len(c['events'])} event(s).")
    print("Now run scripts/seed_regions.py to mark the regions active and link these catchments.")


if __name__ == "__main__":
    main()
