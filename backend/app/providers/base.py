"""
DataProvider adapter interface (problem-statement item 6: Data Reality Requirement).

Every external data category (rainfall, soil moisture, water level, ...) is
accessed through a small abstract interface so that:

  * a REAL provider (hits a public API / dataset) and a SIMULATED provider
    (synthetic, clearly labelled) are interchangeable at runtime via config,
  * the rest of the system never has to know or care which one is active,
  * we can never accidentally present simulated numbers as if they were real
    observations - every reading carries an explicit `source` tag.

Phase 1 ships the interface plus one trivial simulated rainfall provider, to
prove the pattern end-to-end and give the risk engine (Phase 4) something to
depend on. Real adapters (IMD / NASA GPM-IMERG / SMAP / ...) are added in
Phase 2-3 behind this same interface; nothing above this layer should need
to change when that happens.
"""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import httpx


class DataSource(str, Enum):
    """Provenance tag - required on every reading, never omitted or faked."""

    REAL = "real"
    SIMULATED = "simulated"
    DERIVED = "derived"


@dataclass
class Reading:
    value: float
    unit: str
    source: DataSource
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    provider_name: str = "unknown"


class DataProvider(ABC):
    """Base adapter. One concrete subclass per (data category x backing source)."""

    name: str = "base"

    # Performance follow-up (user-requested: GET /risk/map measured at ~48s
    # end-to-end with real providers active): whether concurrent calls to
    # fetch() on the SAME instance, from multiple threads at once, are safe.
    # False is the conservative default. A subclass may only declare True if
    # fetch() reads/writes no per-instance mutable state — see
    # RealRainfallProvider/RealSoilMoistureProvider below, where every call
    # is an independent, stateless httpx.get with nothing shared across
    # calls. SimulatedRainfallProvider/SimulatedSoilMoistureProvider stay
    # False because they share a single `random.Random` instance across
    # calls, and random.Random's internal state (the Box-Muller "spare"
    # value gauss() caches between calls) is not safe to touch from more
    # than one thread at once. Consulted by
    # app/services/risk_engine.py::prefetch_readings to decide which
    # provider calls are safe to parallelize — nothing else in this app
    # calls fetch() from a thread other than the request's own.
    thread_safe: bool = False

    @abstractmethod
    def fetch(self, *, lat: float, lon: float) -> Reading:
        """Return the latest reading for a given point. Must raise
        ProviderUnavailableError (not a silent default) if the source cannot
        be reached, so the risk engine's fallback hierarchy (item 13) can
        react instead of quietly consuming a stale/wrong value."""
        raise NotImplementedError


class ProviderUnavailableError(RuntimeError):
    """Raised when a provider cannot produce a reading right now."""


class SimulatedRainfallProvider(DataProvider):
    """
    Clearly-labelled synthetic rainfall provider used for local development,
    tests and the demo/what-if simulator. Never claims to be a real
    observation - `Reading.source` is always DataSource.SIMULATED.
    """

    name = "simulated_rainfall_v0"

    def __init__(self, seed: int | None = None, base_mm_per_hr: float = 4.0) -> None:
        self._rng = random.Random(seed)
        self._base = base_mm_per_hr

    def fetch(self, *, lat: float, lon: float) -> Reading:
        # Deterministic-ish noise around a base rate; good enough for a
        # skeleton-phase smoke test. Replaced by a real hydrology-aware
        # generator in Phase 4 (what-if simulator) and by a real API adapter
        # (RealRainfallProvider) in Phase 2/3 where public data is available.
        value = max(0.0, self._rng.gauss(self._base, self._base * 0.6))
        return Reading(
            value=round(value, 1),
            unit="mm/hr",
            source=DataSource.SIMULATED,
            provider_name=self.name,
        )


OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_TIMEOUT_SECONDS = 8.0


