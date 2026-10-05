from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.orm import MicroCatchment
from app.models.schemas import MicroCatchmentOut

router = APIRouter(prefix="/catchments", tags=["catchments"])


@router.get("", response_model=list[MicroCatchmentOut])
def list_catchments(region_id: int | None = None, db: Session = Depends(get_db)):
    """GET /catchments — micro-catchment topology (problem-statement item 7).
    Polygon geometry (`geom`) is not yet populated — real DEM-based delineation is
    Phase 3 GIS work. What's real here: the catchment's identity, its watershed/river,
    and upstream/downstream topology, derived from documented river-order research
    (see scripts/seed_pilot_region.py). Optional `?region_id=` (Phase 11) scopes
    this to one real region."""
    # Real bug fixed here (found via the SCS-CN integration pass): with no
    # explicit ORDER BY, Postgres is free to return rows in whatever
    # physical order it likes — not guaranteed to match insertion order,
    # and observed in practice to differ between environments (a fresh
    # local Postgres vs. this build's own sandbox). Ordering by id makes
    # the response deterministic and matches insertion order (Mandakini's
    # catchment seeded in Phase 2, before Chamoli's in the Phase 11
    # follow-up), rather than leaving callers to discover the difference
    # the hard way.
    query = select(MicroCatchment).order_by(MicroCatchment.id)
    if region_id is not None:
        query = query.where(MicroCatchment.region_id == region_id)
    catchments = db.scalars(query).all()
    return [
        MicroCatchmentOut(
            id=c.id,
            name=c.name,
            watershed_name=c.watershed_name,
            river_name=c.river_name,
            region_id=c.region_id,
            region_name=c.region.name if c.region else None,
            upstream_catchment_id=c.upstream_catchment_id,
            has_polygon_geometry=c.geom is not None,
            village_count=len(c.villages),
            source=c.source.value,
            provenance=c.provenance,
        )
        for c in catchments
    ]
