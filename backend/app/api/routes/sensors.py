"""
Phase 8: IoT sensor registry + real ingestion endpoint.

Real end-to-end pipeline built for this phase (see iot/README.md for how to
run it):

    ESP32 firmware (iot/firmware/*/*.ino, real code, not yet flashed to
    physical hardware — none exists in this build environment)
          │  MQTT publish
          ▼
    MQTT broker (mosquitto — a real broker, actually run and tested here)
          │
          ▼
    iot/mqtt_bridge.py (real script — subscribes, forwards to the endpoint below)
          │  HTTP POST
          ▼
    POST /api/v1/sensor-reading   <-- this file
          │
          ▼
    Postgres (sensors, sensor_readings tables — Phase 2 schema)

Since no physical ESP32 boards exist in this build environment,
iot/simulate_sensor_publisher.py stands in for them on the MQTT side,
publishing realistic (not random-uniform) synthetic readings and always
declaring source="simulated" — every other hop in the pipeline above is
real and was actually exercised end-to-end (see docs/IoT_Architecture.md
for the exact verification run and its output).

Device authentication (user-requested follow-up): POST /sensor-reading
originally trusted any request naming a registered external_device_id,
with no credential check — see docs/IoT_Architecture.md's "Sensor
authentication" section for the full design. Each provisioned node gets
its own random API key (scripts/seed_iot_nodes.py / rotate_sensor_api_keys.py),
stored here only as a SHA-256 hash; the real device (or, in this build
environment, iot/simulate_sensor_publisher.py) includes its own plaintext
key in its published payload, iot/mqtt_bridge.py forwards it verbatim as
the X-Device-Api-Key header, and this endpoint hashes+compares it with a
constant-time check before accepting the reading. A sensor with no key on
file (api_key_hash IS NULL — provisioned before this feature existed, not
yet rotated) still gets accepted unauthenticated, exactly as before this
follow-up: nothing already provisioned is silently locked out.

Server-side region filtering (user-requested follow-up): GET /sensors
previously had no `?region_id=` filter of its own — the Authority
dashboard scoped it client-side, against whichever villages the selected
region's own (already region-scoped) /villages call returned. That worked,
but meant a client-side bug could leak sensors across regions with nothing
server-side backing the boundary. Same real filter shape as /villages,
/catchments, /risk/map (Sensor -> Village -> MicroCatchment -> Region) —
omitting the param keeps every existing caller's behavior unchanged. A
sensor with no village assigned (village_id IS NULL) never matches any
`region_id` filter, same as it never showed up in any region-scoped
village list either.

Real-regional-data fallback (user-requested follow-up): "why do we need
the simulator if we have real values" — because the IoT sensor network and
the REAL Open-Meteo providers (app/providers/base.py, already used by the
risk engine) were, until this follow-up, two disconnected data paths. No
physical ESP32 hardware has actually been deployed anywhere (see this
file's module docstring above), so with the simulator stopped, GET
/sensors had nothing honest to show except "offline". Rather than force
the simulator to always be running just to keep the dashboard populated,
`_to_sensor_out` now falls back to a REAL Open-Meteo regional-weather
estimate for a sensor's village whenever that sensor has no live reading
of its own — tagged `source="derived"` (see SensorOut's docstring in
app/models/schemas.py) so it is never confused with a genuine device
observation, and cached per (sensor type, ~110m-rounded coordinate,
calendar hour) so this doesn't turn one GET /sensors call into a real
network request per offline sensor on every page load. This does NOT make
`status` say "online" — that field stays an honest fact about the device
itself; only the fallback fields change.
"""
from __future__ import annotations

import hashlib
import hmac
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import APIRouter, Depends, Header, HTTPException
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.database import get_db
from app.models.orm import DataSource, MicroCatchment, Sensor, SensorReading, SensorStatus, SensorType, Village
from app.models.schemas import SensorOut, SensorReadingIn, SensorReadingOut
from app.providers.base import ProviderUnavailableError, RealRainfallProvider, RealSoilMoistureProvider
from app.services.sensor_freshness import compute_sensor_status

router = APIRouter(tags=["sensors"])

