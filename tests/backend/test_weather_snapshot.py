"""Hourly weather snapshot: providers prefer a fresh stored REAL reading,
fall back to the live call otherwise, and report age honestly. Offline."""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.providers import base, weather_cache  # noqa: E402
from app.providers.base import DataSource, RealRainfallProvider, RealSoilMoistureProvider  # noqa: E402
from app.providers.weather_cache import lookup as real_lookup  # noqa: E402  (captured before conftest patches it)

NOW = datetime.now(timezone.utc)


def _snap(value, unit, minutes_old=20):
    return weather_cache.Snapshot(value=value, unit=unit, fetched_at=NOW - timedelta(minutes=minutes_old),
                                  provider_name="x")


def _no_http(*a, **k):
    raise AssertionError("live Open-Meteo call should not happen when a fresh snapshot exists")


def test_rainfall_uses_snapshot_without_live_call(monkeypatch):
    monkeypatch.setattr("app.providers.weather_cache.lookup", lambda kind, lat, lon, **k: _snap(3.24, "mm/hr"))
    monkeypatch.setattr("app.providers.base.httpx.get", _no_http)
    r = RealRainfallProvider().fetch(lat=30.73, lon=79.07)
    assert r.source == DataSource.REAL and r.value == 3.2
    assert r.provider_name.endswith(weather_cache.SNAPSHOT_SUFFIX)


def test_soil_uses_snapshot(monkeypatch):
    monkeypatch.setattr("app.providers.weather_cache.lookup", lambda kind, lat, lon, **k: _snap(31.0, "pct"))
    monkeypatch.setattr("app.providers.base.httpx.get", _no_http)
    assert RealSoilMoistureProvider().fetch(lat=30.7, lon=79.0).value == 31.0


def test_no_snapshot_falls_back_to_live_call_and_its_honest_failure():
    # conftest: lookup -> None, httpx.get -> ConnectError
    with pytest.raises(base.ProviderUnavailableError):
        RealRainfallProvider().fetch(lat=30.7, lon=79.0)


def test_lookup_without_database_returns_none(monkeypatch):
    def boom():
        raise RuntimeError("no db")

    monkeypatch.setattr("app.models.database.get_engine", boom)
    assert real_lookup("rainfall", 30.7, 79.0) is None


def test_snapshot_note_reports_age():
    from app.services.risk_engine import _snapshot_note

    reading = base.Reading(value=1, unit="mm/hr", source=DataSource.REAL,
                           observed_at=NOW - timedelta(minutes=25),
                           provider_name="open_meteo_rainfall_v1" + weather_cache.SNAPSHOT_SUFFIX)
    note = _snapshot_note(reading)
    assert "hourly snapshot" in note and ("25 min" in note or "26 min" in note)
    live = base.Reading(value=1, unit="mm/hr", source=DataSource.REAL, provider_name="open_meteo_rainfall_v1")
    assert _snapshot_note(live) == "" and _snapshot_note(None) == ""


def _load_script():
    spec = importlib.util.spec_from_file_location("fetch_weather_snapshot", ROOT / "scripts" / "fetch_weather_snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_parses_batched_payload_and_skips_missing_values():
    mod = _load_script()
    fetched = datetime(2026, 10, 6, 9, 30, tzinfo=timezone.utc)
    points = [(30.735, 79.067), (30.28, 78.98)]
    payload = [
        {"current": {"time": "2026-10-06T09:30", "rain": 1.5},
         "hourly": {"time": ["2026-10-06T08:00", "2026-10-06T09:00"], "soil_moisture_0_to_1cm": [0.2, 0.31]}},
        {"current": {"time": "2026-10-06T09:30", "rain": None, "precipitation": None},
         "hourly": {"time": ["2026-10-06T09:00"], "soil_moisture_0_to_1cm": [None]}},
    ]
    rows = mod.rows_from(points, payload, fetched)
    assert len(rows) == 2  # second point had nothing real -> nothing written
    soil = next(r for r in rows if r["kind"] == "soil_moisture")
    assert soil["value"] == pytest.approx(31.0) and soil["model_time"] == "2026-10-06T09:00"
