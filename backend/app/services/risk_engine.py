"""
Phase 4 baseline risk engine ("Layer A" in docs/Architecture.md) — a
transparent, weighted scorer. Deliberately NOT a black box: every score is
a plain weighted sum of named, inspectable components, each carrying its
own data-source tag. This is intentional per the problem statement's
"hybrid risk engine" requirement (item 9): the ML layer (Phase 5) augments
this, it does not replace it, and this baseline keeps working (with an
honest, lower confidence) if the ML layer or any single input is
unavailable.

What this engine is NOT:
  - It is not validated against real outcomes. There is exactly one
    historical event in the whole pilot region (2013 Kedarnath) — nowhere
    near enough to claim a tuned or validated model. The weights below are
    a reasonable, documented starting point, not a fitted result.
  - Lead time (Phase 10, app/services/lead_time.py) is a straight-line-
    distance / single-assumed-velocity prototype, not validated hydraulic
    routing. `drivers` here is a transparent breakdown of this specific
    formula; the model-agnostic "why" narrative (Phase 9) lives in
    app/services/explanation.py, built from these same real components.
  - Rainfall and soil moisture are SIMULATED by default, or REAL when
    GIRIVARSHA_ACTIVE_RAINFALL_PROVIDER / GIRIVARSHA_ACTIVE_SOIL_PROVIDER
    are set to "real" (Open-Meteo, no API key — see app/providers/base.py).
    Historical susceptibility and upstream topology stay DERIVED either
    way. Confidence is computed from whichever tags are actually active,
    not asserted — it rises automatically, with no change to this file,
    once real providers are switched on.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import RiskWeights, Settings, get_settings
from app.models.orm import (
    DataSource,
    HistoricalEvent,
    ModelVersion,
    RiskLevel,
    RiskPrediction,
    Sensor,
    SensorReading,
    SensorStatus,
    SensorType,
    Village,
)
from app.providers.base import DataProvider, ProviderUnavailableError, Reading, get_rainfall_provider, get_soil_provider
from app.services.glacial_lake_proximity import nearest_glacial_lake
from app.services.glacial_melt_hazard import glof_contribution_indicator, nearest_glacier_melt
from app.services.antecedent_rainfall import get_antecedent_rainfall
from app.services.lead_time import estimate_lead_time, village_latlon
from app.services.rainfall_threshold import assess_rainfall_threshold
from app.services.scs_cn_runoff import estimate_runoff
from app.services.sensor_freshness import compute_sensor_status

# Marks a Reading as sensor-sourced (vs. provider-sourced) for the
# description text below — not a data-source tag (that's still Reading.source,
# taken as-is from what the sensor/publisher declared).
SENSOR_PROVIDER_PREFIX = "sensor:"

MODEL_VERSION_TAG = "baseline-v1"

# How much a component's source tier contributes to overall confidence.
# REAL sensor/API data is trusted most; SIMULATED data (everything right
# now, for rainfall/soil moisture) is trusted least but still shown, never
# hidden. This is why confidence today is honestly capped in the 30-50%
# range — it will rise automatically, with no code change here, once real
# providers replace simulated ones behind the same DataProvider interface.
TIER_CONFIDENCE = {
    DataSource.REAL: 0.90,
    DataSource.DERIVED: 0.65,
    DataSource.SIMULATED: 0.35,
}

# Historical event severity -> susceptibility contribution (0..1). Only
# "catastrophic" is populated today (the one seeded 2013 Kedarnath event);
# the rest exist so the mapping doesn't silently mishandle a future event
# with a different severity label.
SEVERITY_SCORE = {
    "catastrophic": 1.0,
    "severe": 0.8,
    "major": 0.7,
    "moderate": 0.5,
    "minor": 0.25,
}
DEFAULT_SEVERITY_SCORE = 0.4  # unrecognized severity string — logged, not silently zeroed

# Normalization caps — deliberately conservative/round, documented rather
# than fitted (no labelled dataset exists yet to fit them against). See
# docs/ML_Methodology.md for how Phase 5 will revisit these with real data.
RAINFALL_CAP_MM_PER_HR = 50.0


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _region_name(village: Village) -> str | None:
    """Real-world region name for this village, via its catchment's real
    Region link (Phase 11's registry) — used only to honestly disclose
    whether the rainfall I-D threshold curve is a direct fit or a regional
    proxy for this village (see app/services/rainfall_threshold.py). Never
    raises: an unlinked catchment/region degrades to None, which
    rainfall_threshold.py already treats as "regional proxy" rather than
    crashing."""
    catchment = village.catchment
    if catchment is None:
        return None
    region = catchment.region
    return region.name if region is not None else None


@dataclass
class Component:
    name: str
    description: str
    raw_value: float
    unit: str
    source: DataSource
    normalized_0_1: float
    weight: float

    @property
    def score_contribution(self) -> float:
        return round(self.weight * self.normalized_0_1 * 100, 2)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "raw_value": self.raw_value,
            "unit": self.unit,
            "source": self.source.value,
            "normalized_0_1": round(self.normalized_0_1, 3),
            "weight": self.weight,
            "score_contribution": self.score_contribution,
        }


@dataclass
class RiskAssessment:
    village_id: int
    score: float
    level: RiskLevel
    confidence_pct: float
    components: list[Component]
    model_version_tag: str = MODEL_VERSION_TAG
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lead_time_minutes: float | None = None
    lead_time_note: str = ""
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

    def drivers_json(self) -> dict:
        return {
            "model_version": self.model_version_tag,
            "components": [c.to_dict() for c in self.components],
            "confidence_explanation": (
                "Confidence reflects data-source quality (real > derived > simulated "
                "for each input), not validated model accuracy — no outcome validation "
                "exists yet (Phase 5 discusses why: only 1 historical event is seeded). "
                "It will rise automatically as real providers replace simulated ones "
                "behind the same adapter interface, with no change to this formula."
            ),
            "not_included_yet": [
                "Real per-reach hydraulic routing for lead time — the current estimate "
                "(see lead_time_minutes/lead_time_note) is a straight-line-distance / "
                "single-assumed-velocity prototype, not HEC-RAS-grade modeling.",
                "Glacial-lake proximity (see glacial_lake_distance_km/glacial_lake_note) is "
                "real, advisory context only — not folded into score/level. No lake-attribute-"
                "aware GLOF hazard model exists to calibrate a weighted contribution against; "
                "see app/services/glacial_lake_proximity.py's module docstring.",
                "glof_contribution_pct is a heuristic 0-100 blend of real glacial-lake "
                "proximity and real glacier melt rate — advisory context only, NOT folded "
                "into score/level and NOT a calibrated statistical flash-flood probability "
                "(no outcome data exists to calibrate one); see app/services/"
                "glacial_melt_hazard.py's module docstring.",
                "scs_cn_runoff_depth_mm is a SEPARATE, independent SCS-CN (Soil Conservation "
                "Service Curve Number) direct-runoff estimate from real per-village soil "
                "texture (ISRIC SoilGrids) and land cover (ESA WorldCover) — a real, standard "
                "hydrological method shown ALONGSIDE this score for comparison, not folded "
                "into it and not a replacement for it; see app/services/scs_cn_runoff.py's "
                "module docstring for every simplification made (assumed 1-hour storm depth, "
                "soil-moisture-as-antecedent-condition proxy, a default hydrologic condition "
                "per land-cover class).",
                "rainfall_threshold_hours_to_threshold is a THIRD, independent indicator from a "
                "real, peer-reviewed, region-specific rainfall intensity-duration (I-D) "
                "landslide-triggering threshold curve (Kanungo & Sharma 2014, covering this "
                "project's own Chamoli pilot valley directly) — advisory context only, NOT "
                "folded into score/level. rainfall_threshold_applicability discloses whether "
                "this village's region is the study's own catchment ('direct_fit') or a "
                "regional proxy ('regional_proxy'); see app/services/rainfall_threshold.py's "
                "module docstring for the formula and every simplification made (a "
                "constant-rate assumption, not a real hyetograph).",
                "antecedent_rainfall_5day_mm (and its 10/20-day siblings) is a real or simulated "
                "antecedent-precipitation-index figure that now DRIVES the SCS-CN Antecedent Moisture "
                "Condition classification above whenever real data is available (opt-in via "
                "GIRIVARSHA_ACTIVE_ANTECEDENT_PROVIDER=real), replacing the soil-moisture proxy — see "
                "app/services/antecedent_rainfall.py's module docstring for the real NASA POWER "
                "reporting-latency caveat (its most recent ~1-2 weeks aren't yet available, so the real "
                "figure here is as of roughly a week or two ago, not literally today).",
            ],
        }


def get_or_create_model_version(db: Session, settings: Settings) -> ModelVersion:
    """Idempotent — the baseline scorer has exactly one governance row
    (problem-statement item 38); re-running this doesn't create duplicates."""
    existing = db.scalar(select(ModelVersion).where(ModelVersion.version_tag == MODEL_VERSION_TAG))
    if existing is not None:
        return existing
    mv = ModelVersion(
        model_type="weighted_baseline",
        version_tag=MODEL_VERSION_TAG,
        threshold_version=(
            f"low_max={settings.risk_thresholds.low_max},"
            f"moderate_max={settings.risk_thresholds.moderate_max},"
            f"high_max={settings.risk_thresholds.high_max}"
        ),
        trained_at=None,  # not a trained model — a fixed, documented formula
        notes=(
            "Transparent weighted-sum baseline (Layer A). Not fitted to data — "
            "weights are a documented starting point, see app/services/risk_engine.py. "
            "Superseded/augmented by an ML layer in Phase 5, which will report its own "
            "version here rather than overwriting this one."
        ),
    )
    db.add(mv)
    db.flush()
    return mv


def _historical_susceptibility(db: Session, village: Village) -> Component:
    direct_events = db.scalars(select(HistoricalEvent).where(HistoricalEvent.village_id == village.id)).all()
    if direct_events:
        best = max(SEVERITY_SCORE.get(e.severity or "", DEFAULT_SEVERITY_SCORE) for e in direct_events)
        return Component(
            name="historical_susceptibility",
            description=f"Real recorded historical event(s) at this village ({len(direct_events)})",
            raw_value=best,
            unit="0-1 susceptibility",
            source=DataSource.DERIVED,
            normalized_0_1=best,
            weight=0.0,  # filled in by caller
        )
    if village.catchment_id is not None:
        catchment_events = db.scalars(
            select(HistoricalEvent).where(HistoricalEvent.catchment_id == village.catchment_id)
        ).all()
        if catchment_events:
            best = max(SEVERITY_SCORE.get(e.severity or "", DEFAULT_SEVERITY_SCORE) for e in catchment_events)
            # A recorded event elsewhere in the same catchment is real signal that
            # this is a hazard-prone valley, but it isn't evidence at this exact
            # village — discounted rather than treated as equally strong.
            discounted = best * 0.5
            return Component(
                name="historical_susceptibility",
                description=(
                    f"No recorded event at this exact village, but {len(catchment_events)} "
                    "recorded elsewhere in its micro-catchment — discounted 50%"
                ),
                raw_value=discounted,
                unit="0-1 susceptibility",
                source=DataSource.DERIVED,
                normalized_0_1=discounted,
                weight=0.0,
            )
    return Component(
        name="historical_susceptibility",
        description="No recorded historical event at this village or its micro-catchment yet",
        raw_value=0.0,
        unit="0-1 susceptibility",
        source=DataSource.DERIVED,
        normalized_0_1=0.0,
        weight=0.0,
    )


def _fresh_sensor_reading(db: Session, village: Village, sensor_type: SensorType) -> Reading | None:
    """Phase 8+ follow-up (user-requested): the top of the documented
    fallback hierarchy (docs/Architecture.md, "Sensor-failure / fallback
    hierarchy, problem-statement item 13") is now actually consulted, not
    just described — LOCAL SENSOR is genuinely tried first. Returns None
    (never raises) whenever there's no registered sensor of this type for
    this village, or the freshest one isn't currently 'online' by the exact
    same live freshness computation GET /sensors uses (app/services/
    sensor_freshness.py) — callers fall through to the configured provider
    exactly as before this change, so nothing about the existing REAL/
    SIMULATED provider fallback path changes when no sensor is available.

    The returned Reading's `source` tag is taken as-is from what the sensor
    reading itself declared (SensorReading.source — 'real' for genuine
    hardware, 'simulated' for this build's stand-in publisher, never
    silently upgraded) — a demo sensor publishing source='simulated' does
    NOT make confidence jump to the REAL tier just because a sensor exists;
    only an actual real-hardware reading would."""
    # .limit(1) rather than a bare .scalar() query: a village with more than
    # one registered sensor of the same type (not the case in this pilot's
    # own seed data today, but a real deployment might add redundant nodes)
    # must never crash the whole risk computation with MultipleResultsFound
    # — pick the most recently-seen one instead.
    sensor = db.scalar(
        select(Sensor)
        .where(Sensor.village_id == village.id, Sensor.sensor_type == sensor_type)
        .order_by(Sensor.last_seen_at.desc().nullslast())
        .limit(1)
    )
    if sensor is None or sensor.last_seen_at is None:
        return None
    status, _ = compute_sensor_status(sensor.last_seen_at, now=datetime.now(timezone.utc))
    if status != SensorStatus.ONLINE.value:
        return None
    latest = db.scalar(
        select(SensorReading)
        .where(SensorReading.sensor_id == sensor.id)
        .order_by(SensorReading.observed_at.desc())
        .limit(1)
    )
    if latest is None:
        return None
    return Reading(
        value=latest.value,
        unit=latest.unit,
        source=latest.source,
        observed_at=latest.observed_at,
        provider_name=f"{SENSOR_PROVIDER_PREFIX}{sensor.external_device_id}",
    )


def _fetch_rainfall(
    provider: DataProvider,
    village: Village,
    db: Session,
    *,
    cache: dict[int, Reading | None] | None = None,
) -> Reading | None:
    # Performance follow-up (user-requested — see prefetch_readings below for
    # the full story): when a request-scoped cache is supplied and already
    # holds this village's rainfall reading, use it instead of re-doing the
    # sensor check + provider call — this is what stops the same village's
    # rainfall from being independently re-fetched once per downstream
    # village that has it as "upstream." Falls through to the original
    # uncached behavior whenever no cache is supplied (GET /risk/{id},
    # /simulate, /model/explanation — all single-village, nothing to dedupe)
    # or the cache genuinely has no entry for this village yet.
    if cache is not None and village.id in cache:
        return cache[village.id]
    sensor_reading = _fresh_sensor_reading(db, village, SensorType.RAINFALL)
    if sensor_reading is not None:
        return sensor_reading
    point = _village_point(village)
    try:
        return provider.fetch(lat=point[0], lon=point[1])
    except ProviderUnavailableError:
        return None


def _fetch_soil(
    provider: DataProvider,
    village: Village,
    db: Session,
    *,
    cache: dict[int, Reading | None] | None = None,
) -> Reading | None:
    if cache is not None and village.id in cache:
        return cache[village.id]
    sensor_reading = _fresh_sensor_reading(db, village, SensorType.SOIL_MOISTURE)
    if sensor_reading is not None:
        return sensor_reading
    point = _village_point(village)
    try:
        return provider.fetch(lat=point[0], lon=point[1])
    except ProviderUnavailableError:
        return None


def prefetch_readings(
    rainfall_provider: DataProvider,
    soil_provider: DataProvider,
    villages: list[Village],
    db: Session,
) -> tuple[dict[int, Reading | None], dict[int, Reading | None]]:
    """Performance follow-up (user-requested): GET /risk/map was measured
    (via the user's own `time curl`) taking ~48s end-to-end with real
    providers active. Root cause was two compounding issues, both in this
    module: (1) compute_risk_for_village()'s upstream-rainfall lookup
    independently re-fetches every upstream sibling village's rainfall
    reading on EVERY village's own computation, so the real provider-call
    count for an N-village catchment scales roughly with N^2/2, not N (a
    6-village catchment does ~27 rainfall fetches, not 6); and (2) every one
    of those provider calls (Open-Meteo, ~1-5s each over the network) ran
    strictly sequentially, one at a time.

    This function fixes both, called once per /risk/map request (see
    app/api/routes/risk.py) before the per-village loop, and its result
    threaded into every compute_risk_for_village() call via the
    rainfall_cache/soil_cache parameters:

      1. Deduplication: every village's rainfall/soil reading is looked up
         at most ONCE here, cached by village id, regardless of how many
         other villages in the request need it as "upstream." _fetch_rainfall
         / _fetch_soil consult this cache first (see above) instead of
         re-doing the work.
      2. Safe parallelism: the ONE part of a lookup that must stay
         sequential — the local-sensor-first DB check (_fresh_sensor_reading)
         — runs up front, in this calling thread, using the same shared
         Session every other query in the request uses (SQLAlchemy Sessions
         are documented as not safe to use concurrently from multiple
         threads). Only the genuinely slow, purely-network leftover
         (DataProvider.fetch, for whichever villages didn't have a fresh
         sensor override) is farmed out to a small thread pool — and only
         for providers that declare themselves safe for that (see
         DataProvider.thread_safe in app/providers/base.py; today that's
         RealRainfallProvider/RealSoilMoistureProvider, which touch no
         shared state per call). A provider that hasn't declared itself
         thread-safe (the simulated providers, which share a single
         random.Random instance) is simply called sequentially here instead
         — exactly as before this follow-up, so simulated-provider mode
         (this project's default) sees no behavior change at all, just the
         dedup win.

    Returns (rainfall_cache, soil_cache), each keyed by village.id, with
    every village in `villages` guaranteed a (possibly None) entry — ready
    to pass straight into compute_risk_for_village."""
    rainfall_cache: dict[int, Reading | None] = {}
    soil_cache: dict[int, Reading | None] = {}
    pending_rainfall: list[Village] = []
    pending_soil: list[Village] = []

    # Sequential pass: the only part that touches the shared DB session.
    for v in villages:
        sensor = _fresh_sensor_reading(db, v, SensorType.RAINFALL)
        if sensor is not None:
            rainfall_cache[v.id] = sensor
        else:
            pending_rainfall.append(v)
        sensor = _fresh_sensor_reading(db, v, SensorType.SOIL_MOISTURE)
        if sensor is not None:
            soil_cache[v.id] = sensor
        else:
            pending_soil.append(v)

    def _resolve(kind: str, provider: DataProvider, v: Village) -> Reading | None:
        point = _village_point(v)
        try:
            return provider.fetch(lat=point[0], lon=point[1])
        except ProviderUnavailableError:
            return None

    # Parallel pass: only for provider/kind combinations declared safe for
    # concurrent use (see DataProvider.thread_safe) — everything else below
    # is resolved sequentially, exactly as it would have been before this
    # follow-up.
    parallel_jobs: list[tuple[str, Village, DataProvider]] = []
    for v in pending_rainfall:
        if rainfall_provider.thread_safe:
            parallel_jobs.append(("rainfall", v, rainfall_provider))
        else:
            rainfall_cache[v.id] = _resolve("rainfall", rainfall_provider, v)
    for v in pending_soil:
        if soil_provider.thread_safe:
            parallel_jobs.append(("soil", v, soil_provider))
        else:
            soil_cache[v.id] = _resolve("soil", soil_provider, v)

    if parallel_jobs:
        # Bounded pool: this work is I/O-bound (waiting on Open-Meteo), not
        # CPU-bound, so more workers than jobs is fine — it's what actually
        # collapses many seconds of sequential waiting down to roughly the
        # slowest single call instead of their sum.
        with ThreadPoolExecutor(max_workers=min(16, len(parallel_jobs))) as pool:
            futures = {
                pool.submit(_resolve, kind, provider, v): (kind, v.id)
                for kind, v, provider in parallel_jobs
            }
            for future in futures:
                kind, village_id = futures[future]
                reading = future.result()
                if kind == "rainfall":
                    rainfall_cache[village_id] = reading
                else:
                    soil_cache[village_id] = reading

    return rainfall_cache, soil_cache


def _village_point(village: Village) -> tuple[float, float]:
    from geoalchemy2.shape import to_shape

    p = to_shape(village.location)
    return p.y, p.x


def compute_risk_for_village(
    village: Village,
    db: Session,
    *,
    settings: Settings | None = None,
    rainfall_provider: DataProvider | None = None,
    soil_provider: DataProvider | None = None,
    all_villages_in_catchment: list[Village] | None = None,
    rainfall_override: float | None = None,
    soil_override: float | None = None,
    rainfall_cache: dict[int, Reading | None] | None = None,
    soil_cache: dict[int, Reading | None] | None = None,
) -> RiskAssessment:
    """Computes one village's baseline risk score right now. Stateless and
    side-effect-free (does not write to the DB) — callers decide whether to
    persist the result as a RiskPrediction row (see persist_prediction).

    `rainfall_override` / `soil_override` (Phase 14+ follow-up, user-
    requested: the What-If Simulator, POST /simulate) let a caller substitute
    a hypothetical value for this village's own rainfall/soil-moisture input
    instead of fetching a real sensor/provider reading — everything else
    (upstream rainfall, historical susceptibility, weights, thresholds) stays
    exactly as it would for a real GET /risk/{id} call. An override is always
    tagged DataSource.SIMULATED regardless of what this village's real data
    source currently is, because a presenter-typed number is not a live
    observation — see SimulationOut.note for the same disclosure surfaced to
    the API caller.

    `rainfall_cache` / `soil_cache` (performance follow-up, user-requested):
    optional request-scoped dicts, keyed by village id, produced by
    prefetch_readings() above. GET /risk/map builds one pair of these once
    per request and passes the SAME dicts into every village's call, so a
    village's own reading is fetched at most once no matter how many other
    villages in the request need it as "upstream" — see prefetch_readings's
    docstring for the full story. Left as None (the default) for every
    other caller (GET /risk/{id}, /simulate, /model/explanation), which are
    single-village calls with nothing to deduplicate."""
    settings = settings or get_settings()
    weights: RiskWeights = settings.risk_weights
    # Reads GIRIVARSHA_ACTIVE_RAINFALL_PROVIDER / GIRIVARSHA_ACTIVE_SOIL_PROVIDER
    # (default "simulated") — this is the actual place those settings take
    # effect; they existed since Phase 1 but were never consulted anywhere
    # until this wiring. Set either to "real" to switch that input to the
    # live Open-Meteo adapter (app/providers/base.py) — no code change
    # needed, same adapter-pattern promise as everywhere else in this file.
    rainfall_provider = rainfall_provider or get_rainfall_provider(settings.active_rainfall_provider)
    soil_provider = soil_provider or get_soil_provider(settings.active_soil_provider)

    if rainfall_override is not None:
        rainfall_value = rainfall_override
        rainfall_source = DataSource.SIMULATED
        rainfall_description = "What-if override rainfall rate (hypothetical, not a live reading)"
    else:
        rainfall_reading = _fetch_rainfall(rainfall_provider, village, db, cache=rainfall_cache)
        rainfall_value = rainfall_reading.value if rainfall_reading else 0.0
        rainfall_source = rainfall_reading.source if rainfall_reading else DataSource.SIMULATED
        rainfall_from_sensor = bool(
            rainfall_reading and rainfall_reading.provider_name.startswith(SENSOR_PROVIDER_PREFIX)
        )
        rainfall_description = (
            f"Current rainfall rate from this village's live sensor ({rainfall_reading.provider_name})"
            if rainfall_from_sensor
            else "Current rainfall rate at this village"
        )
    rainfall_component = Component(
        name="rainfall_intensity",
        description=rainfall_description,
        raw_value=rainfall_value,
        unit="mm/hr",
        source=rainfall_source,
        normalized_0_1=_clamp01(rainfall_value / RAINFALL_CAP_MM_PER_HR),
        weight=weights.rainfall_intensity,
    )

    if soil_override is not None:
        soil_value = soil_override
        soil_source = DataSource.SIMULATED
        soil_description = "What-if override soil saturation (hypothetical, not a live reading)"
    else:
        soil_reading = _fetch_soil(soil_provider, village, db, cache=soil_cache)
        soil_value = soil_reading.value if soil_reading else 0.0
        soil_source = soil_reading.source if soil_reading else DataSource.SIMULATED
        soil_from_sensor = bool(soil_reading and soil_reading.provider_name.startswith(SENSOR_PROVIDER_PREFIX))
        soil_description = (
            f"Current soil saturation from this village's live sensor ({soil_reading.provider_name})"
            if soil_from_sensor
            else "Current soil saturation at this village"
        )
    soil_component = Component(
        name="soil_moisture",
        description=soil_description,
        raw_value=soil_value,
        unit="pct",
        source=soil_source,
        normalized_0_1=_clamp01(soil_value / 100.0),
        weight=weights.soil_moisture,
    )

    # Upstream contribution — the piece that makes this catchment-aware
    # rather than per-village-isolated (problem-statement item 7). With
    # only one micro-catchment seeded so far (Phase 2), "upstream" is
    # approximated as other villages in the SAME catchment at higher
    # elevation, matching the real, documented river order in
    # scripts/seed_pilot_region.py. Once multiple micro-catchments with
    # real upstream_catchment_id links exist, this should walk that
    # topology instead — tracked in docs/GIS_Methodology.md.
    upstream_max = 0.0
    # Was hardcoded to DataSource.SIMULATED regardless of what actually
    # produced upstream_max — a real, pre-existing inconsistency this
    # follow-up also fixed: even with GIRIVARSHA_ACTIVE_RAINFALL_PROVIDER=
    # real (or a real online sensor) upstream, this component's confidence
    # contribution stayed pinned at the SIMULATED tier while
    # rainfall_intensity correctly rose to REAL. Now tagged from the actual
    # reading that produced the max, same honesty standard as every other
    # component here.
    upstream_max_source = DataSource.SIMULATED
    upstream_count = 0
    siblings: list[Village] = []
    if village.catchment_id is not None:
        siblings = all_villages_in_catchment
        if siblings is None:
            siblings = db.scalars(select(Village).where(Village.catchment_id == village.catchment_id)).all()
        upstream = [
            v for v in siblings
            # Real bug fixed here (found via this performance follow-up):
            # when a caller supplies `all_villages_in_catchment` (GET
            # /risk/map does, so every village's call can share one query
            # instead of N), that list was never actually filtered back
            # down to the SAME catchment before this line — the `siblings
            # = db.scalars(...where(catchment_id == ...))` fallback a few
            # lines up only ever ran when nothing was passed in. Once a
            # second region/catchment existed (Phase 11's Chamoli valley),
            # any higher-elevation village from a DIFFERENT river system
            # could get counted as "upstream" of this one and pollute its
            # upstream_rainfall reading — the exact opposite of this
            # component's own documented "elevation-order proxy within the
            # same micro-catchment" definition. Filtering explicitly here
            # makes the passed-in-list and query-fallback branches agree,
            # and — as a side effect — shrinks the (already deduplicated,
            # see prefetch_readings above) set of villages this loop looks
            # at to only the ones that were ever a real upstream candidate.
            if v.id != village.id
            and v.catchment_id == village.catchment_id
            and (v.elevation_m or 0) > (village.elevation_m or 0)
        ]
        upstream_count = len(upstream)
        if upstream:
            readings = [_fetch_rainfall(rainfall_provider, v, db, cache=rainfall_cache) for v in upstream]
            valid = [r for r in readings if r is not None]
            if valid:
                best = max(valid, key=lambda r: r.value)
                upstream_max = best.value
                upstream_max_source = best.source
    upstream_component = Component(
        name="upstream_rainfall",
        description=(
            f"Max current rainfall among {upstream_count} village(s) upstream in the same "
            "micro-catchment (elevation-order proxy — see docstring)"
            if upstream_count
            else "No upstream villages in this micro-catchment (this is the highest-elevation village seeded)"
        ),
        raw_value=upstream_max,
        unit="mm/hr",
        source=upstream_max_source,
        normalized_0_1=_clamp01(upstream_max / RAINFALL_CAP_MM_PER_HR),
        weight=weights.upstream_rainfall,
    )

    historical_component = _historical_susceptibility(db, village)
    historical_component.weight = weights.historical_susceptibility

    # Real, RGI-identified nearby glacier's recent mass-balance rate
    # (Phase 14+ follow-up, user-requested: "incorporate the melting rate
    # of nearby glaciers into the risk score"). Unlike glacial_lake_distance_km
    # below (deliberately advisory-only), this IS a weighted component — see
    # app/services/glacial_melt_hazard.py's module docstring for why melt
    # rate is treated differently from raw lake distance. A lookup failure
    # (e.g. unresolvable village geometry) degrades to an honest 0 rather
    # than crashing the whole risk computation, same discipline as the
    # glacial-lake lookup a few lines below.
    try:
        melt_lat, melt_lon = village_latlon(village)
        glacier_melt = nearest_glacier_melt(melt_lat, melt_lon)
    except Exception:
        glacier_melt = None
    glacial_melt_component = Component(
        name="glacial_melt_rate",
        description=(
            glacier_melt.note if glacier_melt else "Glacier melt rate could not be computed for this village."
        ),
        raw_value=(
            glacier_melt.nearest_glacier.recent_mean_mwe_per_yr
            if glacier_melt and glacier_melt.nearest_glacier
            else 0.0
        ),
        unit="m w.e./yr (nearest RGI glacier, 2021-2025 mean)",
        source=DataSource.DERIVED,
        normalized_0_1=glacier_melt.normalized_0_1 if glacier_melt else 0.0,
        weight=weights.glacial_melt_rate,
    )

    components = [
        rainfall_component,
        soil_component,
        upstream_component,
        historical_component,
        glacial_melt_component,
    ]

    score = round(sum(c.weight * c.normalized_0_1 for c in components) * 100, 1)
    score = max(0.0, min(100.0, score))

    thresholds = settings.risk_thresholds
    if score <= thresholds.low_max:
        level = RiskLevel.LOW
    elif score <= thresholds.moderate_max:
        level = RiskLevel.MODERATE
    elif score <= thresholds.high_max:
        level = RiskLevel.HIGH
    else:
        level = RiskLevel.CRITICAL

    confidence = round(sum(c.weight * TIER_CONFIDENCE[c.source] for c in components) * 100, 1)

    lead_time = estimate_lead_time(village, siblings)

    # Real advisory-only field, deliberately not folded into score/level —
    # see app/services/glacial_lake_proximity.py's module docstring for why.
    # Same "degrade honestly" discipline as everything else here: a lookup
    # failure (e.g. a village geometry that can't be resolved) results in an
    # honest None + note, never a crash of the whole risk computation.
    try:
        lat, lon = village_latlon(village)
        glacial_lake = nearest_glacial_lake(lat, lon)
    except Exception:
        glacial_lake = None

    # Real, disclosed, non-calibrated blend of the two glacial fields above —
    # advisory only, see app/services/glacial_melt_hazard.py's module
    # docstring for why this isn't a statistical flash-flood probability.
    glof_indicator = glof_contribution_indicator(glacial_lake, glacier_melt)

    # Real antecedent-precipitation-index (user-requested follow-up, from
    # this project's own competitive-landscape research: "a real API
    # calculation ... would make the SCS-CN AMC classification less of an
    # approximation"). Fetched (or simulated, per
    # GIRIVARSHA_ACTIVE_ANTECEDENT_PROVIDER) BEFORE the SCS-CN call below so
    # its real AMC classification can feed it directly. Never raises — see
    # app/services/antecedent_rainfall.py's own real/simulated/fallback
    # contract — but wrapped here anyway for the same defensive discipline
    # as every other advisory lookup in this function.
    try:
        ant_lat, ant_lon = village_latlon(village)
        antecedent = get_antecedent_rainfall(ant_lat, ant_lon, settings.active_antecedent_provider)
    except Exception:
        antecedent = None

    # Real, SEPARATE SCS-CN runoff estimate (user-requested follow-up, from
    # this project's own competitive-landscape research: "add a real
    # hydrological layer shown alongside the current weighted formula").
    # Uses rainfall_value/soil_value as already resolved above — which
    # means a What-If Simulator override flows through into this estimate
    # too, same as it does for the weighted components. Now also takes the
    # real antecedent-rainfall result above, which drives its AMC
    # classification whenever real data is available. Degrades honestly
    # (see app/services/scs_cn_runoff.py) rather than crashing the whole
    # risk computation if its own precomputed dataset is unavailable.
    try:
        scs_lat, scs_lon = village_latlon(village)
        scs_cn = estimate_runoff(scs_lat, scs_lon, rainfall_value, soil_value, antecedent=antecedent)
    except Exception:
        scs_cn = None

    # Real, THIRD independent indicator (user-requested follow-up, from this
    # project's own competitive-landscape research: "rainfall-intensity-
    # duration threshold rules ... as a third independent indicator
    # alongside the weighted score and SCS-CN runoff"). Uses rainfall_value
    # as already resolved above, so a What-If Simulator override flows
    # through here too, same as it does for scs_cn. Degrades honestly
    # (never crashes the whole risk computation) if the village's region
    # link can't be resolved — rainfall_threshold.py treats an unknown
    # region as "regional proxy" rather than failing.
    try:
        rainfall_threshold = assess_rainfall_threshold(rainfall_value, _region_name(village))
    except Exception:
        rainfall_threshold = None

    return RiskAssessment(
        village_id=village.id,
        score=score,
        level=level,
        confidence_pct=confidence,
        components=components,
        lead_time_minutes=lead_time.minutes,
        lead_time_note=lead_time.note,
        glacial_lake_distance_km=glacial_lake.distance_km if glacial_lake else None,
        glacial_lake_note=(
            glacial_lake.note if glacial_lake else "Glacial lake proximity could not be computed for this village."
        ),
        glof_contribution_pct=glof_indicator.pct,
        glof_contribution_tier=glof_indicator.tier,
        glof_contribution_note=glof_indicator.note,
        scs_cn_curve_number=scs_cn.curve_number_used if scs_cn else None,
        scs_cn_amc_class=scs_cn.amc_class if scs_cn else None,
        scs_cn_hydrologic_soil_group=scs_cn.hydrologic_soil_group if scs_cn else None,
        scs_cn_land_cover=scs_cn.land_cover if scs_cn else None,
        scs_cn_rainfall_depth_mm=scs_cn.rainfall_depth_mm if scs_cn else None,
        scs_cn_runoff_depth_mm=scs_cn.runoff_depth_mm if scs_cn else None,
        scs_cn_runoff_ratio=scs_cn.runoff_ratio if scs_cn else None,
        scs_cn_note=(scs_cn.note if scs_cn else "SCS-CN runoff estimate could not be computed for this village."),
        rainfall_threshold_hours_to_threshold=(
            rainfall_threshold.hours_to_threshold if rainfall_threshold else None
        ),
        rainfall_threshold_status=(rainfall_threshold.status if rainfall_threshold else None),
        rainfall_threshold_applicability=(rainfall_threshold.applicability if rainfall_threshold else None),
        rainfall_threshold_note=(
            rainfall_threshold.note
            if rainfall_threshold
            else "Rainfall intensity-duration threshold could not be computed for this village."
        ),
        antecedent_rainfall_5day_mm=(antecedent.p5_mm if antecedent else None),
        antecedent_rainfall_10day_mm=(antecedent.p10_mm if antecedent else None),
        antecedent_rainfall_20day_mm=(antecedent.p20_mm if antecedent else None),
        antecedent_rainfall_as_of=(antecedent.as_of_date if antecedent else None),
        antecedent_rainfall_source=(antecedent.source if antecedent else None),
        antecedent_rainfall_note=(
            antecedent.note if antecedent else "Antecedent rainfall could not be computed for this village."
        ),
    )


def persist_prediction(db: Session, assessment: RiskAssessment, model_version: ModelVersion) -> RiskPrediction:
    prediction = RiskPrediction(
        village_id=assessment.village_id,
        model_version_id=model_version.id,
        risk_score=assessment.score,
        risk_level=assessment.level,
        confidence_pct=assessment.confidence_pct,
        # The RiskPrediction.lead_time_minutes column is an integer (a
        # historical-record precision choice, not worth a migration for) —
        # rounded here at the DB boundary; the full-precision estimate plus
        # its reasoning stays available via assessment.lead_time_note on the
        # live (unpersisted) RiskAssessment returned by compute_risk_for_village.
        lead_time_minutes=(
            round(assessment.lead_time_minutes) if assessment.lead_time_minutes is not None else None
        ),
        drivers=assessment.drivers_json(),
        input_data_timestamp=assessment.computed_at,
    )
    db.add(prediction)
    db.flush()
    return prediction
