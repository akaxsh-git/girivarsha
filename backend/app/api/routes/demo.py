"""
Phase-1-only smoke-test route: proves the DataProvider adapter pattern
(app/providers/base.py) actually works end-to-end, independent of the DB or
risk engine which don't exist yet. Safe to delete once Phase 4/5 supersede it
with real provider-backed endpoints — tracked in docs/Future_Work.md.
"""
from fastapi import APIRouter, Query

from app.providers.base import ProviderUnavailableError, SimulatedRainfallProvider

router = APIRouter(prefix="/demo", tags=["demo"])

_provider = SimulatedRainfallProvider(seed=42)


@router.get("/rainfall-sample")
def rainfall_sample(
    lat: float = Query(30.4667, description="Default: approx. Rudraprayag district, Uttarakhand"),
    lon: float = Query(78.9833),
):
    try:
        reading = _provider.fetch(lat=lat, lon=lon)
    except ProviderUnavailableError as exc:
        return {"error": str(exc)}
    return {
        "lat": lat,
        "lon": lon,
        "value": reading.value,
        "unit": reading.unit,
        "source": reading.source.value,
        "provider": reading.provider_name,
        "observed_at": reading.observed_at.isoformat(),
        "note": "SIMULATED reading — not a real observation. See docs/Data_Sources.md.",
    }
