"""
Read side of the hourly weather snapshot (see migration 8a1e4c2d9f10 and
scripts/fetch_weather_snapshot.py).

`lookup()` returns the nearest stored REAL Open-Meteo reading for a point if
one exists within ~5 km and was fetched within MAX_AGE. Any problem at all
(no database configured, table not migrated yet, DB unreachable) returns
None so callers fall straight through to the existing live-call path — this
layer can only ever ADD real data, never break or fake anything.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)

MAX_AGE = timedelta(hours=2)
MAX_DISTANCE_DEG = 0.05  # ~5 km; village points are stored to 3 dp

SNAPSHOT_SUFFIX = "_snapshot"

_LOOKUP_SQL = text(
    """
    SELECT value, unit, fetched_at, provider_name
    FROM weather_snapshots
    WHERE kind = :kind
      AND fetched_at >= :min_fetched
      AND abs(lat_key - :lat) <= :d AND abs(lon_key - :lon) <= :d
    ORDER BY (lat_key - :lat) * (lat_key - :lat) + (lon_key - :lon) * (lon_key - :lon)
    LIMIT 1
    """
)


@dataclass(frozen=True)
class Snapshot:
    value: float
    unit: str
    fetched_at: datetime
    provider_name: str


def lookup(kind: str, lat: float, lon: float, *, now: datetime | None = None) -> Snapshot | None:
    now = now or datetime.now(timezone.utc)
    try:
        from app.models.database import get_engine

        with get_engine().connect() as conn:
            row = conn.execute(
                _LOOKUP_SQL,
                {"kind": kind, "lat": lat, "lon": lon, "d": MAX_DISTANCE_DEG, "min_fetched": now - MAX_AGE},
            ).first()
    except Exception as exc:  # noqa: BLE001 — honest fall-through, see module docstring
        logger.debug("weather snapshot lookup unavailable: %r", exc)
        return None
    if row is None:
        return None
    fetched_at = row.fetched_at
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return Snapshot(value=float(row.value), unit=row.unit, fetched_at=fetched_at, provider_name=row.provider_name)


def age_minutes(observed_at: datetime, *, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return max(0, int((now - observed_at).total_seconds() // 60))
