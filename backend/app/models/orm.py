"""
Full relational schema (problem-statement item 26). All 14 required entities
are defined here in one migration so the schema is coherent from the start;
most stay empty until the phase that populates them lands (see the
`introduced_phase` note in each table's docstring) — defining the schema
early is cheap and avoids re-litigating relationships table-by-table later.

Every fact table carries a `source` column (real / simulated / derived) at
the row level, mirroring the DataProvider adapter pattern in
app/providers/base.py — the database never has a way to represent "real"
data that quietly came from a simulator.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DataSource(str, enum.Enum):
    REAL = "real"
    SIMULATED = "simulated"
    DERIVED = "derived"


class UserRole(str, enum.Enum):
    CITIZEN = "citizen"
    AUTHORITY = "authority"
    ADMIN = "admin"


class SensorType(str, enum.Enum):
    RAINFALL = "rainfall"
    SOIL_MOISTURE = "soil_moisture"
    WATER_LEVEL = "water_level"
    TILT = "tilt"


class SensorStatus(str, enum.Enum):
    ONLINE = "online"
    STALE = "stale"
    OFFLINE = "offline"


class EventType(str, enum.Enum):
    FLASH_FLOOD = "flash_flood"
    LANDSLIDE = "landslide"
    OTHER = "other"


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertLevel(str, enum.Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


class RoadStatus(str, enum.Enum):
    OPEN = "open"
    UNSAFE = "unsafe"
    BLOCKED = "blocked"


class User(Base):
    """introduced_phase: schema now, real auth in a later phase (item 29 — MVP-level only)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.CITIZEN)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Region(Base):
    """
    introduced_phase: Phase 11 — groups one or more MicroCatchments into a
    named real-world region (typically a river valley), so the system's
    data model can scale to multiple genuinely-sourced pilot valleys across
    Northern India's flash-flood/landslide-prone hill states, instead of
    hard-coding a single valley everywhere in the schema and API.

    This table does NOT itself expand coverage — adding a region row with
    real villages behind it still requires the same real, cited sourcing
    work every existing village/catchment/historical-event row already
    goes through (see docs/Data_Sources.md and docs/Region_Onboarding.md).
    `status` is honest about that: 'active' means real village-level data
    actually exists for it in this database; 'planned' means the region is
    real and documented (a real, citable place with a real flash-flood/
    landslide history) but has NOT been sourced down to village level yet
    — never a placeholder pretending to be populated.
    """

    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    states: Mapped[str] = mapped_column(
        String(255), doc="Comma-separated Indian state(s)/UT(s) this region spans, e.g. 'Uttarakhand'"
    )
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32),
        default="planned",
        doc="'active' = real village/catchment data exists in this DB; 'planned' = real, documented, cited region, not yet sourced to village level.",
    )
    source: Mapped[DataSource] = mapped_column(Enum(DataSource), default=DataSource.DERIVED)
    provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    catchments: Mapped[list["MicroCatchment"]] = relationship(back_populates="region")


class MicroCatchment(Base):
    """
    introduced_phase: Phase 2 (topology from real river-order research),
    `geom` polygon populated in Phase 3 once real DEM delineation runs.
    Self-referential `upstream_catchment_id` encodes the
    District -> Watershed -> Micro-catchment -> Stream flow topology
    (problem-statement item 7) so risk can propagate downstream even before
    full polygon geometry exists. `region_id` (Phase 11) places this
    catchment within the real-world Region registry so the system can hold
    more than one genuinely-sourced valley at once.
    """

    __tablename__ = "micro_catchments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    watershed_name: Mapped[str] = mapped_column(String(255))
    river_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"), nullable=True)
    upstream_catchment_id: Mapped[int | None] = mapped_column(
        ForeignKey("micro_catchments.id"), nullable=True
    )
    geom: Mapped[str | None] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326), nullable=True
    )
    source: Mapped[DataSource] = mapped_column(Enum(DataSource), default=DataSource.DERIVED)
    provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    region: Mapped["Region | None"] = relationship(back_populates="catchments")
    villages: Mapped[list["Village"]] = relationship(back_populates="catchment")
    upstream: Mapped["MicroCatchment | None"] = relationship(remote_side=[id])


class Village(Base):
    """introduced_phase: Phase 2. Real pilot-region settlements, see docs/Data_Sources.md."""

    __tablename__ = "villages"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    district: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(255), default="Uttarakhand")
    elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    population: Mapped[int | None] = mapped_column(Integer, nullable=True)
    catchment_id: Mapped[int | None] = mapped_column(ForeignKey("micro_catchments.id"), nullable=True)
    location: Mapped[str] = mapped_column(Geometry(geometry_type="POINT", srid=4326))
    coordinate_precision: Mapped[str] = mapped_column(
        String(32),
        default="approximate",
        doc="'surveyed' | 'approximate' — see docs/Data_Sources.md for what backs each row.",
    )
    source: Mapped[DataSource] = mapped_column(Enum(DataSource), default=DataSource.REAL)
    provenance: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    catchment: Mapped[MicroCatchment | None] = relationship(back_populates="villages")
    sensors: Mapped[list["Sensor"]] = relationship(back_populates="village")


