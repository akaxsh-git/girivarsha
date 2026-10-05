"""
Phase 12: seeds real, sourced timeline entries for historical-event replay
(problem-statement item 19). Every entry here must be backed by a real
citation — there is no fabricated minute-by-minute reconstruction of a
real disaster in this script.

DATA HONESTY (see docs/Data_Sources.md, docs/Limitations.md):
  - The real historical record for BOTH events is genuinely sparse on exact
    clock times. Rather than invent a plausible-looking full timeline, each
    entry is tagged with `time_precision`:
      - 'exact_time'  — a specific clock time is stated in a cited source.
      - 'approximate' — a time is estimated FROM a cited source (e.g. "~18
        minutes before" a documented timestamp), not guessed from nothing.
      - 'date_only'   — only the day is documented; no time of day exists
        in any source found during this build.
  - 2013 Kedarnath has more documented granularity (multiple named days,
    one specific clock time from a survivor account) than 2021 Chamoli
    (essentially one well-documented clock time — 10:30 IST, from satellite
    imagery analysis — everything else in the geological literature is
    stated as elapsed duration, not clock time).
  - Village-by-village arrival times (Rambara, Gaurikund, Sonprayag,
    Rudraprayag; Reni, Tapovan, Vishnuprayag, Joshimath) were NOT found in
    any source consulted during this build — no entry claims one. This is
    a real gap in the public record, not an oversight in this seed script.

Run: cd backend && source .venv/bin/activate && python ../scripts/seed_event_timelines.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select

# All cited clock times in the sources below are reported in India Standard
# Time (UTC+5:30), not UTC — using this offset for the 'exact_time'/
# 'approximate' entries below (rather than tagging them UTC and silently
# shifting the real time by 5.5 hours) is what keeps `occurred_at` an
# honest, correct instant, not just a correct-looking string. 'date_only'
# entries below deliberately stay plain UTC-midnight instead: there is no
# real clock time to convert for those, and applying the IST offset to a
# midnight placeholder would shift the stored calendar DATE itself
# backward by a day under naive UTC-date display — worse, not better.
IST = timezone(timedelta(hours=5, minutes=30))

from app.models.database import session_scope
from app.models.orm import EventTimelineEntry, EventType, HistoricalEvent, Village

WIKI = "https://en.wikipedia.org/wiki/{}"
DTE = "https://www.downtoearth.org.in/natural-disasters/heavens-rage-41497"
DIALOGUE_EARTH = "https://dialogue.earth/en/climate/death-of-chorabari-lake/"
ICIMOD = (
    "https://www.icimod.org/article/understanding-the-chamoli-flood-cause-process-"
    "impacts-and-context-of-rapid-infrastructure-development/"
)

# (village_name, event_type) -> ordered real timeline entries
TIMELINES: dict[str, list[dict]] = {
    "Kedarnath": [
        dict(
            occurred_at=datetime(2013, 6, 13, tzinfo=timezone.utc),
            time_precision="date_only",
            headline="IMD issues first rainfall warning",
            description=(
                "The India Meteorological Department issues an initial warning of "
                "'rather heavy rainfall' for the Uttarakhand region."
            ),
            source_citation=f"{DTE} (fetched 2026-09-04).",
        ),
        dict(
            occurred_at=datetime(2013, 6, 14, tzinfo=timezone.utc),
            time_precision="date_only",
            headline="Continuous rainfall begins",
            description=(
                "Heavy rain begins falling across the Mandakini valley and does not let up — "
                "survivor accounts describe it as 'raining nonstop since June 14.'"
            ),
            source_citation=f"{DTE} (fetched 2026-09-04).",
        ),
        dict(
            occurred_at=datetime(2013, 6, 15, 9, 0, tzinfo=IST),
            time_precision="exact_time",
            headline="IMD upgrades to 'heavy rainfall' bulletin",
            description=(
                "IMD issues a 9 a.m. bulletin to state officials upgrading the forecast to "
                "'heavy rainfall,' naming five locations at risk including Kedarnath."
            ),
            source_citation=f"{DTE} (fetched 2026-09-04).",
        ),
        dict(
            occurred_at=datetime(2013, 6, 16, 19, 18, tzinfo=IST),
            time_precision="exact_time",
            headline="Disaster strikes near Kedarnath",
            description=(
                "At 7:18 PM, survivor Ram Singh — with 45 years in the valley — hears what he "
                "describes as the loudest crack of his life as the disaster begins to unfold."
            ),
            source_citation=f"{DTE} (fetched 2026-09-04) — survivor account.",
        ),
        dict(
            occurred_at=datetime(2013, 6, 17, tzinfo=timezone.utc),
            time_precision="date_only",
            headline="Chorabari Lake (Gandhi Sarovar) breaches",
            description=(
                "On the morning of June 17, the moraine-dammed Chorabari Lake above Kedarnath "
                "breaches its banks, emptying over 262 million litres of water in a matter of "
                "minutes and sending a catastrophic debris flow down the Mandakini valley."
            ),
            source_citation=f"{DIALOGUE_EARTH} (fetched 2026-09-04).",
        ),
        dict(
            occurred_at=datetime(2013, 6, 18, tzinfo=timezone.utc),
            time_precision="date_only",
            headline="Survivors begin fleeing downstream",
            description="Survivors, including Sushil Singh, flee downstream from Gaurikund toward Gaurigaon.",
            source_citation=f"{DTE} (fetched 2026-09-04) — survivor account.",
        ),
        dict(
            occurred_at=datetime(2013, 6, 19, tzinfo=timezone.utc),
            time_precision="date_only",
            headline="Army rescue operations begin",
            description="Indian Army rescue operations get underway; the Union Home Minister visits the region.",
            source_citation=f"{DTE} (fetched 2026-09-04).",
        ),
    ],
    "Reni": [
        dict(
            occurred_at=datetime(2021, 2, 7, 10, 12, tzinfo=IST),
            time_precision="approximate",
            headline="Rock-ice avalanche detaches near Ronti Peak",
            description=(
                "A ~27 million m3 rock-ice mass detaches from a hanging glacier near Ronti Peak "
                "in the Nanda Devi region. No direct-observation timestamp exists for the "
                "detachment itself; this time is estimated by working backward from the one "
                "precisely documented timestamp below (debris flow reaching Tapovan at 10:30 "
                "IST) using the ~18-minute travel time analysis in the cited source."
            ),
            source_citation=f"{ICIMOD} (fetched 2026-09-04) — satellite-imagery-based reconstruction.",
        ),
        dict(
            occurred_at=datetime(2021, 2, 7, 10, 30, tzinfo=IST),
            time_precision="exact_time",
            headline="Debris flow reaches Tapovan Hydropower Project",
            description=(
                "The debris flow reaches the Tapovan Vishnugad Hydropower Project intake site — "
                "the one precisely timestamped moment in the disaster's public documentation, "
                "identified from satellite imagery captured at 10:30 IST."
            ),
            source_citation=f"{ICIMOD} (fetched 2026-09-04) — satellite imagery timestamp.",
        ),
        dict(
            occurred_at=datetime(2021, 2, 7, tzinfo=timezone.utc),
            time_precision="date_only",
            headline="Rishiganga and Tapovan-Vishnugad hydropower projects destroyed",
            description=(
                "Both hydropower projects on the Rishiganga/Dhauliganga are destroyed by the "
                "debris flow / flash flood; roughly 200 people are killed, more than 140 of them "
                "workers at the Tapovan site."
            ),
            source_citation=f"{WIKI.format('2021_Uttarakhand_flood')} (fetched 2026-09-04).",
        ),
    ],
}


def main() -> None:
    with session_scope() as db:
        created, skipped = 0, 0
        for village_name, entries in TIMELINES.items():
            village = db.scalar(select(Village).where(Village.name == village_name))
            if village is None:
                print(f"Skipping '{village_name}' — no such village seeded yet.")
                continue

            event = db.scalar(
                select(HistoricalEvent).where(
                    HistoricalEvent.village_id == village.id,
                    HistoricalEvent.event_type == EventType.FLASH_FLOOD,
                )
            )
            if event is None:
                print(f"Skipping '{village_name}' — no historical event seeded for it yet.")
                continue

            existing_count = db.scalar(
                select(EventTimelineEntry).where(EventTimelineEntry.historical_event_id == event.id)
            )
            if existing_count is not None:
                print(f"Timeline for '{village_name}' already seeded — refusing to double-seed.")
                skipped += 1
                continue

            for i, e in enumerate(entries):
                db.add(
                    EventTimelineEntry(
                        historical_event_id=event.id,
                        sequence_order=i,
                        occurred_at=e["occurred_at"],
                        time_precision=e["time_precision"],
                        headline=e["headline"],
                        description=e["description"],
                        source_citation=e["source_citation"],
                    )
                )
            created += len(entries)

        print(f"Seeded {created} real timeline entries; {skipped} event(s) already had a timeline.")


if __name__ == "__main__":
    main()
