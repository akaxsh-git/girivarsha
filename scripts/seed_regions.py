"""
Phase 11: seeds the Region registry (problem-statement-adjacent scaling
work — see docs/Region_Onboarding.md). This is the architecture that lets
Girivarsha hold MULTIPLE genuinely-sourced pilot valleys at once, instead
of a single valley hard-coded through the schema/API/frontend.

DATA HONESTY: every region row here is a REAL, named, documented place —
never an invented placeholder. Two statuses:
  - 'active'  — real village-level data already exists in this database
    for it (seeded by scripts/seed_pilot_region.py and
    scripts/seed_chamoli_valley.py).
  - 'planned' — a real, well-documented flash-flood/landslide-prone valley
    (with a real, cited disaster in its history) that has NOT been sourced
    to village level yet. Listing it here proves the data model scales to
    it; it does NOT claim village-level coverage that doesn't exist. See
    docs/Region_Onboarding.md for exactly what sourcing a 'planned' region
    up to 'active' requires.

This script only creates/updates Region rows and links existing catchments
to their region — it never fabricates villages. Run AFTER
seed_pilot_region.py (and seed_chamoli_valley.py, once run) so the
'active' regions can be linked to their real catchments.

Run: cd backend && source .venv/bin/activate && python ../scripts/seed_regions.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select

from app.models.database import session_scope
from app.models.orm import DataSource, MicroCatchment, Region

WIKI = "https://en.wikipedia.org/wiki/{}"

# name -> (states, description, status, catchment_name_to_link, provenance)
REGIONS = [
    dict(
        name="Mandakini Valley",
        states="Uttarakhand",
        description=(
            "Rudraprayag district — the real catchment of the 16-17 June 2013 Kedarnath flash "
            "flood/debris-flow disaster, one of India's deadliest such events."
        ),
        status="active",
        catchment_name="Mandakini Valley (Kedarnath -> Rudraprayag)",
        provenance=f"See docs/Data_Sources.md and {WIKI.format('Mandakini_River')}.",
    ),
    dict(
        name="Chamoli Disaster Valley",
        states="Uttarakhand",
        description=(
            "Chamoli district — the Rishiganga/Dhauliganga corridor to the Alaknanda at "
            "Vishnuprayag/Joshimath, site of the real 7 February 2021 rock-ice-avalanche-triggered "
            "flash flood that killed roughly 200 people and destroyed two hydropower projects."
        ),
        status="active",
        catchment_name="Rishiganga-Dhauliganga Valley (Reni -> Vishnuprayag)",
        provenance=f"See docs/Data_Sources.md and {WIKI.format('2021_Uttarakhand_flood')}.",
    ),
    dict(
        name="South Lhonak / Teesta Valley",
        states="Sikkim",
        description=(
            "The Teesta river valley below South Lhonak Lake — site of the real 3-4 October 2023 "
            "glacial lake outburst flood (GLOF), triggered by a landslide/moraine collapse into the "
            "lake, which killed 90+ people and destroyed the Teesta III dam."
        ),
        status="planned",
        catchment_name=None,
        provenance=f"{WIKI.format('2023_Sikkim_flash_floods')} (fetched 2026-09-04). No village-level data sourced yet — see docs/Region_Onboarding.md.",
    ),
    dict(
        name="Jhelum Basin / Kashmir Valley",
        states="Jammu and Kashmir",
        description=(
            "The Jhelum river basin through the Kashmir Valley — site of the real September 2014 "
            "Jammu and Kashmir floods, in which torrential monsoon rainfall caused catastrophic "
            "flooding that killed 277 people in J&K and submerged large parts of Srinagar."
        ),
        status="planned",
        catchment_name=None,
        provenance=f"{WIKI.format('2014_India%E2%80%93Pakistan_floods')} (fetched 2026-09-04). No village-level data sourced yet — see docs/Region_Onboarding.md.",
    ),
    dict(
        name="Beas River Basin (Kullu-Manali)",
        states="Himachal Pradesh",
        description=(
            "The Beas river basin through Kullu and Manali — site of real, severe monsoon flash "
            "flooding beginning 8-9 July 2023 (part of the wider 2023 North India floods), which "
            "destroyed roads, bridges, and property along the Kullu-Manali-Leh highway."
        ),
        status="planned",
        catchment_name=None,
        provenance=f"{WIKI.format('2023_North_India_floods')} (fetched 2026-09-04). No village-level data sourced yet — see docs/Region_Onboarding.md.",
    ),
]


def main() -> None:
    with session_scope() as db:
        created, linked, skipped = 0, 0, 0
        for r in REGIONS:
            existing = db.scalar(select(Region).where(Region.name == r["name"]))
            if existing is None:
                existing = Region(
                    name=r["name"],
                    states=r["states"],
                    description=r["description"],
                    status=r["status"],
                    source=DataSource.DERIVED,
                    provenance=r["provenance"],
                )
                db.add(existing)
                db.flush()
                created += 1
            else:
                skipped += 1

            if r["catchment_name"] is not None:
                catchment = db.scalar(select(MicroCatchment).where(MicroCatchment.name == r["catchment_name"]))
                if catchment is not None and catchment.region_id is None:
                    catchment.region_id = existing.id
                    linked += 1

        print(f"Regions: {created} created, {skipped} already existed, {linked} catchment(s) linked.")


if __name__ == "__main__":
    main()
