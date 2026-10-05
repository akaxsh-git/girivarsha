"""
Wind field endpoint for the animated map overlay (user-requested, "like the
Mac Weather app").

REAL data only: one batched Open-Meteo forecast call (no API key, same host
the rainfall/soil adapters already use) returns *current* 10 m wind speed,
direction and gusts for a coarse grid of points covering the requested map
bounds. The frontend interpolates between grid points to animate particles.

Honest limits (also in docs/Limitations.md):
- The grid is coarse (default 5x5 over the visible area) and Open-Meteo's
  underlying model resolution is roughly 2-11 km. In steep valleys real
  winds are channelled by terrain at scales far below that, so this shows
  the *regional* flow, not valley-scale wind. Never use it to infer local
  conditions at a specific village.
- It is context for the user, not an input to the risk model.
- If Open-Meteo is unreachable the endpoint returns 503 and the frontend
  hides the layer. Nothing is simulated or invented.

Cached per (rounded bounds, grid size) for an hour so many viewers cost at most
one upstream call per area per hour. Open-Meteo's free tier is rate-limited per
source IP and shared hosting IPs are shared, so a 429 is retried once and, if it
persists, the last REAL grid (up to 6 h old) is served flagged `stale: true`.
"""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import WindFieldOut, WindPointOut
from app.providers.base import OPEN_METEO_TIMEOUT_SECONDS

router = APIRouter(prefix="/wind", tags=["wind"])

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_BOUNDS_STEP_DEG = 0.25  # round outward so nearby viewers share a cache entry
_MAX_SPAN_DEG = 6.0
_MAX_GRID = 12


def _snap_outward(south: float, west: float, north: float, east: float) -> tuple[float, float, float, float]:
    s = _BOUNDS_STEP_DEG
    return (
        math.floor(south / s) * s,
        math.floor(west / s) * s,
        math.ceil(north / s) * s,
        math.ceil(east / s) * s,
    )


def wind_components(speed_ms: float, direction_deg: float) -> tuple[float, float]:
    """Meteorological direction is where the wind comes FROM (0 = from north).
    Returns (u, v): eastward and northward components in m/s."""
    rad = math.radians(direction_deg)
    return -speed_ms * math.sin(rad), -speed_ms * math.cos(rad)


_FRESH_SECONDS = 3600  # reuse a fetched grid for an hour
_MAX_STALE_SECONDS = 6 * 3600  # on upstream failure, serve a REAL older grid up to this age, labelled stale
_RETRY_DELAY_SECONDS = 1.5
_cache: dict[tuple, tuple[float, tuple[WindPointOut, ...], str | None]] = {}
_cache_lock = threading.Lock()


def _fetch_upstream(
    south: float, west: float, north: float, east: float, nx: int, ny: int
) -> tuple[tuple[WindPointOut, ...], str | None]:
    lats = [south + (north - south) * j / (ny - 1) for j in range(ny)]
    lons = [west + (east - west) * i / (nx - 1) for i in range(nx)]
    coords = [(round(la, 4), round(lo, 4)) for la in lats for lo in lons]  # row-major, south->north
    params = {
        "latitude": ",".join(str(c[0]) for c in coords),
        "longitude": ",".join(str(c[1]) for c in coords),
        "current": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "wind_speed_unit": "ms",
        "timezone": "UTC",
    }
    try:
        response = httpx.get(OPEN_METEO_URL, params=params, timeout=OPEN_METEO_TIMEOUT_SECONDS)
        if response.status_code == 429:
            # Free-tier limit is per source IP and shared hosting IPs are shared
            # with other apps: wait briefly and retry once before giving up.
            time.sleep(_RETRY_DELAY_SECONDS)
            response = httpx.get(OPEN_METEO_URL, params=params, timeout=OPEN_METEO_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):  # a single location comes back un-wrapped
            payload = [payload]
        points: list[WindPointOut] = []
        valid_time: str | None = None
        for (lat, lon), entry in zip(coords, payload, strict=True):
            cur = entry["current"]
            speed = float(cur["wind_speed_10m"])
            direction = float(cur["wind_direction_10m"])
            gust = cur.get("wind_gusts_10m")
            u, v = wind_components(speed, direction)
            points.append(
                WindPointOut(
                    lat=lat,
                    lon=lon,
                    speed_ms=round(speed, 2),
                    direction_deg=round(direction, 1),
                    gust_ms=round(float(gust), 2) if gust is not None else None,
                    u=round(u, 3),
                    v=round(v, 3),
                )
            )
            valid_time = valid_time or cur.get("time")
        return tuple(points), valid_time
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Open-Meteo wind fetch failed (rate-limited or unreachable)") from exc


def _get_grid(key: tuple) -> tuple[tuple[WindPointOut, ...], str | None, float, bool]:
    """Returns (points, valid_time, fetched_at_epoch, stale). Fresh cache ->
    no upstream call. Upstream failure -> an older REAL grid if we have one
    (flagged stale), else RuntimeError. Never invents values."""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < _FRESH_SECONDS:
        return hit[1], hit[2], hit[0], False
    try:
        points, valid_time = _fetch_upstream(*key)
    except RuntimeError:
        if hit and now - hit[0] < _MAX_STALE_SECONDS:
            return hit[1], hit[2], hit[0], True
        raise
    with _cache_lock:
        _cache[key] = (now, points, valid_time)
    return points, valid_time, now, False


@router.get("", response_model=WindFieldOut)
def get_wind_field(
    south: float = Query(..., ge=-90, le=90),
    west: float = Query(..., ge=-180, le=180),
    north: float = Query(..., ge=-90, le=90),
    east: float = Query(..., ge=-180, le=180),
    nx: int = Query(5, ge=2, le=_MAX_GRID),
    ny: int = Query(5, ge=2, le=_MAX_GRID),
):
    """GET /wind — current real 10 m wind on a regular grid over the bounds."""
    if north <= south or east <= west:
        raise HTTPException(status_code=422, detail="Bounds must satisfy south < north and west < east.")
    if north - south > _MAX_SPAN_DEG or east - west > _MAX_SPAN_DEG:
        raise HTTPException(status_code=422, detail=f"Bounds span may not exceed {_MAX_SPAN_DEG} degrees.")
    s, w, n, e = _snap_outward(south, west, north, east)
    try:
        points, valid_time, fetched_at, stale = _get_grid((s, w, n, e, nx, ny))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return WindFieldOut(
        south=s,
        west=w,
        north=n,
        east=e,
        nx=nx,
        ny=ny,
        points=list(points),
        valid_time=valid_time,
        fetched_at=datetime.fromtimestamp(fetched_at, tz=timezone.utc).isoformat(),
        stale=stale,
        source="real",
        provider="Open-Meteo (current 10 m wind)",
        note=(
            "Coarse regional wind field. Terrain-channelled valley winds are "
            "not resolved; context only, not used by the risk model."
        ),
    )
