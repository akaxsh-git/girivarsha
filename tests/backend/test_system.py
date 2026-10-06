"""Phase 1 smoke tests: app boots, health/version report correctly, and the
shared `not_implemented()` helper (app/api/routes/not_implemented.py) — used
by any endpoint whose contract is defined but not yet backed by real logic —
still raises an honest 501 with the documented shape. As of the What-If
Simulator follow-up (POST /simulate, previously the last endpoint using this
helper), no route in this build currently calls it — every endpoint listed
in docs/API_Documentation.md is real. This test exercises the helper
directly rather than pointing at a since-implemented path, so it keeps
guarding the "honest 501, never fabricated data" pattern for whichever
endpoint needs it next (see docs/Future_Work.md for what's still open)."""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.api.routes.not_implemented import not_implemented  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["app"] == "Girivarsha"
    assert "not an official government warning mechanism" in body["disclaimer"]


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_version_reports_configurable_thresholds():
    r = client.get("/api/v1/version")
    body = r.json()
    assert body["risk_thresholds"] == {"low_max": 30, "moderate_max": 50, "high_max": 70}
    assert body["active_model"]["trained"] is False  # baseline is a formula, not a fitted model — never claim otherwise


def test_not_implemented_helper_raises_honest_501_not_fake_data():
    # villages/catchments/historical-events graduated to real DB-backed
    # endpoints in Phase 2, risk/alerts in Phase 4, sensors in Phase 8,
    # model/explanation in Phase 9, regions in Phase 11, evacuation/replay
    # in Phase 12, and the What-If Simulator (POST /simulate) in this
    # follow-up — see test_villages.py, test_risk.py, test_sensors.py,
    # test_explanation.py, test_regions.py, test_evacuation.py,
    # test_replay.py, and test_simulate.py. No route currently calls this
    # helper, but whatever's still open in docs/Future_Work.md (e.g. device
    # auth) must still fail this way, not with fabricated data, if it ships
    # as a stub before it's really built.
    with pytest.raises(HTTPException) as exc_info:
        not_implemented("/api/v1/example-not-yet-built", planned_phase="some future phase")
    assert exc_info.value.status_code == 501
    assert exc_info.value.detail["status"] == "not_implemented"
    assert exc_info.value.detail["endpoint"] == "/api/v1/example-not-yet-built"


def test_simulated_rainfall_provider_is_labelled_simulated():
    r = client.get("/api/v1/demo/rainfall-sample")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "simulated"
    assert body["value"] >= 0


def test_health_accepts_head_for_uptime_monitors():
    # UptimeRobot and similar monitors probe with HEAD; a 405 there reads as "down".
    assert client.head("/api/v1/health").status_code == 200
