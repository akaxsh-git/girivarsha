"""
Phase 13: explicit failure/fallback testing.

The original SIH26192 problem-statement item 31 text (the exact "nine
failure modes" list) is not available in this build environment — two
web searches for it during this project turned up nothing publicly
indexed, and it isn't stored anywhere in this repo either. Rather than
fabricate a list and pretend it's the source text, this suite instead
derives nine real, concrete failure modes directly from THIS app's own
architecture — specifically the fallback hierarchy already documented in
`docs/Architecture.md` ("Sensor-failure / fallback hierarchy, problem
-statement item 13") and the real degrade-paths that already exist (or,
in one case below, didn't exist until this suite found the gap) in the
provider, risk-engine, sensor-ingestion, and MQTT-bridge code. Each mode
is tested for the same property: the app degrades honestly (no crash, no
fabricated data, clear tagging/status) rather than failing silently,
crashing the whole process, or presenting a guess as a fact.

Four of the nine modes already had dedicated regression tests elsewhere
in the suite before this file existed (sensor never-reported, sensor
stale, unregistered device, invalid source tag) — this file references
where those live rather than duplicating them, and adds tests for the
five modes that had no dedicated failure-path test yet. One of those five
(mode 5, malformed sensor timestamp) turned out to be a REAL bug, not
just a missing test: `POST /sensor-reading` crashed with a bare,
unhelpful 500 on a malformed `observed_at` string before this work — see
the fix in `app/api/routes/sensors.py` and the git history for this file.
That is exactly the kind of thing Phase 13 is for.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.models.database import DatabaseNotConfiguredError, get_engine  # noqa: E402

try:
    _engine = get_engine()
    with _engine.connect():
        pass
    _db_available = True
    _skip_reason = ""
except DatabaseNotConfiguredError as exc:
    _db_available = False
    _skip_reason = str(exc)
except Exception as exc:  # pragma: no cover
    _db_available = False
    _skip_reason = f"Database configured but unreachable: {exc}"

pytestmark = pytest.mark.skipif(not _db_available, reason=_skip_reason)

from fastapi.testclient import TestClient  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.main import app  # noqa: E402
from app.models.database import session_scope  # noqa: E402
from app.models.orm import Sensor, SensorReading, SensorStatus, SensorType, Village  # noqa: E402
from app.providers.base import ProviderUnavailableError  # noqa: E402
from app.api.routes.sensors import hash_device_api_key  # noqa: E402
from app.services import glacial_lake_proximity as glp  # noqa: E402
from app.services.risk_engine import compute_risk_for_village  # noqa: E402

client = TestClient(app)


def _village_id(name: str) -> int:
    villages = client.get("/api/v1/villages").json()
    matches = [v for v in villages if v["name"] == name]
    assert matches, f"expected seeded village {name!r} not found — has scripts/seed_pilot_region.py run?"
    return matches[0]["id"]


# ---------------------------------------------------------------------------
# Mode 1: a provisioned sensor node that has never reported.
# Already covered — see tests/backend/test_sensors.py::
#   test_provisioned_but_never_reported_sensor_is_honestly_offline
# Asserts: status == "offline", last_value is None (never fabricated).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Mode 2: a sensor whose last reading has gone stale (old, but not so old
# it's "offline").
# Already covered — see tests/backend/test_sensors.py::
#   test_stale_reading_reports_stale_not_online
# Asserts: status is recomputed live from freshness on every request, never
# trusted from a stored column.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Mode 3: an unregistered device attempts to report a reading.
# Already covered — see tests/backend/test_sensors.py::
#   test_unregistered_device_gets_a_clear_404_not_a_silent_accept
# Asserts: 404, not a silent auto-provision.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Mode 4: a sensor payload declares an unrecognized provenance tag.
# Already covered — see tests/backend/test_sensors.py::
#   test_invalid_source_is_rejected_not_silently_stored
# Asserts: 422, not silently stored as if it were real/simulated/derived.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Mode 5: a sensor payload carries a malformed observed_at timestamp.
# NEW test — this is the real bug this suite found and fixed (see module
# docstring). Before the fix, this crashed with a bare 500.
#
# Device-authentication follow-up (user-requested) found a second, smaller
# real bug while adding Mode 14 above: these two tests originally posted
# against the real seeded `esp32-kedarnath-rain-01` device, silently
# assuming it stays keyless forever. That assumption broke the moment
# anyone ran scripts/rotate_sensor_api_keys.py against a real database
# (which the device-authentication follow-up's own live verification did,
# in this very sandbox) — the device gained a real key, and both tests
# started failing with 401 instead of the timestamp-validation outcomes
# they're actually testing. Fixed by giving these tests their own
# dedicated, always-keyless throwaway sensor, same discipline
# test_sensors.py already uses for TEST_DEVICE_ID/STALE_DEVICE_ID — a
# malformed-timestamp test has nothing to do with authentication and
# shouldn't depend on a real fleet device's current key-rotation state.
# ---------------------------------------------------------------------------
_MALFORMED_TS_TEST_DEVICE_ID = "test-failure-mode-5-observed-at"


@pytest.fixture()
def _keyless_test_sensor():
    with session_scope() as db:
        village = db.scalar(select(Village).where(Village.name == "Kedarnath"))
        assert village is not None
        existing = db.scalar(select(Sensor).where(Sensor.external_device_id == _MALFORMED_TS_TEST_DEVICE_ID))
        if existing is None:
            db.add(
                Sensor(
                    external_device_id=_MALFORMED_TS_TEST_DEVICE_ID,
                    village_id=village.id,
                    sensor_type=SensorType.RAINFALL,
                    status=SensorStatus.OFFLINE,
                    last_seen_at=None,
                    api_key_hash=None,  # deliberately keyless — see comment above
                )
            )
        else:
            existing.api_key_hash = None
        db.commit()

    yield _MALFORMED_TS_TEST_DEVICE_ID

    with session_scope() as db:
        sensor = db.scalar(select(Sensor).where(Sensor.external_device_id == _MALFORMED_TS_TEST_DEVICE_ID))
        if sensor is not None:
            db.execute(SensorReading.__table__.delete().where(SensorReading.sensor_id == sensor.id))
            db.delete(sensor)
        db.commit()


def test_malformed_observed_at_gets_a_clean_422_not_a_crash(_keyless_test_sensor):
    r = client.post(
        "/api/v1/sensor-reading",
        json={
            "external_device_id": _keyless_test_sensor,
            "value": 5.0,
            "unit": "mm/hr",
            "source": "simulated",
            "observed_at": "definitely-not-a-timestamp",
        },
    )
    assert r.status_code == 422, (
        "a malformed timestamp from a misbehaving node must be rejected cleanly, "
        "not crash the request with an unhandled 500"
    )
    assert "observed_at" in r.json()["detail"]


def test_missing_observed_at_still_works_and_defaults_to_now(_keyless_test_sensor):
    """Sanity check alongside mode 5: omitting the optional field entirely
    (the common real-world case — most publishers won't set it) must keep
    working exactly as before this fix."""
    r = client.post(
        "/api/v1/sensor-reading",
        json={"external_device_id": _keyless_test_sensor, "value": 5.0, "unit": "mm/hr", "source": "simulated"},
    )
    assert r.status_code == 201


# ---------------------------------------------------------------------------
# Mode 6: the active REAL weather provider (Open-Meteo) becomes unreachable
# mid-request — the exact scenario docs/Architecture.md's "Sensor-failure /
# fallback hierarchy (problem-statement item 13)" diagram describes: LOCAL
# SENSOR unavailable -> ... -> REDUCED CONFIDENCE, never a silent default
# presented as if nothing happened.
# NEW test — app/providers/base.py already raises ProviderUnavailableError
# instead of returning a bad value (tested in isolation in
# test_providers.py), and app/services/risk_engine.py already catches it
# (_fetch_rainfall, the soil-moisture try/except) — but nothing had
# actually proven, end-to-end, that a full risk computation survives a
# real provider failure rather than propagating a 500. It does; this
# closes that gap.
# ---------------------------------------------------------------------------
def test_risk_computation_survives_a_real_provider_outage():
    village_id = _village_id("Kedarnath")
    with session_scope() as db:
        village = db.get(Village, village_id)

        failing_provider = Mock()
        failing_provider.fetch.side_effect = ProviderUnavailableError("Open-Meteo unreachable (simulated outage)")

        # Must not raise — a real upstream outage must degrade the
        # assessment, never take down the whole risk computation.
        assessment = compute_risk_for_village(
            village, db, rainfall_provider=failing_provider, soil_provider=failing_provider
        )

    assert 0.0 <= assessment.score <= 100.0
    rainfall_component = next(c for c in assessment.components if c.name == "rainfall_intensity")
    soil_component = next(c for c in assessment.components if c.name == "soil_moisture")
    # Honest degrade, not a fabricated "real" reading: when the configured
    # provider can't be reached, the component must fall back to the
    # SIMULATED tier (which is what actually drags confidence down below),
    # never silently relabelled as real.
    assert rainfall_component.source.value == "simulated"
    assert soil_component.source.value == "simulated"


# ---------------------------------------------------------------------------
# Mode 7: the glacial-lake-proximity dataset (an auxiliary, non-critical
# input) is entirely missing on disk.
# The underlying lookup already degrades honestly at the unit level (see
# tests/backend/test_glacial_lake_proximity.py::
# test_missing_data_file_returns_honest_none_not_a_crash). NEW here: proving
# that failure doesn't propagate up and break the REST endpoint that
# actually matters — a full GET /risk/{id} call must still return 200 with
# every other field intact.
# ---------------------------------------------------------------------------
def test_risk_endpoint_survives_missing_glacial_lake_dataset(monkeypatch):
    monkeypatch.setattr(glp, "DATA_PATH", Path("/nonexistent/does-not-exist.csv"))
    glp._load_lakes.cache_clear()
    try:
        village_id = _village_id("Kedarnath")
        r = client.get(f"/api/v1/risk/{village_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["glacial_lake_distance_km"] is None
        assert body["glacial_lake_note"], "must still explain WHY it's missing, not just omit the field silently"
        # Everything else about the risk assessment must be unaffected by
        # this one advisory field failing.
        assert 0.0 <= body["risk_score"] <= 100.0
        assert body["risk_level"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    finally:
        glp._load_lakes.cache_clear()


# ---------------------------------------------------------------------------
# Mode 8: a client queries risk data for a region with no seeded villages,
# or a village id that doesn't exist at all.
# NEW test — both paths already existed in the route code (an empty ORM
# query result, and an explicit 404) but had no dedicated failure-path
# test proving neither one crashes or fabricates a placeholder result.
# ---------------------------------------------------------------------------
def test_risk_map_for_an_unpopulated_planned_region_returns_an_honest_empty_list():
    regions = client.get("/api/v1/regions").json()
    planned = [r for r in regions if r["status"] == "planned"]
    assert planned, "expected at least one honestly-unpopulated planned region — has Phase 11 seeding run?"
    region_id = planned[0]["id"]

    r = client.get(f"/api/v1/risk/map?region_id={region_id}")
    assert r.status_code == 200
    assert r.json() == [], "a region with zero seeded villages must return an honest [], never fabricated entries"


def test_risk_for_nonexistent_village_id_is_a_clean_404():
    r = client.get("/api/v1/risk/999999")
    assert r.status_code == 404
    assert "999999" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Mode 9: the MQTT bridge (iot/mqtt_bridge.py) receives a malformed payload,
# or the backend it forwards to is unreachable.
# NEW test — exercises the real on_message handler function directly (no
# live broker or backend needed to prove the logic), same approach already
# used for provider unit tests. This is real code review + test coverage
# for something that was already implemented correctly but had never had
# an explicit regression test proving it.
# ---------------------------------------------------------------------------
def _import_mqtt_bridge():
    import importlib.util

    bridge_path = Path(__file__).resolve().parents[2] / "iot" / "mqtt_bridge.py"
    spec = importlib.util.spec_from_file_location("mqtt_bridge", bridge_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mqtt_bridge_drops_malformed_json_without_crashing():
    bridge = _import_mqtt_bridge()
    on_message = bridge.make_on_message("http://localhost:8000")

    msg = Mock()
    msg.topic = "girivarsha/sensors/esp32-kedarnath-rain-01/reading"
    msg.payload = b"{not valid json"

    # Must not raise — a single garbled MQTT message must never take the
    # bridge process down.
    on_message(None, None, msg)


def test_mqtt_bridge_survives_backend_unreachable(monkeypatch):
    bridge = _import_mqtt_bridge()
    on_message = bridge.make_on_message("http://localhost:8000")

    import requests

    def fake_post(*args, **kwargs):
        raise requests.exceptions.ConnectionError("simulated backend outage")

    monkeypatch.setattr(bridge.requests, "post", fake_post)

    msg = Mock()
    msg.topic = "girivarsha/sensors/esp32-kedarnath-rain-01/reading"
    msg.payload = b'{"value": 5.0, "unit": "mm/hr", "source": "simulated"}'

    # Must not raise — a transient backend outage must be logged and
    # skipped, not crash the bridge (which would then miss every
    # subsequent real message too).
    on_message(None, None, msg)


def test_mqtt_bridge_ignores_messages_on_unexpected_topics():
    bridge = _import_mqtt_bridge()
    on_message = bridge.make_on_message("http://localhost:8000")

    msg = Mock()
    msg.topic = "some/other/unrelated/topic/shape"
    msg.payload = b'{"value": 5.0}'

    # Must not raise, and must not attempt to forward garbage to the API.
    on_message(None, None, msg)


# ---------------------------------------------------------------------------
# Mode 10: the glacier mass-balance dataset (another auxiliary, non-critical
# input — user-requested glacier-melt-rate follow-up) is entirely missing on
# disk. Same shape as Mode 7's glacial-lake test: the underlying lookup
# already degrades honestly at the unit level (see
# tests/backend/test_glacial_melt_hazard.py::
# test_missing_data_file_returns_honest_zero_not_a_crash). NEW here: proving
# a full GET /risk/{id} call still returns 200 with every other field intact
# — including the risk_score/level itself, since glacial_melt_rate (unlike
# glacial_lake_distance_km) IS folded into the weighted score, so this is
# also proof that a missing dataset degrades to a 0-weight contribution
# rather than crashing score computation entirely.
# ---------------------------------------------------------------------------
def test_risk_endpoint_survives_missing_glacier_mass_balance_dataset(monkeypatch):
    from app.services import glacial_melt_hazard as gmh

    monkeypatch.setattr(gmh, "DATA_PATH", Path("/nonexistent/does-not-exist.csv"))
    gmh._load_glaciers.cache_clear()
    gmh._normalization_bounds.cache_clear()
    try:
        village_id = _village_id("Kedarnath")
        r = client.get(f"/api/v1/risk/{village_id}")
        assert r.status_code == 200
        body = r.json()
        # The GLOF contribution indicator honestly can't be computed without
        # glacier data either.
        assert body["glof_contribution_pct"] is None
        assert body["glof_contribution_note"], "must still explain WHY it's missing, not just omit the field silently"
        glacial_melt_component = next(c for c in body["drivers"]["components"] if c["name"] == "glacial_melt_rate")
        assert glacial_melt_component["normalized_0_1"] == 0.0
        # Everything else about the risk assessment must be unaffected by
        # this one component's data source failing.
        assert 0.0 <= body["risk_score"] <= 100.0
        assert body["risk_level"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    finally:
        gmh._load_glaciers.cache_clear()
        gmh._normalization_bounds.cache_clear()


# ---------------------------------------------------------------------------
# Mode 11: the SCS-CN soil/land-cover input dataset (another auxiliary,
# non-critical input — user-requested SCS-CN rainfall-runoff follow-up) is
# entirely missing on disk. Same shape as Mode 7's glacial-lake test: the
# underlying lookup already degrades honestly at the unit level (see
# tests/backend/test_scs_cn_runoff.py::
# test_missing_data_file_returns_honest_none_not_a_crash). NEW here: proving
# a full GET /risk/{id} call still returns 200 with every other field
# intact — including risk_score/level itself, since the SCS-CN runoff
# estimate is NEVER folded into the weighted score (unlike glacial_melt_rate
# in Mode 10 above), so this also proves that component list is completely
# unaffected by this dataset's absence.
# ---------------------------------------------------------------------------
def test_risk_endpoint_survives_missing_scs_cn_dataset(monkeypatch):
    from app.services import scs_cn_runoff as scr

    monkeypatch.setattr(scr, "DATA_PATH", Path("/nonexistent/does-not-exist.csv"))
    scr._load_inputs.cache_clear()
    try:
        village_id = _village_id("Kedarnath")
        r = client.get(f"/api/v1/risk/{village_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["scs_cn_curve_number"] is None
        assert body["scs_cn_runoff_depth_mm"] is None
        assert body["scs_cn_note"], "must still explain WHY it's missing, not just omit the field silently"
        # Everything else about the risk assessment — including every
        # weighted component — must be unaffected by this one advisory
        # estimate's data source failing.
        assert 0.0 <= body["risk_score"] <= 100.0
        assert body["risk_level"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")
        component_names = {c["name"] for c in body["drivers"]["components"]}
        assert len(component_names) == 5
    finally:
        scr._load_inputs.cache_clear()


# ---------------------------------------------------------------------------
# Mode 12: the real OpenStreetMap road/trail network dataset (user-requested
# evacuation-routing follow-up) is entirely missing on disk. Unlike Modes 7,
# 10 and 11 above, this isn't a /risk/* input at all — it only affects
# GET /evacuation/route/{id}'s per-hop distance calculation. The underlying
# loader already degrades honestly at the unit level (see
# tests/backend/test_road_network.py::test_missing_dataset_degrades_honestly_to_none).
# NEW here: proving a full evacuation-route call still returns 200 with a
# complete, correct route — every hop just falls back to the pre-existing
# straight-line elevation-order proxy, exactly as it behaved before this
# follow-up existed, rather than crashing or returning a partial route.
# ---------------------------------------------------------------------------
def test_evacuation_route_survives_missing_road_network_dataset(monkeypatch):
    from app.services import road_network as rn

    monkeypatch.setattr(rn, "DATA_PATH", Path("/nonexistent/does-not-exist.json"))
    rn._reset_cache_for_tests()
    try:
        reni_id = _village_id("Reni")
        r = client.get(f"/api/v1/evacuation/route/{reni_id}")
        assert r.status_code == 200
        body = r.json()
        assert len(body["hops"]) == 3
        for hop in body["hops"]:
            assert hop["distance_source"] == "straight_line_proxy"
            assert hop["polyline"] is None
            assert "dataset not found" in hop["road_note"].lower()
        assert body["total_distance_km"] > 0
        assert body["estimated_minutes"] > 0
    finally:
        rn._reset_cache_for_tests()


# ---------------------------------------------------------------------------
# Mode 13: the real NASA POWER antecedent-rainfall fetch (user-requested
# antecedent-precipitation-index follow-up) fails outright — network down,
# API error, whatever. GET /risk/{id} must still return 200 with a complete,
# correct response: the SCS-CN AMC classification honestly falls back to the
# pre-existing soil-moisture proxy (exactly as it behaved before this
# follow-up existed) rather than crashing or leaving fields half-populated.
# The underlying degrade-path is already unit-tested in isolation
# (test_antecedent_rainfall.py::test_get_antecedent_rainfall_real_mode_falls_back_honestly_on_failure);
# NEW here is proving the full request survives it end-to-end.
# ---------------------------------------------------------------------------
def test_risk_detail_survives_a_failed_real_antecedent_rainfall_fetch(monkeypatch):
    from app.core.config import get_settings
    from app.services import antecedent_rainfall as ar

    def _raise(*a, **k):
        raise ar.httpx.ConnectError("connection refused")

    monkeypatch.setattr(ar.httpx, "get", _raise)
    settings = get_settings()
    monkeypatch.setattr(settings, "active_antecedent_provider", "real")
    try:
        village_id = _village_id("Kedarnath")
        r = client.get(f"/api/v1/risk/{village_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["antecedent_rainfall_source"] == "simulated"
        assert "fetch failed" in body["antecedent_rainfall_note"].lower()
        assert "soil-moisture reading" in body["scs_cn_note"]
    finally:
        ar._fetch_real_power_daily.cache_clear()


# ---------------------------------------------------------------------------
# Mode 14: a device sends a WRONG API key for a sensor that has one on file
# (user-requested IoT device-authentication follow-up). Must degrade
# honestly — a clean 401, no fabricated acceptance, and no side effects on
# the sensor's stored state (last_seen_at/status must NOT change on a
# rejected request, since the request never actually reported anything).
# The unit-level 401 behavior is already covered directly in
# tests/backend/test_sensors.py; NEW here is proving there's no accidental
# partial write on the reject path.
# ---------------------------------------------------------------------------
def test_wrong_device_api_key_degrades_honestly_with_no_side_effects():
    device_id = "test-failure-mode-14-auth"
    plaintext_key = "correct-key-for-mode-14-test-only"

    with session_scope() as db:
        village = db.scalar(select(Village).where(Village.name == "Kedarnath"))
        assert village is not None
        db.add(
            Sensor(
                external_device_id=device_id,
                village_id=village.id,
                sensor_type=SensorType.RAINFALL,
                status=SensorStatus.OFFLINE,
                last_seen_at=None,
                api_key_hash=hash_device_api_key(plaintext_key),
            )
        )
        db.commit()

    try:
        r = client.post(
            "/api/v1/sensor-reading",
            json={"external_device_id": device_id, "value": 42.0, "unit": "mm/hr", "source": "simulated"},
            headers={"X-Device-Api-Key": "wrong-key-entirely"},
        )
        assert r.status_code == 401, "a wrong key must be rejected cleanly, not crash or be silently accepted"

        sensors = client.get("/api/v1/sensors").json()
        sensor_out = next(s for s in sensors if s["external_device_id"] == device_id)
        assert sensor_out["status"] == "offline", "a rejected reading must never flip status to online"
        assert sensor_out["last_seen_at"] is None, "a rejected reading must never update last_seen_at"
        assert sensor_out["last_value"] is None, "a rejected reading must never be stored as a real observation"
    finally:
        with session_scope() as db:
            sensor = db.scalar(select(Sensor).where(Sensor.external_device_id == device_id))
            if sensor is not None:
                db.execute(SensorReading.__table__.delete().where(SensorReading.sensor_id == sensor.id))
                db.delete(sensor)
            db.commit()
