from fastapi import APIRouter, Depends, HTTPException
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.orm import MicroCatchment, Village
from app.models.schemas import VillageOut

router = APIRouter(prefix="/villages", tags=["villages"])


def _to_out(v: Village) -> VillageOut:
    point = to_shape(v.location)
    return VillageOut(
        id=v.id,
        name=v.name,
        district=v.district,
        state=v.state,
        elevation_m=v.elevation_m,
        population=v.population,
        lat=point.y,
        lon=point.x,
        coordinate_precision=v.coordinate_precision,
        catchment_id=v.catchment_id,
        catchment_name=v.catchment.name if v.catchment else None,
        region_id=v.catchment.region_id if v.catchment else None,
        region_name=v.catchment.region.name if v.catchment and v.catchment.region else None,
        source=v.source.value,
        provenance=v.provenance,
    )


@router.get("", response_model=list[VillageOut])
def list_villages(region_id: int | None = None, db: Session = Depends(get_db)):
    """GET /villages — pilot-region village list with real seeded geometry
    (Phase 2). Optional `?region_id=` (Phase 11) scopes this to one real
    region — the region-agnostic default (no filter) keeps every existing
    caller working unchanged."""
    query = select(Village).order_by(Village.elevation_m.desc())
    if region_id is not None:
        query = query.join(MicroCatchment, Village.catchment_id == MicroCatchment.id).where(
            MicroCatchment.region_id == region_id
        )
    villages = db.scalars(query).all()
    return [_to_out(v) for v in villages]


@router.get("/{village_id}", response_model=VillageOut)
def get_village(village_id: int, db: Session = Depends(get_db)):
    """GET /villages/{id} — village detail card (problem-statement item 34).
    Risk/confidence/lead-time fields land in Phase 4 — this returns identity + location for now."""
    village = db.get(Village, village_id)
    if village is None:
        raise HTTPException(status_code=404, detail=f"No village with id={village_id}")
    return _to_out(village)