# Both real Open-Meteo adapters are stateless/thread-safe per-call httpx.get
# (see DataProvider.thread_safe in app/providers/base.py) — safe to build
# once here and reuse across every request rather than constructing one per
# lookup. Deliberately NOT the config-driven get_rainfall_provider()/
# get_soil_provider() factory the risk engine uses: this fallback's whole
# point is "show real regional weather data when there's no live sensor",
# so it always means Open-Meteo specifically, regardless of whatever
# GIRIVARSHA_ACTIVE_RAINFALL_PROVIDER is set to for the risk engine's own,
# separate data path.
_real_rainfall_provider = RealRainfallProvider()
_real_soil_provider = RealSoilMoistureProvider()

# Which sensor types this fallback can even honestly cover. Open-Meteo has
# no water-level or ground-tilt product at any resolution — leaving those
# two sensor types with fallback_value=None is the honest answer, not a gap
# to "fix" by guessing (see docs/Limitations.md).
_FALLBACK_PROVIDER_BY_SENSOR_TYPE = {
    SensorType.RAINFALL: _real_rainfall_provider,
    SensorType.SOIL_MOISTURE: _real_soil_provider,
}


@lru_cache(maxsize=256)
def _regional_fallback_cached(
    sensor_type: str, lat_r: float, lon_r: float, hour_bucket: str
) -> tuple[float, str] | None:
    """The actual (cached) Open-Meteo call. Cached per (sensor type,
    ~110m-rounded coordinate, calendar hour) — same cache-per-time-bucket
    discipline app/services/antecedent_rainfall.py already uses for its own
    real NASA POWER calls — so several offline sensors in the same village,
    or several dashboard refreshes within the same hour, share one real
    network call instead of one each. `hour_bucket` is cache-key-only, to
    naturally expire the entry once a new hour starts; it is not otherwise
    used, same pattern as antecedent_rainfall.py's `today_iso` argument."""
    del hour_bucket
    provider = _FALLBACK_PROVIDER_BY_SENSOR_TYPE[SensorType(sensor_type)]
    try:
        reading = provider.fetch(lat=lat_r, lon=lon_r)
    except ProviderUnavailableError:
        # Honest degradation: if Open-Meteo itself is unreachable, slow, or
        # returns something unparseable, this sensor's fallback fields just
        # stay None for the rest of this hour's cache window — never a
        # fabricated number, never a 500 raised out of a GET /sensors call.
        return None
    return reading.value, reading.unit


def _fallback_key_for_sensor(sensor: Sensor) -> tuple[str, float, float] | None:
    """The (sensor type, ~110m-rounded lat, ~110m-rounded lon) cache/job key
    for this sensor's regional fallback, or None if it has no village or no
    honest Open-Meteo equivalent (water_level/tilt — see
    _FALLBACK_PROVIDER_BY_SENSOR_TYPE above)."""
    if sensor.village is None or sensor.sensor_type not in _FALLBACK_PROVIDER_BY_SENSOR_TYPE:
        return None
    point = to_shape(sensor.village.location)
    return sensor.sensor_type.value, round(point.y, 3), round(point.x, 3)


def _prefetch_regional_fallbacks(
    sensors: list[Sensor], *, now: datetime
) -> dict[tuple[str, float, float], tuple[float, str] | None]:
    """Performance discipline (the SAME real bug already found and fixed
    for GET /risk/map — see prefetch_readings()'s docstring in
    app/services/risk_engine.py, "~48s end-to-end with real providers
    active"): computing one real Open-Meteo call per offline sensor
    sequentially, inside a per-sensor loop, is exactly the anti-pattern
    already fixed there. This collects every UNIQUE (sensor type,
    ~110m-rounded coordinate) fallback actually needed for this GET
    /sensors response — sensors sharing a village and type collapse to one
    job — then fetches them all concurrently, once each, before the
    per-sensor loop runs. Sensors that are already online contribute no
    job at all, so a fully-online fleet costs nothing extra."""
    hour_bucket = now.strftime("%Y-%m-%dT%H")
    jobs: set[tuple[str, float, float]] = set()
    for sensor in sensors:
        status, _ = compute_sensor_status(sensor.last_seen_at, now=now)
        if status == SensorStatus.ONLINE.value:
            continue
        key = _fallback_key_for_sensor(sensor)
        if key is not None:
            jobs.add(key)

    if not jobs:
        return {}

    results: dict[tuple[str, float, float], tuple[float, str] | None] = {}
    with ThreadPoolExecutor(max_workers=min(16, len(jobs))) as pool:
        futures = {
            pool.submit(_regional_fallback_cached, sensor_type, lat_r, lon_r, hour_bucket): (
                sensor_type,
                lat_r,
                lon_r,
            )
            for (sensor_type, lat_r, lon_r) in jobs
        }
        for future in futures:
            results[futures[future]] = future.result()
    return results


