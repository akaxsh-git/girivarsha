from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.orm import Region
from app.models.schemas import RegionOut

router = APIRouter(prefix="/regions", tags=["regions"])


@router.get("", response_model=list[RegionOut])
def list_regions(db: Session = Depends(get_db)):
    """GET /regions — the real-world region registry (Phase 11). Lets the
    system hold more than one genuinely-sourced pilot valley at once
    without hard-coding a single valley through the schema/API/frontend.
    `status` is honest about depth: 'active' regions have real
    village-level data in this database right now; 'planned' regions are
    real, documented, and cited (a genuine flash-flood/landslide-prone
    valley) but not yet sourced to village level — see
    docs/Region_Onboarding.md for what that sourcing work involves."""
    regions = db.scalars(select(Region)).all()
    return [
        RegionOut(
            id=r.id,
            name=r.name,
            states=r.states,
            description=r.description,
            status=r.status,
            village_count=sum(len(c.villages) for c in r.catchments),
            catchment_count=len(r.catchments),
            source=r.source.value,
            provenance=r.provenance,
        )
        for r in regions
    ]
