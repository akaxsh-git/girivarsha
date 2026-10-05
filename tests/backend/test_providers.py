"""
Phase 9-10 confidence work: tests for the real Open-Meteo-backed
RealRainfallProvider / RealSoilMoistureProvider (app/providers/base.py) and
the get_rainfall_provider/get_soil_provider factory functions.

No database needed — these are pure unit tests against httpx, with
httpx.get monkeypatched to fake HTTP responses (this sandbox's own network
is blocked from reaching api.open-meteo.com, confirmed via `curl -v` — see
the module docstrings in app/providers/base.py — so these tests prove the
parsing/error-handling logic is correct without depending on a live call
that can't run here; they do NOT prove the live API's real response shape
matches what's mocked below, which is why docs/Data_Sources.md asks the
user to verify the real call once on their own machine).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.providers.base import (  # noqa: E402
    DataSource,
    ProviderUnavailableError,
    RealRainfallProvider,
    RealSoilMoistureProvider,
    SimulatedRainfallProvider,
    SimulatedSoilMoistureProvider,
    get_rainfall_provider,
    get_soil_provider,
)


class _FakeResponse:
    def __init__(self, json_body: dict, status_code: int = 200):
        self._json_body = json_body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("fake error", request=None, response=self)

    def json(self):
        return self._json_body


def test_real_rainfall_provider_parses_a_real_shaped_response(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        assert "api.open-meteo.com" in url
        assert params["latitude"] == 30.7346
        return _FakeResponse({"current": {"time": "2026-09-04T10:00", "precipitation": 3.2, "rain": 2.8}})

    monkeypatch.setattr("app.providers.base.httpx.get", fake_get)

    provider = RealRainfallProvider()
    reading = provider.fetch(lat=30.7346, lon=79.0669)

    assert reading.value == 2.8, "must prefer the 'rain' field over 'precipitation' when both are present"
    assert reading.unit == "mm/hr"
    assert reading.source == DataSource.REAL
    assert reading.provider_name == "open_meteo_rainfall_v1"


def test_real_rainfall_provider_falls_back_to_precipitation_field(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse({"current": {"time": "2026-09-04T10:00", "precipitation": 1.5, "rain": None}})

    monkeypatch.setattr("app.providers.base.httpx.get", fake_get)

    reading = RealRainfallProvider().fetch(lat=30.7, lon=79.0)
    assert reading.value == 1.5


def test_real_rainfall_provider_raises_provider_unavailable_on_http_failure(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse({}, status_code=503)

    monkeypatch.setattr("app.providers.base.httpx.get", fake_get)

    with pytest.raises(ProviderUnavailableError):
        RealRainfallProvider().fetch(lat=30.7, lon=79.0)


def test_real_rainfall_provider_raises_provider_unavailable_on_malformed_body(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse({"unexpected": "shape"})

    monkeypatch.setattr("app.providers.base.httpx.get", fake_get)

    with pytest.raises(ProviderUnavailableError):
        RealRainfallProvider().fetch(lat=30.7, lon=79.0)


def test_real_soil_moisture_provider_parses_and_scales_volumetric_value(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(
            {
                "hourly": {
                    "time": ["2026-09-04T09:00", "2026-09-04T10:00", "2026-09-04T11:00"],
                    "soil_moisture_0_to_1cm": [0.20, 0.28, 0.31],
                }
            }
        )

    monkeypatch.setattr("app.providers.base.httpx.get", fake_get)
    monkeypatch.setattr(
        "app.providers.base.datetime",
        _FrozenDatetime,
    )

    reading = RealSoilMoistureProvider().fetch(lat=30.7, lon=79.0)
    assert reading.value == 28.0, "0.28 m3/m3 at the matched hour should scale to 28.0 volumetric pct"
    assert reading.source == DataSource.REAL
    assert "volumetric" in reading.unit


class _FrozenDatetime:
    """Minimal stand-in so 'now' resolves to the 10:00 slot in the fake
    hourly series above, without depending on the real wall-clock hour."""

    @staticmethod
    def now(tz=None):
        import datetime as _dt

        return _dt.datetime(2026, 9, 4, 10, 17, tzinfo=tz)


def test_real_soil_moisture_provider_raises_provider_unavailable_on_null_value(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        return _FakeResponse({"hourly": {"time": ["2026-09-04T10:00"], "soil_moisture_0_to_1cm": [None]}})

    monkeypatch.setattr("app.providers.base.httpx.get", fake_get)
    monkeypatch.setattr("app.providers.base.datetime", _FrozenDatetime)

    with pytest.raises(ProviderUnavailableError):
        RealSoilMoistureProvider().fetch(lat=30.7, lon=79.0)


def test_get_rainfall_provider_factory_respects_setting():
    assert isinstance(get_rainfall_provider("real"), RealRainfallProvider)
    assert isinstance(get_rainfall_provider("simulated"), SimulatedRainfallProvider)
    assert isinstance(get_rainfall_provider("some_typo"), SimulatedRainfallProvider), (
        "an unrecognized setting must fail safe to simulated, not crash the app"
    )


def test_get_soil_provider_factory_respects_setting():
    assert isinstance(get_soil_provider("real"), RealSoilMoistureProvider)
    assert isinstance(get_soil_provider("simulated"), SimulatedSoilMoistureProvider)
    assert isinstance(get_soil_provider("anything_else"), SimulatedSoilMoistureProvider)