class RealRainfallProvider(DataProvider):
    """
    Real adapter backed by Open-Meteo's free forecast API
    (https://open-meteo.com/en/docs) — no API key required for
    non-commercial use, which is what actually makes wiring this in
    feasible for this build. Uses the `current` block's `rain`
    field (mm, falling back to `precipitation` — rain+showers+snow — if
    `rain` is absent) as an approximation of the current mm/hr rate, the
    same unit convention SimulatedRainfallProvider already used.

    Honesty notes:
    - This is real, live, third-party weather data — not a fabricated or
      hard-coded number — but it is a general-purpose global forecast
      model's nowcast, not a calibrated rain-gauge or radar reading at the
      village itself. It is a genuine upgrade in provenance (REAL vs.
      SIMULATED), not a claim of ground-truth precision.
    - This exact HTTP call could not be executed inside the sandbox this
      code was built in — outbound network to api.open-meteo.com is
      blocked there (confirmed via `curl -v`; same restriction already
      documented for the OpenTopography DEM download, see
      docs/GIS_Methodology.md). Unlike OpenTopography this needs no API
      key, so verifying it is a single `curl` away on any normal
      connection — see docs/Data_Sources.md for the exact command.
    """

    name = "open_meteo_rainfall_v1"
    thread_safe = True  # stateless per-call httpx.get — see DataProvider.thread_safe

    def __init__(self, timeout_seconds: float = OPEN_METEO_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout_seconds

    def fetch(self, *, lat: float, lon: float) -> Reading:
        try:
            response = httpx.get(
                OPEN_METEO_BASE_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "precipitation,rain",
                    "timezone": "UTC",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
            current = payload["current"]
            value = current.get("rain")
            if value is None:
                value = current["precipitation"]
            value = float(value)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailableError(
                f"Open-Meteo rainfall request failed: {exc!r}"
            ) from exc

        return Reading(
            value=round(value, 1),
            unit="mm/hr",
            source=DataSource.REAL,
            provider_name=self.name,
        )


class SimulatedSoilMoistureProvider(DataProvider):
    """
    Clearly-labelled synthetic soil-moisture provider, same honesty
    contract as SimulatedRainfallProvider above. Used by the Phase 4
    baseline risk engine (app/services/risk_engine.py) until a real adapter
    (e.g. SMAP/NASA) is wired up behind this same interface.
    """

    name = "simulated_soil_moisture_v0"

    def __init__(self, seed: int | None = None, base_pct: float = 45.0) -> None:
        self._rng = random.Random(seed)
        self._base = base_pct

    def fetch(self, *, lat: float, lon: float) -> Reading:
        value = min(100.0, max(0.0, self._rng.gauss(self._base, 15.0)))
        return Reading(
            value=round(value, 1),
            unit="pct",
            source=DataSource.SIMULATED,
            provider_name=self.name,
        )


class RealSoilMoistureProvider(DataProvider):
    """
    Real adapter backed by Open-Meteo's free forecast API. Soil moisture has
    no "current" field on Open-Meteo — only `hourly` (`soil_moisture_0_to_1cm`,
    volumetric water content in m3/m3 for the top 0-1cm layer, from its land
    -surface model, not a physical soil-moisture sensor). This fetches the
    next 24 hourly values and picks the slot matching the current UTC hour.

    Honesty note on the number itself: it is reported here scaled to 0-100
    (value * 100) as an honest **volumetric-percent** figure — e.g. 0.25
    m3/m3 -> 25.0. This is NOT "percent of saturation" or a plant-available
    -water percentage; those need soil-type-specific field-capacity data
    this API doesn't provide, and claiming them would overstate precision
    this pipeline doesn't have. Same REAL-vs-ground-truth and sandbox
    -network caveats as RealRainfallProvider above.
    """

    name = "open_meteo_soil_moisture_v1"
    thread_safe = True  # stateless per-call httpx.get — see DataProvider.thread_safe

    def __init__(self, timeout_seconds: float = OPEN_METEO_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout_seconds

    def fetch(self, *, lat: float, lon: float) -> Reading:
        try:
            response = httpx.get(
                OPEN_METEO_BASE_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": "soil_moisture_0_to_1cm",
                    "forecast_days": 1,
                    "timezone": "UTC",
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
            hourly = payload["hourly"]
            times = hourly["time"]
            values = hourly["soil_moisture_0_to_1cm"]
            now_hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:00")
            try:
                idx = times.index(now_hour)
            except ValueError:
                idx = 0  # no exact match (e.g. clock skew) — nearest available slot
            volumetric_m3_per_m3 = values[idx]
            if volumetric_m3_per_m3 is None:
                raise ValueError("Open-Meteo returned a null soil_moisture_0_to_1cm value")
            volumetric_m3_per_m3 = float(volumetric_m3_per_m3)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderUnavailableError(
                f"Open-Meteo soil-moisture request failed: {exc!r}"
            ) from exc

        pct = min(100.0, max(0.0, volumetric_m3_per_m3 * 100.0))
        return Reading(
            value=round(pct, 1),
            unit="pct (volumetric water content)",
            source=DataSource.REAL,
            provider_name=self.name,
        )


def get_rainfall_provider(active: str) -> DataProvider:
    """Reads the GIRIVARSHA_ACTIVE_RAINFALL_PROVIDER setting ("simulated" |
    "real") and returns the matching provider. Any unrecognized value falls
    back to simulated rather than crashing the app — a typo in .env should
    degrade to the honestly-labelled default, not take the API down."""
    if active == "real":
        return RealRainfallProvider()
    return SimulatedRainfallProvider()


def get_soil_provider(active: str) -> DataProvider:
    """Same fallback philosophy as get_rainfall_provider above."""
    if active == "real":
        return RealSoilMoistureProvider()
    return SimulatedSoilMoistureProvider()
