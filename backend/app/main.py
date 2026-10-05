from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    alerts,
    catchments,
    demo,
    evacuation,
    notifications,
    regions,
    replay,
    risk,
    sensors,
    system,
    villages,
    wind,
)
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description=(
        "Hyper-local last-mile disaster intelligence for flash floods and "
        "landslides in hilly regions. Prototype decision-support system — "
        "NOT an official government warning mechanism."
    ),
    version="0.1.0-phase1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router, prefix=settings.api_v1_prefix)
app.include_router(villages.router, prefix=settings.api_v1_prefix)
app.include_router(catchments.router, prefix=settings.api_v1_prefix)
app.include_router(regions.router, prefix=settings.api_v1_prefix)
app.include_router(sensors.router, prefix=settings.api_v1_prefix)
app.include_router(risk.router, prefix=settings.api_v1_prefix)
app.include_router(alerts.router, prefix=settings.api_v1_prefix)
app.include_router(evacuation.router, prefix=settings.api_v1_prefix)
app.include_router(replay.router, prefix=settings.api_v1_prefix)
app.include_router(demo.router, prefix=settings.api_v1_prefix)
app.include_router(notifications.router, prefix=settings.api_v1_prefix)
app.include_router(wind.router, prefix=settings.api_v1_prefix)


@app.get("/")
def root():
    return {
        "app": settings.app_name,
        "tagline": settings.tagline,
        "docs": "/docs",
        "api": settings.api_v1_prefix,
        "disclaimer": "Prototype decision-support system — not an official government warning mechanism.",
    }
