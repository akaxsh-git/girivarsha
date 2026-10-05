"""Wind-field endpoint tests (no database needed: the route only calls
Open-Meteo, which is mocked here — never a live call)."""
import sys
from pathlib import Path

import time

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.routes import wind  # noqa: E402

_app = FastAPI()
_app.include_router(wind.router, prefix="/api/v1")
client = TestClient(_app)

BOUNDS = {"south": 30.4, "west": 78.8, "north": 30.8, "east": 79.2, "nx": 2, "ny": 2}


class _Resp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _entry(speed, direction):
    return {"current": {"time": "2026-10-05T14:00", "wind_speed_10m": speed,
                        "wind_direction_10m": direction, "wind_gusts_10m": speed * 1.5}}


@pytest.fixture(autouse=True)
def _clear():
    wind._cache.clear()
    yield
    wind._cache.clear()


def test_components_from_meteorological_direction():
    u, v = wind.wind_components(10, 0)  # from north -> blowing south
    assert abs(u) < 1e-9 and v == pytest.approx(-10)
    u, v = wind.wind_components(10, 270)  # from west -> blowing east
    assert u == pytest.approx(10) and abs(v) < 1e-9


def test_returns_real_tagged_grid(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _Resp([_entry(4.0, 270.0) for _ in range(4)])

    monkeypatch.setattr("app.api.routes.wind.httpx.get", fake_get)
    r = client.get("/api/v1/wind", params=BOUNDS)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "real" and len(body["points"]) == 4
    assert body["points"][0]["u"] == pytest.approx(4.0)
    assert body["south"] <= 30.4 and body["north"] >= 30.8  # snapped outward only
    assert len(calls) == 1 and calls[0]["wind_speed_unit"] == "ms"


def test_second_identical_request_is_cached(monkeypatch):
    n = {"c": 0}

    def fake_get(url, params=None, timeout=None):
        n["c"] += 1
        return _Resp([_entry(1.0, 90.0) for _ in range(4)])

    monkeypatch.setattr("app.api.routes.wind.httpx.get", fake_get)
    client.get("/api/v1/wind", params=BOUNDS)
    client.get("/api/v1/wind", params=BOUNDS)
    assert n["c"] == 1


def test_upstream_failure_is_503_not_invented_data(monkeypatch):
    def boom(url, params=None, timeout=None):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("app.api.routes.wind.httpx.get", boom)
    r = client.get("/api/v1/wind", params=BOUNDS)
    assert r.status_code == 503


def test_malformed_upstream_payload_is_503(monkeypatch):
    monkeypatch.setattr("app.api.routes.wind.httpx.get",
                        lambda url, params=None, timeout=None: _Resp([{"nope": 1}] * 4))
    assert client.get("/api/v1/wind", params=BOUNDS).status_code == 503


def test_rejects_bad_bounds():
    assert client.get("/api/v1/wind", params={**BOUNDS, "south": 31, "north": 30}).status_code == 422
    assert client.get("/api/v1/wind", params={**BOUNDS, "south": 20, "north": 30}).status_code == 422


def test_429_is_retried_once_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.api.routes.wind._RETRY_DELAY_SECONDS", 0)
    seq = [429, 200]

    class R(_Resp):
        def __init__(self, code):
            super().__init__([_entry(2.0, 0.0) for _ in range(4)])
            self.status_code = code

    monkeypatch.setattr("app.api.routes.wind.httpx.get", lambda url, params=None, timeout=None: R(seq.pop(0)))
    r = client.get("/api/v1/wind", params=BOUNDS)
    assert r.status_code == 200 and r.json()["stale"] is False


def test_serves_older_real_grid_flagged_stale_when_upstream_fails(monkeypatch):
    monkeypatch.setattr("app.api.routes.wind.httpx.get",
                        lambda url, params=None, timeout=None: _Resp([_entry(3.0, 90.0) for _ in range(4)]))
    assert client.get("/api/v1/wind", params=BOUNDS).json()["stale"] is False
    # age the cache entry past the fresh window, then break upstream
    for k, (t, pts, vt) in list(wind._cache.items()):
        wind._cache[k] = (t - 2 * 3600, pts, vt)

    def boom(url, params=None, timeout=None):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("app.api.routes.wind.httpx.get", boom)
    r = client.get("/api/v1/wind", params=BOUNDS)
    assert r.status_code == 200 and r.json()["stale"] is True and r.json()["source"] == "real"


def test_too_old_cache_is_not_served(monkeypatch):
    monkeypatch.setattr("app.api.routes.wind.httpx.get",
                        lambda url, params=None, timeout=None: _Resp([_entry(3.0, 90.0) for _ in range(4)]))
    client.get("/api/v1/wind", params=BOUNDS)
    for k, (t, pts, vt) in list(wind._cache.items()):
        wind._cache[k] = (t - 7 * 3600, pts, vt)

    def boom(url, params=None, timeout=None):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("app.api.routes.wind.httpx.get", boom)
    assert client.get("/api/v1/wind", params=BOUNDS).status_code == 503
