"""
Shared backend test fixtures.

Global autouse network-safety net (real-regional-data fallback follow-up,
user-requested): GET /sensors (app/api/routes/sensors.py) can now make a
REAL httpx.get call to api.open-meteo.com whenever an offline/stale sensor
needs a regional fallback estimate — same real adapters (RealRainfallProvider
/ RealSoilMoistureProvider) the risk engine already used. This build
sandbox's own outbound network to that host is blocked (see
app/providers/base.py's module docstrings — confirmed via `curl -v`), so an
UNMOCKED real call here doesn't fail fast — it hangs for the full httpx
timeout (8s) per unique village/sensor-type combo. Several existing tests
across this whole test suite provision sensors/villages that start
deliberately offline (the honest default), so without this fixture, almost
any GET /sensors call anywhere in the suite could pay that 8s tax — this
was caught live: a full sandboxed test run of test_sensors.py alone hung
past 90s once the fallback feature landed, entirely from this.

This autouse fixture makes httpx.get raise an immediate, honest connection
error by default, for every test in this directory, UNLESS a test
explicitly monkeypatches app.providers.base.httpx.get itself (e.g.
test_providers.py and test_sensors.py's own regional-fallback tests, which
need to control the fake response's shape) — a test's own
monkeypatch.setattr call simply overrides this one for the rest of that
test, and pytest's monkeypatch fixture reverts both afterward regardless of
ordering.

This changes nothing about real behaviour on a real network: the real
adapters and every route that calls them already treat a failed/unreachable
fetch as an honest, non-fatal degradation (see ProviderUnavailableError
handling in each) — this fixture just makes that same failure path fast in
this sandbox instead of slow, so tests that have nothing to do with
Open-Meteo aren't held hostage by an environment restriction that has
nothing to do with what they're testing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import httpx  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fail_fast_on_real_open_meteo_calls_by_default(monkeypatch):
    def _immediate_connect_error(url, params=None, timeout=None):
        raise httpx.ConnectError(
            "blocked in this build sandbox by default — see tests/backend/conftest.py"
        )

    monkeypatch.setattr("app.providers.base.httpx.get", _immediate_connect_error, raising=False)
    yield
