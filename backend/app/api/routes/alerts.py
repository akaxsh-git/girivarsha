import asyncio
import json
import queue

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.orm import Alert, HistoricalEvent, MicroCatchment, RiskPrediction, Village
from app.models.schemas import AlertOut, HistoricalEventOut
from app.services import alert_broadcaster

router = APIRouter(tags=["alerts"])

# How long the SSE generator waits for a real event before sending a
# heartbeat comment line instead — purely to keep intermediary proxies/load
# balancers from timing out an idle connection. Never counted as, or
# confused with, a real alert event by the frontend (heartbeats are SSE
# comment lines, `: ...`, not `data: ...` lines — EventSource never fires
# onmessage for a comment).
_HEARTBEAT_SECONDS = 15.0


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(region_id: int | None = None, db: Session = Depends(get_db)):
    """GET /alerts — currently active (unresolved) GREEN-and-above alerts,
    i.e. YELLOW/ORANGE/RED (a village with no open alert is implicitly
    GREEN — see app/services/alerts_engine.py for why GREEN never gets a
    row). Alerts are synced from the Phase 4 baseline risk engine whenever
    GET /risk/map or GET /risk/{id} runs — call one of those first if this
    looks stale; there's no background scheduler yet (that's Phase 8+).

    Optional `?region_id=` (server-side region filtering follow-up,
    user-requested) scopes this to alerts whose village belongs to one
    real region — same real Alert -> Village -> MicroCatchment -> Region
    join /sensors now uses too. Omitting it returns every open alert
    across every region, unchanged from before this filter existed."""
    query = select(Alert).where(Alert.resolved_at.is_(None))
    if region_id is not None:
        query = (
            query.join(Village, Alert.village_id == Village.id)
            .join(MicroCatchment, Village.catchment_id == MicroCatchment.id)
            .where(MicroCatchment.region_id == region_id)
        )
    alerts = db.scalars(query.order_by(Alert.issued_at.desc())).all()
    out = []
    for a in alerts:
        risk_score = None
        if a.risk_prediction_id is not None:
            pred = db.get(RiskPrediction, a.risk_prediction_id)
            risk_score = pred.risk_score if pred else None
        out.append(
            AlertOut(
                id=a.id,
                village_id=a.village_id,
                village_name=a.village.name if a.village else "unknown",
                level=a.level.value,
                message=a.message,
                risk_score=risk_score,
                issued_at=a.issued_at.isoformat(),
                resolved_at=a.resolved_at.isoformat() if a.resolved_at else None,
            )
        )
    return out


@router.get("/alerts/stream")
async def alerts_stream():
    """GET /alerts/stream — real-time push follow-up (user-requested): a
    Server-Sent-Events channel that emits one `data:` line the instant a
    real alert actually opens, escalates, or resolves (see
    app/services/alerts_engine.py's AlertTransition and
    app/services/alert_broadcaster.py), instead of requiring the dashboard
    to poll GET /alerts on an interval and notice the change late.

    Every event is a genuine transition produced by a real
    GET /risk/map or GET /risk/{id} call elsewhere in this app — this
    endpoint only relays them, it never invents or schedules one. Lines
    starting with `:` are heartbeats/comments (SSE spec), not alert data;
    EventSource on the frontend only fires its `onmessage` handler for real
    `data:` lines, so these are inert there by construction, not just by
    convention.

    Single-process, in-memory fan-out — see alert_broadcaster.py's module
    docstring for why, and for the real limitation that implies if this app
    is ever run as multiple worker processes."""

    async def event_generator():
        q = alert_broadcaster.subscribe()
        loop = asyncio.get_event_loop()
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = await loop.run_in_executor(None, q.get, True, _HEARTBEAT_SECONDS)
                except queue.Empty:
                    yield ": heartbeat\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            alert_broadcaster.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Disables response buffering on nginx-style reverse proxies —
            # without it, a proxy can hold every event until its own buffer
            # fills, defeating the entire point of "real-time" here.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/historical-events", response_model=list[HistoricalEventOut])
def list_historical_events(db: Session = Depends(get_db)):
    """GET /historical-events — real, citable past events (Phase 2). See
    scripts/seed_pilot_region.py for sourcing; every row carries a source_citation,
    never a fabricated one."""
    events = db.scalars(select(HistoricalEvent)).all()
    return [
        HistoricalEventOut(
            id=e.id,
            village_id=e.village_id,
            village_name=e.village.name if e.village_id and e.village else None,
            event_type=e.event_type.value,
            event_date=e.event_date,
            severity=e.severity,
            description=e.description,
            source_citation=e.source_citation,
        )
        for e in events
    ]
