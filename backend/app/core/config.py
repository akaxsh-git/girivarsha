"""
Application configuration.

All tunables that the product spec calls out as "must be configurable" live
here and are overridable via environment variables / .env — never hard-coded
in business logic. See ../../.env.example for the full list of variables.
"""
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute, not relative to cwd — so `backend/.env` is found whether the
# process is started from `backend/` (uvicorn/alembic's usual case) or from
# the repo root (pytest's usual case). A relative "env_file" silently found
# nothing when pytest ran from the repo root, which made every DB-backed
# test skip with a confusing "database not configured" reason.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class RiskThresholds(BaseSettings):
    """0-100 risk score band boundaries. Configurable per problem-statement item 8."""

    low_max: int = Field(default=30, description="0..low_max = LOW")
    moderate_max: int = Field(default=50, description="low_max+1..moderate_max = MODERATE")
    high_max: int = Field(default=70, description="moderate_max+1..high_max = HIGH")
    # anything above high_max = CRITICAL


class RiskWeights(BaseSettings):
    """
    Weights for the Phase 4 transparent baseline risk scorer
    (app/services/risk_engine.py) — a plain weighted sum, deliberately NOT
    a black box, so every score can be explained component-by-component
    (problem-statement items 9/35). Must sum to 1.0 — validated in
    tests/backend/test_risk.py rather than at import time, so a
    misconfigured .env fails a visible test instead of crashing the app.

    Kept configurable (not hard-coded in risk_engine.py) per item 8, same as
    RiskThresholds above — a reviewer or a future maintainer can
    retune these without touching code.
    """

    rainfall_intensity: float = Field(default=0.30, description="Village's own current rainfall rate")
    soil_moisture: float = Field(default=0.20, description="Village's own soil saturation")
    upstream_rainfall: float = Field(
        default=0.25,
        description="Max rainfall among villages upstream in the same micro-catchment — this is what makes risk catchment-aware, not per-village-isolated (item 7)",
    )
    historical_susceptibility: float = Field(
        default=0.15, description="Derived from real recorded historical events near this village"
    )
    glacial_melt_rate: float = Field(
        default=0.10,
        description=(
            "Real, RGI-identified nearby glacier's recent (2021-2025 mean) mass-balance rate "
            "(app/services/glacial_melt_hazard.py) — user-requested follow-up. Deliberately the "
            "smallest weight: a genuine physical melt-rate signal, but a slow climate-scale one, "
            "not an immediate storm trigger the way rainfall/soil moisture are. Rainfall + soil "
            "moisture still carry half the total weight between them."
        ),
    )

    # Rebalanced from the original 0.35/0.25/0.25/0.15 (still sums to 1.0) when
    # glacial_melt_rate was added, per docs/Build_Status.md's "glacier melt" entry —
    # rainfall/soil moisture each gave up a little weight; upstream/historical
    # were left untouched since neither is superseded by the new component.


class SensorThresholds(BaseSettings):
    """
    Freshness thresholds for a sensor node's live status (Phase 8, item 24).
    Status is never trusted from a stored column alone — it's recomputed
    from `now - last_seen_at` on every GET /sensors call, same philosophy
    as risk scores never being served stale/cached without recomputation.
    """

    online_max_seconds: int = Field(default=300, description="last_seen_at newer than this = online")
    stale_max_seconds: int = Field(
        default=1800, description="last_seen_at newer than this (but older than online) = stale; older still = offline"
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_prefix="GIRIVARSHA_", env_nested_delimiter="__", extra="ignore"
    )

    app_name: str = "Girivarsha"
    tagline: str = "Detect -> Predict -> Explain -> Act"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"

    # Comma-separated list of allowed browser origins for the dashboard(s).
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Postgres + PostGIS connection string. Left unset in Phase 1 (no DB wired yet).
    database_url: str | None = None

    # Feature flag: which data providers are active. Phase 1 ships only the
    # simulated provider; real adapters are added as Phase 2/3 land per the
    # DataProvider adapter pattern (see app/providers/base.py).
    active_rainfall_provider: str = "simulated"
    active_soil_provider: str = "simulated"

    # Antecedent-precipitation-index follow-up (user-requested, from this
    # project's own competitive-landscape research): same opt-in, degrade-
    # honestly pattern as the two providers above. "simulated" (default)
    # makes zero live network calls; "real" fetches actual historical daily
    # rainfall from NASA POWER (free, no key) to classify Antecedent
    # Moisture Condition for the SCS-CN layer from genuine rainfall history
    # instead of a single current soil-moisture reading. See
    # app/services/antecedent_rainfall.py for the real data-latency caveat
    # this source has (its most recent ~1-2 weeks are not yet processed).
    active_antecedent_provider: str = "simulated"

    # SMS-reach follow-up (user-requested): same opt-in-only, degrade-honestly
    # pattern as the rainfall/soil providers above, applied to outbound SMS
    # instead of inbound readings — see app/providers/notification.py.
    # "log_only" (default) never claims a message was actually delivered;
    # "twilio" activates real delivery only if all three Twilio credentials
    # below are also set (get_notification_provider falls back to log_only
    # otherwise, exactly like a mistyped active_rainfall_provider does).
    active_sms_provider: str = "log_only"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None

    risk_thresholds: RiskThresholds = RiskThresholds()
    risk_weights: RiskWeights = RiskWeights()
    sensor_thresholds: SensorThresholds = SensorThresholds()

    build_phase: str = (
        "Phase 14 complete (original 14-phase plan) + user-requested follow-ups: "
        "sensor network wired into risk engine, What-If Simulator, glacier melt-rate "
        "risk component + GLOF contribution indicator, all-villages evacuation route summary"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