def hash_device_api_key(plaintext_key: str) -> str:
    """SHA-256 hex digest of a device's plaintext API key. No per-key salt:
    unlike a human password, this key is already a high-entropy random
    token (scripts/seed_iot_nodes.py's `secrets.token_urlsafe(32)`), so an
    unsalted hash carries no meaningful rainbow-table risk — the same
    reasoning GitHub/Stripe-style API tokens rely on. Shared with
    scripts/seed_iot_nodes.py and scripts/rotate_sensor_api_keys.py so the
    hash stored at provisioning time is computed identically to the one
    this endpoint recomputes from a request header."""
    return hashlib.sha256(plaintext_key.encode("utf-8")).hexdigest()


def _to_sensor_out(
    sensor: Sensor,
    *,
    now: datetime,
    fallback_cache: dict[tuple[str, float, float], tuple[float, str] | None],
) -> SensorOut:
    status, age = compute_sensor_status(sensor.last_seen_at, now=now)
    latest = max(sensor.readings, key=lambda r: r.observed_at) if sensor.readings else None

    # Real-regional-data fallback (user-requested follow-up) — only even
    # looked up when this sensor has no live/fresh reading of its own.
    # `fallback_cache` was already fully populated by _prefetch_regional_
    # fallbacks() before this function runs, so this is a plain dict lookup,
    # never a fresh network call.
    fallback_value: float | None = None
    fallback_unit: str | None = None
    fallback_source: str | None = None
    if status != SensorStatus.ONLINE.value:
        key = _fallback_key_for_sensor(sensor)
        if key is not None:
            fallback = fallback_cache.get(key)
            if fallback is not None:
                fallback_value, fallback_unit = fallback
                fallback_source = DataSource.DERIVED.value

    return SensorOut(
        id=sensor.id,
        external_device_id=sensor.external_device_id,
        village_id=sensor.village_id,
        village_name=sensor.village.name if sensor.village else None,
        sensor_type=sensor.sensor_type.value,
        status=status,
        last_seen_at=sensor.last_seen_at.isoformat() if sensor.last_seen_at else None,
        seconds_since_last_seen=age,
        battery_pct=sensor.battery_pct,
        last_value=latest.value if latest else None,
        last_unit=latest.unit if latest else None,
        last_reading_source=latest.source.value if latest else None,
        authenticated=sensor.api_key_hash is not None,
        fallback_value=fallback_value,
        fallback_unit=fallback_unit,
        fallback_source=fallback_source,
    )


@router.get("/sensors", response_model=list[SensorOut])
def list_sensors(region_id: int | None = None, db: Session = Depends(get_db)):
    """GET /sensors — every registered node, with live-computed status
    (problem-statement item 24). Seed nodes with `python scripts/seed_iot_nodes.py`
    — they start honestly 'offline' until a reading actually arrives.

    Optional `?region_id=` (server-side region filtering follow-up,
    user-requested) scopes this to sensors whose village belongs to one
    real region — same real Sensor -> Village -> MicroCatchment -> Region
    join /villages and /risk/map already use. Omitting it returns every
    sensor across every region, unchanged from before this filter existed.
    A sensor with no village assigned never matches a region filter."""
    query = select(Sensor)
    if region_id is not None:
        query = (
            query.join(Village, Sensor.village_id == Village.id)
            .join(MicroCatchment, Village.catchment_id == MicroCatchment.id)
            .where(MicroCatchment.region_id == region_id)
        )
    sensors = db.scalars(query).all()
    now = datetime.now(timezone.utc)
    fallback_cache = _prefetch_regional_fallbacks(sensors, now=now)
    return [_to_sensor_out(s, now=now, fallback_cache=fallback_cache) for s in sensors]