class Sensor(Base):
    """introduced_phase: schema now, populated in Phase 8 (IoT integration).
    `api_key_hash` added by the device-authentication follow-up (user-
    requested) — see app/api/routes/sensors.py and docs/IoT_Architecture.md.
    Nullable, not because a key is optional going forward, but because this
    column was added after real devices were already provisioned in past
    sessions: a NULL here means "provisioned before authentication existed,
    not yet rotated onto a key" (see scripts/rotate_sensor_api_keys.py), and
    the ingestion endpoint keeps accepting that node's un-authenticated
    requests until it's rotated — an explicit, disclosed transition state,
    never silently enforced retroactively against a key nobody has."""

    __tablename__ = "sensors"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_device_id: Mapped[str] = mapped_column(String(128), unique=True)
    village_id: Mapped[int | None] = mapped_column(ForeignKey("villages.id"), nullable=True)
    sensor_type: Mapped[SensorType] = mapped_column(Enum(SensorType))
    status: Mapped[SensorStatus] = mapped_column(Enum(SensorStatus), default=SensorStatus.OFFLINE)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    battery_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    location: Mapped[str | None] = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    api_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    village: Mapped[Village | None] = relationship(back_populates="sensors")
    readings: Mapped[list["SensorReading"]] = relationship(back_populates="sensor")


class SensorReading(Base):
    """introduced_phase: schema now, populated in Phase 8."""

    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    sensor_id: Mapped[int] = mapped_column(ForeignKey("sensors.id"))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    source: Mapped[DataSource] = mapped_column(Enum(DataSource))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    sensor: Mapped[Sensor] = relationship(back_populates="readings")


class RainfallData(Base):
    """introduced_phase: schema now, populated in Phase 2/4 (real IMD/GPM adapter or simulated provider)."""

    __tablename__ = "rainfall_data"

    id: Mapped[int] = mapped_column(primary_key=True)
    village_id: Mapped[int | None] = mapped_column(ForeignKey("villages.id"), nullable=True)
    catchment_id: Mapped[int | None] = mapped_column(ForeignKey("micro_catchments.id"), nullable=True)
    window: Mapped[str] = mapped_column(String(16), doc="e.g. '1h','3h','6h','12h','24h','3d','5d','7d'")
    value_mm: Mapped[float] = mapped_column(Float)
    source: Mapped[DataSource] = mapped_column(Enum(DataSource))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SoilMoistureData(Base):
    """introduced_phase: schema now, populated in Phase 4."""

    __tablename__ = "soil_moisture_data"

    id: Mapped[int] = mapped_column(primary_key=True)
    village_id: Mapped[int | None] = mapped_column(ForeignKey("villages.id"), nullable=True)
    catchment_id: Mapped[int | None] = mapped_column(ForeignKey("micro_catchments.id"), nullable=True)
    value_pct: Mapped[float] = mapped_column(Float)
    source: Mapped[DataSource] = mapped_column(Enum(DataSource))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WaterLevel(Base):
    """introduced_phase: schema now, populated in Phase 8."""

    __tablename__ = "water_levels"

    id: Mapped[int] = mapped_column(primary_key=True)
    catchment_id: Mapped[int | None] = mapped_column(ForeignKey("micro_catchments.id"), nullable=True)
    sensor_id: Mapped[int | None] = mapped_column(ForeignKey("sensors.id"), nullable=True)
    value_m: Mapped[float] = mapped_column(Float)
    source: Mapped[DataSource] = mapped_column(Enum(DataSource))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class HistoricalEvent(Base):
    """introduced_phase: Phase 2 — real, citable past events only; see docs/Data_Sources.md."""

    __tablename__ = "historical_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    village_id: Mapped[int | None] = mapped_column(ForeignKey("villages.id"), nullable=True)
    catchment_id: Mapped[int | None] = mapped_column(ForeignKey("micro_catchments.id"), nullable=True)
    event_type: Mapped[EventType] = mapped_column(Enum(EventType))
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    severity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    source_citation: Mapped[str] = mapped_column(Text, doc="Required — never a fabricated citation.")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    village: Mapped["Village | None"] = relationship()
    timeline_entries: Mapped[list["EventTimelineEntry"]] = relationship(
        back_populates="historical_event", order_by="EventTimelineEntry.sequence_order"
    )


