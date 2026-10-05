from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.database import get_db
from app.models.orm import MicroCatchment, Village
from app.models.schemas import EvacuationHopOut, EvacuationPriorityEntryOut, EvacuationRouteOut
from app.services.evacuation import evacuation_priority, evacuation_route
from app.services.risk_engine import compute_risk_for_village

router = APIRouter(prefix="/evacuation", tags=["evacuation"])


@router.get("/route/{village_id}", response_model=EvacuationRouteOut)
def get_evacuation_route(village_id: int, db: Session = Depends(get_db)):
    """GET /evacuation/route/{id} — Phase 12 prototype shortest-path route
    to this village's catchment's real, lowest-elevation seeded settlement
    (its modelled evacuation destination). See app/services/evacuation.py's
    module docstring for exactly what's real (topology, distances, live
    risk levels) vs. a stated simplification — no real road network exists
    in this build, so this is NOT turn-by-turn road routing."""
    settings = get_settings()
    village = db.get(Village, village_id)
    if village is None:
        raise HTTPException(status_code=404, detail=f"No village with id={village_id}")
    if village.catchment_id is None:
        raise HTTPException(status_code=422, detail=f"{village.name} has no assigned micro-catchment")

    siblings = db.scalars(select(Village).where(Village.catchment_id == village.catchment_id)).all()

    risk_levels = {}
    for v in siblings:
        assessment = compute_risk_for_village(v, db, settings=settings, all_villages_in_catchment=siblings)
        risk_levels[v.id] = assessment.level

    route = evacuation_route(village, siblings, risk_levels)

    return EvacuationRouteOut(
        origin_village_id=route.origin_village_id,
        origin_village_name=route.origin_village_name,
        destination_village_id=route.destination_village_id,
        destination_village_name=route.destination_village_name,
        hops=[EvacuationHopOut(**h.__dict__) for h in route.hops],
        total_distance_km=route.total_distance_km,
        estimated_minutes=route.estimated_minutes,
        note=route.note,
    )


@router.get("/routes", response_model=list[EvacuationRouteOut])
def get_all_evacuation_routes(region_id: int | None = None, db: Session = Depends(get_db)):
    """GET /evacuation/routes — user-requested follow-up: every seeded
    village's own evacuation route in one call, rather than requiring an
    authority user to look them up one village at a time via
    GET /evacuation/route/{id} (which this reuses internally — same
    computation, same honesty framing, nothing duplicated). A village with
    no assigned micro-catchment is skipped (not a fabricated empty route),
    matching that endpoint's own 422 for the single-village case. Optional
    `?region_id=` scopes to one region, same convention as /risk/map and
    /evacuation/priority."""
    settings = get_settings()
    query = select(Village)
    if region_id is not None:
        query = query.join(MicroCatchment, Village.catchment_id == MicroCatchment.id).where(
            MicroCatchment.region_id == region_id
        )
    villages = db.scalars(query).all()

    risk_levels = {}
    for v in villages:
        siblings = [s for s in villages if s.catchment_id == v.catchment_id] if v.catchment_id else [v]
        assessment = compute_risk_for_village(v, db, settings=settings, all_villages_in_catchment=siblings)
        risk_levels[v.id] = assessment.level

    out = []
    for v in villages:
        if v.catchment_id is None:
            continue
        siblings = [s for s in villages if s.catchment_id == v.catchment_id]
        route = evacuation_route(v, siblings, risk_levels)
        out.append(
            EvacuationRouteOut(
                origin_village_id=route.origin_village_id,
                origin_village_name=route.origin_village_name,
                destination_village_id=route.destination_village_id,
                destination_village_name=route.destination_village_name,
                hops=[EvacuationHopOut(**h.__dict__) for h in route.hops],
                total_distance_km=route.total_distance_km,
                estimated_minutes=route.estimated_minutes,
                note=route.note,
            )
        )
    return out


@router.get("/priority", response_model=list[EvacuationPriorityEntryOut])
def get_evacuation_priority(region_id: int | None = None, db: Session = Depends(get_db)):
    """GET /evacuation/priority — transparent evacuation-priority ordering
    (not an evacuation ORDER — decision-support only, see the standing
    disclaimer). Ranks villages by current risk level severity, then by
    less lead time (less warning = more urgent), then by risk score — see
    app/services/evacuation.py's `evacuation_priority` for the exact,
    non-fabricated sort. Optional `?region_id=` scopes to one region."""
    settings = get_settings()
    query = select(Village)
    if region_id is not None:
        query = query.join(MicroCatchment, Village.catchment_id == MicroCatchment.id).where(
            MicroCatchment.region_id == region_id
        )
    villages = db.scalars(query).all()

    entries = []
    for v in villages:
        siblings = [s for s in villages if s.catchment_id == v.catchment_id] if v.catchment_id else [v]
        assessment = compute_risk_for_village(v, db, settings=settings, all_villages_in_catchment=siblings)
        # RiskAssessment.lead_time_minutes is a float (or None) — round at
        # this API boundary, same convention risk_engine.py's
        # persist_prediction() already uses for the DB column.
        lead_time_minutes = round(assessment.lead_time_minutes) if assessment.lead_time_minutes is not None else None
        entries.append((v, assessment.level, assessment.score, lead_time_minutes))

    ranked = evacuation_priority(entries)
    return [EvacuationPriorityEntryOut(**e.__dict__) for e in ranked]
