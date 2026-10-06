"""
Fetch REAL current rainfall + soil moisture for every village from Open-Meteo
in ONE batched request and upsert them into `weather_snapshots`.

Runs hourly from GitHub Actions (.github/workflows/weather-snapshot.yml) so
the hosted backend doesn't depend on its own shared, rate-limited outbound
IP. Can also be run by hand:

    GIRIVARSHA_DATABASE_URL='postgresql+psycopg://...' python scripts/fetch_weather_snapshot.py

Exits non-zero if nothing could be fetched, so a failed run shows up red in
GitHub Actions instead of silently writing nothing. Never writes a value it
did not receive from Open-Meteo.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from geoalchemy2.shape import to_shape  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app.models.database import get_engine, session_scope  # noqa: E402
from app.models.orm import Village  # noqa: E402

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
RETRIES = 4

UPSERT = text(
    """
    INSERT INTO weather_snapshots (kind, lat_key, lon_key, value, unit, model_time, fetched_at, provider_name)
    VALUES (:kind, :lat, :lon, :value, :unit, :model_time, :fetched_at, :provider_name)
    ON CONFLICT (kind, lat_key, lon_key) DO UPDATE SET
      value = EXCLUDED.value, unit = EXCLUDED.unit, model_time = EXCLUDED.model_time,
      fetched_at = EXCLUDED.fetched_at, provider_name = EXCLUDED.provider_name
    """
)


def village_points() -> list[tuple[float, float]]:
    with session_scope() as db:
        villages = db.scalars(select(Village)).all()
        pts = {(round(to_shape(v.location).y, 3), round(to_shape(v.location).x, 3)) for v in villages}
    return sorted(pts)


def fetch(points: list[tuple[float, float]]) -> list[dict]:
    params = {
        "latitude": ",".join(str(p[0]) for p in points),
        "longitude": ",".join(str(p[1]) for p in points),
        "current": "precipitation,rain",
        "hourly": "soil_moisture_0_to_1cm",
        "forecast_days": 1,
        "timezone": "UTC",
    }
    last_exc: Exception | None = None
    for attempt in range(RETRIES):
        try:
            r = httpx.get(OPEN_METEO_URL, params=params, timeout=30)
            if r.status_code == 429:
                raise httpx.HTTPStatusError("429 Too Many Requests", request=r.request, response=r)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else [data]
        except httpx.HTTPError as exc:
            last_exc = exc
            wait = 15 * (attempt + 1)
            print(f"attempt {attempt + 1} failed ({exc}); retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise SystemExit(f"Open-Meteo fetch failed after {RETRIES} attempts: {last_exc}")


def rows_from(points, payload, fetched_at):
    now_hour = fetched_at.strftime("%Y-%m-%dT%H:00")
    rows = []
    for (lat, lon), entry in zip(points, payload, strict=True):
        cur = entry.get("current") or {}
        rain = cur.get("rain")
        if rain is None:
            rain = cur.get("precipitation")
        if rain is not None:
            rows.append(dict(kind="rainfall", lat=lat, lon=lon, value=float(rain), unit="mm/hr",
                             model_time=cur.get("time"), fetched_at=fetched_at,
                             provider_name="open_meteo_rainfall_v1"))
        hourly = entry.get("hourly") or {}
        times = hourly.get("time") or []
        values = hourly.get("soil_moisture_0_to_1cm") or []
        if times and values:
            idx = times.index(now_hour) if now_hour in times else 0
            v = values[idx] if idx < len(values) else None
            if v is not None:
                rows.append(dict(kind="soil_moisture", lat=lat, lon=lon,
                                 value=min(100.0, max(0.0, float(v) * 100.0)),
                                 unit="pct (volumetric water content)", model_time=times[idx],
                                 fetched_at=fetched_at, provider_name="open_meteo_soil_moisture_v1"))
    return rows


def main() -> None:
    if not os.environ.get("GIRIVARSHA_DATABASE_URL"):
        raise SystemExit("GIRIVARSHA_DATABASE_URL is not set")
    points = village_points()
    if not points:
        raise SystemExit("No villages in the database")
    fetched_at = datetime.now(timezone.utc)
    payload = fetch(points)
    rows = rows_from(points, payload, fetched_at)
    if not rows:
        raise SystemExit("Open-Meteo returned no usable values")
    with get_engine().begin() as conn:
        conn.execute(UPSERT, rows)
    print(f"stored {len(rows)} real readings for {len(points)} points at {fetched_at.isoformat()}")


if __name__ == "__main__":
    main()