@router.get("/sensor-readings", response_model=list[SensorReadingOut])
def list_sensor_readings(limit: int = 50, db: Session = Depends(get_db)):
    """GET /sensor-readings — most recent readings across all sensors."""
    limit = max(1, min(limit, 500))
    readings = db.scalars(
        select(SensorReading).order_by(SensorReading.observed_at.desc()).limit(limit)
    ).all()
    out = []
    for r in readings:
        out.append(
            SensorReadingOut(
                id=r.id,
                sensor_id=r.sensor_id,
                external_device_id=r.sensor.external_device_id,
                village_id=r.sensor.village_id,
                sensor_type=r.sensor.sensor_type.value,
                value=r.value,
                unit=r.unit,
                source=r.source.value,
                observed_at=r.observed_at.isoformat(),
                ingested_at=r.ingested_at.isoformat(),
            )
        )
    return out


@router.post("/sensor-reading", response_model=SensorReadingOut, status_code=201)
def post_sensor_reading(
    payload: SensorReadingIn,
    db: Session = Depends(get_db),
    x_device_api_key: str | None = Header(default=None, alias="X-Device-Api-Key"),
):
    """POST /sensor-reading — the real ingestion contract the MQTT bridge
    (iot/mqtt_bridge.py) forwards onto. 404s for an unregistered device
    rather than silently auto-creating one — a node must be provisioned
    (scripts/seed_iot_nodes.py, or a future admin endpoint) before it can
    report, same honesty principle as everywhere else: no data appears
    without a traceable origin.

    Device authentication (user-requested follow-up): if this sensor has a
    real API key on file (`api_key_hash` set), the request MUST include a
    matching `X-Device-Api-Key` header — 401 otherwise, checked with a
    constant-time comparison (`hmac.compare_digest`) so response timing
    can't be used to guess a key byte-by-byte. A sensor with no key on file
    yet (provisioned before this feature existed) is accepted
    un-authenticated, exactly as it always was — see the module docstring
    and docs/IoT_Architecture.md."""
    sensor = db.scalar(select(Sensor).where(Sensor.external_device_id == payload.external_device_id))
    if sensor is None:
        raise HTTPException(
            status_code=404,
            detail=f"No registered sensor with external_device_id={payload.external_device_id!r} — provision it first",
        )

    if sensor.api_key_hash is not None:
        if not x_device_api_key:
            raise HTTPException(
                status_code=401,
                detail=(
                    f"Device {payload.external_device_id!r} requires an API key — "
                    "send it as the X-Device-Api-Key header (see docs/IoT_Architecture.md)"
                ),
            )
        if not hmac.compare_digest(hash_device_api_key(x_device_api_key), sensor.api_key_hash):
            raise HTTPException(
                status_code=401,
                detail=f"Invalid API key for device {payload.external_device_id!r}",
            )

    try:
        source = DataSource(payload.source)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Unknown source {payload.source!r} — must be real/simulated/derived")

    if payload.observed_at:
        # Phase 13 failure-mode testing caught a real bug here: this used to
        # call datetime.fromisoformat() unguarded, so a malformed timestamp
        # (a genuinely possible real-world failure — a misconfigured node's
        # clock/library producing a non-ISO string) crashed with a bare,
        # unhelpful 500 instead of a clean, honest validation error. Fixed
        # by catching it explicitly, same pattern as the source-tag check
        # just above.
        try:
            observed_at = datetime.fromisoformat(payload.observed_at)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"observed_at={payload.observed_at!r} is not a valid ISO 8601 timestamp",
            )
    else:
        observed_at = datetime.now(timezone.utc)

    reading = SensorReading(
        sensor_id=sensor.id,
        value=payload.value,
        unit=payload.unit,
        source=source,
        observed_at=observed_at,
    )
    db.add(reading)

    sensor.last_seen_at = observed_at
    status, _ = compute_sensor_status(observed_at, now=datetime.now(timezone.utc))
    sensor.status = SensorStatus(status)

    db.commit()
    db.refresh(reading)

    return SensorReadingOut(
        id=reading.id,
        sensor_id=sensor.id,
        external_device_id=sensor.external_device_id,
        village_id=sensor.village_id,
        sensor_type=sensor.sensor_type.value,
        value=reading.value,
        unit=reading.unit,
        source=reading.source.value,
        observed_at=reading.observed_at.isoformat(),
        ingested_at=reading.ingested_at.isoformat(),
    )
