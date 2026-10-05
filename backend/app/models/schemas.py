"""Pydantic response schemas — the API's public shape, kept separate from
the ORM models (app/models/orm.py) so internal schema changes don't
automatically change the wire contract."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class VillageOut(BaseModel):
    id: int
    name: str
    district: str
    state: str
    elevation_m: float | None
    population: int | None
    lat: float
    lon: float
    coordinate_precision: str
    catchment_id: int | None
    catchment_name: str | None
    region_id: int | None
    region_name: str | None
    source: str
    provenance: str | None

    model_config = {"from_attributes": True}


class RegionOut(BaseModel):
    """GET /regions — the real-world region registry (Phase 11). `status`
    is honest about data depth: 'active' means real villages/catchments
    exist for it in this database; 'planned' means it's a real, documented,
    cited flash-flood/landslide-prone region that hasn't been sourced to
    village level yet — never a placeholder pretending to be populated."""

    id: int
    name: str
    states: str
    description: str
    status: str
    village_count: int
    catchment_count: int
    source: str
    provenance: str | None

    model_config = {"from_attributes": True}


class MicroCatchmentOut(BaseModel):
    id: int
    name: str
    watershed_name: str
    river_name: str | None
    region_id: int | None
    region_name: str | None
    upstream_catchment_id: int | None
    has_polygon_geometry: bool
    village_count: int
    source: str
    provenance: str | None

    model_config = {"from_attributes": True}


class RiskMapEntryOut(BaseModel):
    """Lightweight entry for GET /risk/map — one per village, no full driver
    breakdown (that's GET /risk/{village_id})."""

    village_id: int
    village_name: str
    risk_score: float
    risk_level: str
    confidence_pct: float
    lead_time_minutes: int | None
    glacial_lake_distance_km: float | None = None
    glof_contribution_pct: float | None = None
    glof_contribution_tier: str | None = None
    scs_cn_runoff_depth_mm: float | None = None
    scs_cn_curve_number: float | None = None
    rainfall_threshold_hours_to_threshold: float | None = None
    rainfall_threshold_status: str | None = None
    antecedent_rainfall_5day_mm: float | None = None
    antecedent_rainfall_source: str | None = None


class RiskAssessmentOut(BaseModel):
    """GET /risk/{village_id} — full transparent breakdown of the Phase 4
    baseline scorer's output for one village."""

    model_config = {"protected_namespaces": ()}

    village_id: int
    village_name: str
    risk_score: float
    risk_level: str
    confidence_pct: float
    lead_time_minutes: int | None
    lead_time_note: str
    glacial_lake_distance_km: float | None = None
    glacial_lake_note: str = ""
    glof_contribution_pct: float | None = None
    glof_contribution_tier: str | None = None
    glof_contribution_note: str = ""
    scs_cn_curve_number: float | None = None
    scs_cn_amc_class: str | None = None
    scs_cn_hydrologic_soil_group: str | None = None
    scs_cn_land_cover: str | None = None
    scs_cn_rainfall_depth_mm: float | None = None
    scs_cn_runoff_depth_mm: float | None = None
    scs_cn_runoff_ratio: float | None = None
    scs_cn_note: str = ""
    rainfall_threshold_hours_to_threshold: float | None = None
    rainfall_threshold_status: str | None = None
    rainfall_threshold_applicability: str | None = None
    rainfall_threshold_note: str = ""
    antecedent_rainfall_5day_mm: float | None = None
    antecedent_rainfall_10day_mm: float | None = None
    antecedent_rainfall_20day_mm: float | None = None
    antecedent_rainfall_as_of: str | None = None
    antecedent_rainfall_source: str | None = None
    antecedent_rainfall_note: str = ""
    model_version: str
    drivers: dict
    computed_at: str


class DriverExplanationOut(BaseModel):
    model_config = {"from_attributes": True}

    name: str
    plain_language: str
    score_contribution: float
    share_of_score_pct: float
    raw_value: float
    unit: str
    source: str
    detail: str


class ExplanationOut(BaseModel):
    """GET /model/explanation/{village_id} — Phase 9 model-agnostic 'why'
    narrative. Explains the ACTUAL active model (the Phase 4 baseline) —
    see app/services/explanation.py's module docstring for why this is not
    a fabricated SHAP explanation of the undeployed Phase 5 ML layer."""

    model_config = {"protected_namespaces": (), "from_attributes": True}

    village_id: int
    village_name: str
    summary: str
    ranked_drivers: list[DriverExplanationOut]
    model_explained: str
    caveat: str


class AlertOut(BaseModel):
    id: int
    village_id: int
    village_name: str
    level: str
    message: str
    risk_score: float | None
    issued_at: str
    resolved_at: str | None

    model_config = {"from_attributes": True}


class SensorOut(BaseModel):
    """GET /sensors — a registered node + its LIVE computed status. `status`
    is never read from a stored column; it's recomputed from
    `now - last_seen_at` on every request (see app/api/routes/sensors.py),
    so a node that silently stopped publishing can never keep reporting a
    stale 'online' forever. `authenticated` (device-authentication
    follow-up, user-requested) is likewise a live fact, not a claim: it
    reflects whether this specific node has a real per-device API key on
    file — `false` means its POST /sensor-reading requests are still
    accepted with no credential check at all, honestly surfaced here
    rather than hidden, so an operator can see at a glance which nodes
    still need scripts/rotate_sensor_api_keys.py run against them.

    `fallback_value`/`fallback_unit`/`fallback_source` (real-regional-data
    follow-up, user-requested) are populated ONLY when this sensor has no
    live/fresh reading of its own — no hardware deployed, the simulator not
    running, or a genuinely offline node — as a REAL Open-Meteo regional
    weather estimate for that village's coordinates, so the dashboard shows
    real numbers instead of nothing. `fallback_source` is always
    `"derived"` when set: this genuinely is real (not fabricated) weather
    data, but it is a regional model estimate standing in for this
    specific device's own reading, not that device's actual measurement —
    never to be confused with `last_value`/`last_reading_source`, which are
    always this exact sensor's own real/simulated observations. Only
    rainfall and soil_moisture sensors get one; Open-Meteo has no
    water-level or ground-tilt product at any resolution, so those stay
    `null` honestly rather than guessing (see docs/Limitations.md)."""

    id: int
    external_device_id: str
    village_id: int | None
    village_name: str | None
    sensor_type: str
    status: str
    last_seen_at: str | None
    seconds_since_last_seen: float | None
    battery_pct: float | None
    last_value: float | None
    last_unit: str | None
    last_reading_source: str | None
    authenticated: bool
    fallback_value: float | None = None
    fallback_unit: str | None = None
    fallback_source: str | None = None


class SensorReadingOut(BaseModel):
    id: int
    sensor_id: int
    external_device_id: str
    village_id: int | None
    sensor_type: str
    value: float
    unit: str
    source: str
    observed_at: str
    ingested_at: str


class SensorReadingIn(BaseModel):
    """POST /sensor-reading body — the real ingestion contract an MQTT
    bridge (iot/mqtt_bridge.py) forwards onto after receiving a publish
    from a node. `source` is self-declared by the publisher: real firmware
    would send 'real'; iot/simulate_sensor_publisher.py (standing in for
    physical hardware in this build environment) always sends 'simulated'
    — the backend trusts and stores whatever is declared rather than
    silently overriding it, so the row-level provenance is exactly as
    honest as its publisher."""

    external_device_id: str
    value: float
    unit: str
    source: str = "simulated"
    observed_at: str | None = None


class EvacuationHopOut(BaseModel):
    from_village_id: int
    from_village_name: str
    to_village_id: int
    to_village_name: str
    distance_km: float
    unsafe: bool
    unsafe_reason: str | None
    # Road-network follow-up (user-requested): which distance calculation
    # actually produced distance_km for this hop, never blended silently —
    # "real_road_network" (a real OpenStreetMap road/trail path) or
    # "straight_line_proxy" (the original elevation-order straight line,
    # used whenever real coverage doesn't reach this hop).
    distance_source: str = "straight_line_proxy"
    road_note: str | None = None
    # Ordered [lat, lon] points along the real road/trail path, only when
    # distance_source == "real_road_network".
    polyline: list[tuple[float, float]] | None = None


class EvacuationRouteOut(BaseModel):
    """GET /evacuation/route/{village_id} — Phase 12 prototype route,
    extended by a user-requested follow-up to use a real OpenStreetMap
    road/trail network per hop wherever it actually covers both endpoints.
    See app/services/evacuation.py's module docstring for exactly what's
    real (topology, live risk levels, and now real road/trail distance
    where covered) vs. a stated simplification (partial real-network
    coverage, an assumed on-foot pace, a derived 'unsafe hop' heuristic)."""

    origin_village_id: int
    origin_village_name: str
    destination_village_id: int | None
    destination_village_name: str | None
    hops: list[EvacuationHopOut]
    total_distance_km: float
    estimated_minutes: float | None
    note: str


class EvacuationPriorityEntryOut(BaseModel):
    village_id: int
    village_name: str
    risk_level: str
    risk_score: float
    lead_time_minutes: int | None
    rank: int


class TimelineEntryOut(BaseModel):
    sequence_order: int
    occurred_at: str | None
    time_precision: str
    headline: str
    description: str
    source_citation: str


class ReplayEventOut(BaseModel):
    """GET /replay/{event_id} — Phase 12 real historical-event replay
    (problem-statement item 19). Every entry is a real, cited sub-event —
    see app/models/orm.py::EventTimelineEntry and
    scripts/seed_event_timelines.py for why there is no simulated-scenario
    path here: a fabricated minute-by-minute reconstruction of a real
    disaster would misrepresent it."""

    event_id: int
    village_id: int | None
    village_name: str | None
    event_type: str
    event_date: str
    severity: str | None
    description: str
    source_citation: str
    timeline: list[TimelineEntryOut]


class ReplayEventSummaryOut(BaseModel):
    """GET /replay/events — lightweight list for picking which real event to replay."""

    event_id: int
    village_id: int | None
    village_name: str | None
    event_type: str
    event_date: str
    severity: str | None
    entry_count: int


class HistoricalEventOut(BaseModel):
    id: int
    village_id: int | None
    village_name: str | None
    event_type: str
    event_date: datetime
    severity: str | None
    description: str
    source_citation: str

    model_config = {"from_attributes": True}


class SimulationRequest(BaseModel):
    """POST /simulate — the What-If Simulator (problem-statement item 20).
    Overrides one village's rainfall and/or soil-moisture INPUT to the
    existing Phase 4 baseline formula — there is no separate "simulation
    model." At least one override must be provided; anything not overridden
    keeps using this village's real current data (sensor, if online, else
    the configured provider), exactly as GET /risk/{id} would report it
    right now."""

    village_id: int
    rainfall_mm_hr: float | None = Field(default=None, ge=0, le=500)
    soil_moisture_pct: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _at_least_one_override(self) -> "SimulationRequest":
        if self.rainfall_mm_hr is None and self.soil_moisture_pct is None:
            raise ValueError(
                "Provide at least one of rainfall_mm_hr or soil_moisture_pct — "
                "otherwise this would just be GET /risk/{village_id} again."
            )
        return self


class SimulationOut(BaseModel):
    """Response for POST /simulate. Always carries BOTH the village's real
    current baseline assessment and the hypothetical one, so the delta the
    overrides caused is visible rather than presented as if it were the
    village's actual live risk. Nothing in this response is persisted to
    the database or fed into /alerts — a what-if run has zero side effects,
    same discipline as every other honest-by-construction endpoint here."""

    model_config = {"protected_namespaces": ()}

    village_id: int
    village_name: str
    is_simulation: bool = True
    overrides_applied: dict
    baseline_risk_score: float
    baseline_risk_level: str
    baseline_confidence_pct: float
    simulated_risk_score: float
    simulated_risk_level: str
    simulated_confidence_pct: float
    baseline_scs_cn_curve_number: float | None = None
    baseline_scs_cn_runoff_depth_mm: float | None = None
    baseline_scs_cn_runoff_ratio: float | None = None
    baseline_scs_cn_note: str = ""
    simulated_scs_cn_curve_number: float | None = None
    simulated_scs_cn_runoff_depth_mm: float | None = None
    simulated_scs_cn_runoff_ratio: float | None = None
    simulated_scs_cn_note: str = ""
    baseline_rainfall_threshold_hours_to_threshold: float | None = None
    baseline_rainfall_threshold_status: str | None = None
    baseline_rainfall_threshold_note: str = ""
    simulated_rainfall_threshold_hours_to_threshold: float | None = None
    simulated_rainfall_threshold_status: str | None = None
    simulated_rainfall_threshold_note: str = ""
    # Antecedent rainfall is real/simulated HISTORY, independent of a
    # rainfall/soil-moisture override — identical for baseline and
    # simulated, so it's surfaced once rather than as a baseline/simulated
    # pair (see antecedent_rainfall_note for why it doesn't change here).
    antecedent_rainfall_5day_mm: float | None = None
    antecedent_rainfall_source: str | None = None
    antecedent_rainfall_note: str = ""
    model_version: str
    drivers: dict
    note: str


class WindPointOut(BaseModel):
    """One grid point of the wind field. `direction_deg` is meteorological
    (where the wind blows FROM); `u`/`v` are eastward/northward m/s."""

    lat: float
    lon: float
    speed_ms: float
    direction_deg: float
    gust_ms: float | None = None
    u: float
    v: float


class WindFieldOut(BaseModel):
    """Real, coarse regional wind field for the map overlay. Always
    `source="real"` (Open-Meteo); the endpoint returns 503 rather than
    inventing values. Context only — not an input to the risk model."""

    south: float
    west: float
    north: float
    east: float
    nx: int
    ny: int
    points: list[WindPointOut]  # row-major, south->north, west->east
    valid_time: str | None = None
    source: str
    provider: str
    note: str
