from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.database import get_db
from app.models.orm import HistoricalEvent
from app.models.schemas import ReplayEventOut, ReplayEventSummaryOut, TimelineEntryOut

router = APIRouter(prefix="/replay", tags=["replay"])


@router.get("/events", response_model=list[ReplayEventSummaryOut])
def list_replayable_events(db: Session = Depends(get_db)):
    """GET /replay/events — real historical events with at least one real,
    sourced timeline entry to replay (see scripts/seed_event_timelines.py).
    An event with zero timeline entries seeded still exists in
    GET /historical-events, but is omitted here rather than offered as an
    empty 'replay.'"""
    events = db.scalars(
        select(HistoricalEvent).options(selectinload(HistoricalEvent.timeline_entries))
    ).all()
    return [
        ReplayEventSummaryOut(
            event_id=e.id,
            village_id=e.village_id,
            village_name=e.village.name if e.village_id and e.village else None,
            event_type=e.event_type.value,
            event_date=e.event_date.isoformat(),
            severity=e.severity,
            entry_count=len(e.timeline_entries),
        )
        for e in events
        if e.timeline_entries
    ]


@router.get("/{event_id}", response_model=ReplayEventOut)
def replay_event(event_id: int, db: Session = Depends(get_db)):
    """GET /replay/{event_id} — the real, ordered, sourced timeline for one
    historical event (problem-statement item 19). Every entry carries a
    `time_precision` tag ('exact_time' | 'approximate' | 'date_only') and a
    real `source_citation` — see app/models/orm.py::EventTimelineEntry and
    scripts/seed_event_timelines.py for why there is deliberately no
    simulated-scenario fallback here: a fabricated timeline of a real
    disaster would misrepresent it. `404` if the event has no seeded
    timeline (not the same as the event not existing at all — see
    GET /historical-events for the full event list regardless of replay
    availability)."""
    event = db.scalar(
        select(HistoricalEvent)
        .options(selectinload(HistoricalEvent.timeline_entries))
        .where(HistoricalEvent.id == event_id)
    )
    if event is None:
        raise HTTPException(status_code=404, detail=f"No historical event with id={event_id}")
    if not event.timeline_entries:
        raise HTTPException(
            status_code=404,
            detail=f"No replay timeline seeded for event id={event_id} yet — see GET /historical-events for the underlying event record.",
        )

    return ReplayEventOut(
        event_id=event.id,
        village_id=event.village_id,
        village_name=event.village.name if event.village_id and event.village else None,
        event_type=event.event_type.value,
        event_date=event.event_date.isoformat(),
        severity=event.severity,
        description=event.description,
        source_citation=event.source_citation,
        timeline=[
            TimelineEntryOut(
                sequence_order=t.sequence_order,
                # Real bug fixed here (found via the SCS-CN integration pass):
                # relying on the DB session's default timezone to already be
                # UTC before calling .isoformat() only works when Postgres's
                # own `timezone` setting happens to be UTC. On a machine
                # whose Postgres defaults to the local system timezone (e.g.
                # IST), the exact same absolute instant would serialize with
                # a "+05:30" offset instead of "+00:00" — the real historical
                # moment is unchanged, but callers hardcoding a UTC-offset
                # comparison (this project's own test suite included) would
                # see a different string for an identical instant. Explicit
                # `.astimezone(timezone.utc)` makes the wire format
                # environment-independent, matching every other real-time
                # field this app returns.
                occurred_at=t.occurred_at.astimezone(timezone.utc).isoformat() if t.occurred_at else None,
                time_precision=t.time_precision,
                headline=t.headline,
                description=t.description,
                source_citation=t.source_citation,
            )
            for t in event.timeline_entries
        ],
    )