class EventTimelineEntry(Base):
    """
    introduced_phase: Phase 12 — real, sourced sub-events within a
    HistoricalEvent's timeline (problem-statement item 19, "historical
    event replay"). Every row here must be backed by a real citation; there
    is no simulated-scenario path in this table on purpose — a fabricated
    minute-by-minute timeline of a real disaster would misrepresent it. A
    real disaster's documented record is often genuinely sparse (see
    scripts/seed_event_timelines.py), so `time_precision` says exactly how
    much to trust `occurred_at`: 'exact_time' (a cited clock time),
    'date_only' (the day is known, the time isn't), or 'approximate' (a
    stated estimate, e.g. "about 18 minutes before" a known timestamp,
    itself derived from a citable source, not guessed).
    """

    __tablename__ = "event_timeline_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    historical_event_id: Mapped[int] = mapped_column(ForeignKey("historical_events.id"))
    sequence_order: Mapped[int] = mapped_column(Integer, doc="Real chronological order, even when exact times aren't all comparable across precision levels.")
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_precision: Mapped[str] = mapped_column(
        String(32), doc="'exact_time' | 'date_only' | 'approximate' — see class docstring."
    )
    headline: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    source_citation: Mapped[str] = mapped_column(Text, doc="Required — never a fabricated citation.")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    historical_event: Mapped["HistoricalEvent"] = relationship(back_populates="timeline_entries")


class ModelVersion(Base):
    """introduced_phase: schema now, populated in Phase 5 (model governance, item 38)."""

    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_type: Mapped[str] = mapped_column(String(64))
    version_tag: Mapped[str] = mapped_column(String(64))
    threshold_version: Mapped[str] = mapped_column(String(64))
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RiskPrediction(Base):
    """introduced_phase: schema now, populated in Phase 4 (baseline) / Phase 5 (ML)."""

    __tablename__ = "risk_predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    village_id: Mapped[int] = mapped_column(ForeignKey("villages.id"))
    model_version_id: Mapped[int | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    risk_score: Mapped[float] = mapped_column(Float, doc="0-100")
    risk_level: Mapped[RiskLevel] = mapped_column(Enum(RiskLevel))
    confidence_pct: Mapped[float] = mapped_column(Float)
    lead_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drivers: Mapped[dict | None] = mapped_column(JSON, nullable=True, doc="Explainability payload (Phase 9)")
    input_data_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Alert(Base):
    """introduced_phase: schema now, populated in Phase 4."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    village_id: Mapped[int] = mapped_column(ForeignKey("villages.id"))
    risk_prediction_id: Mapped[int | None] = mapped_column(ForeignKey("risk_predictions.id"), nullable=True)
    level: Mapped[AlertLevel] = mapped_column(Enum(AlertLevel))
    message: Mapped[str] = mapped_column(Text)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    village: Mapped["Village"] = relationship()


class Shelter(Base):
    """introduced_phase: Phase 2 schema, populated with real data in Phase 12 (evacuation routing)."""

    __tablename__ = "shelters"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    village_id: Mapped[int | None] = mapped_column(ForeignKey("villages.id"), nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location: Mapped[str] = mapped_column(Geometry(geometry_type="POINT", srid=4326))
    source: Mapped[DataSource] = mapped_column(Enum(DataSource), default=DataSource.SIMULATED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Road(Base):
    """introduced_phase: schema now, populated in Phase 12 (OSM-derived road/route network)."""

    __tablename__ = "roads"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[RoadStatus] = mapped_column(Enum(RoadStatus), default=RoadStatus.OPEN)
    geom: Mapped[str | None] = mapped_column(Geometry(geometry_type="LINESTRING", srid=4326), nullable=True)
    source: Mapped[DataSource] = mapped_column(Enum(DataSource), default=DataSource.SIMULATED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class NotificationSubscription(Base):
    """introduced_phase: SMS-reach follow-up (user-requested) — a phone
    number opted in to receive an SMS when ONE village crosses into
    ORANGE/RED (see app/services/notifications.py::NOTIFY_LEVELS). No
    account/authentication system exists yet (see docs/Limitations.md —
    same MVP-appropriate posture already taken for User/RBAC), so
    subscribing needs only a village + phone number, not a login.

    `unsubscribed_at` is a soft-delete, not a row delete — kept for the
    same auditability reason `Alert.resolved_at` is (Phase 4's alert model),
    and so a phone number that unsubscribes then re-subscribes later
    doesn't collide with a leftover unique-row assumption."""

    __tablename__ = "notification_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    village_id: Mapped[int] = mapped_column(ForeignKey("villages.id"))
    phone_number: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    village: Mapped["Village"] = relationship()
