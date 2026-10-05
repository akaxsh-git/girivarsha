"""
Phase 8 tests: the real sensor registry + ingestion endpoint. Needs a
running, migrated, seeded Postgres — see test_villages.py's skip pattern.

Provisions its own throwaway test sensor (device id prefixed `test-`, never
colliding with scripts/seed_iot_nodes.py's real `esp32-*` fleet) so this
suite doesn't depend on that script having been run.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

from sqlalchemy import select  # noqa: E402

from app.models.database import session_scope  # noqa: E402
from app.models.orm import Sensor, SensorReading, SensorStatus, SensorType, Village  # noqa: E402
from app.api.routes.sensors import _regional_fallback_cached, hash_device_api_key  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


class _FakeOpenMeteoResponse:
    """Same shallow httpx.get fake used by tests/backend/test_providers.py
    — redefined locally rather than imported, matching this codebase's
    existing convention of small test doubles living beside the tests that
    use them (see e.g. app/services/*.py's several independent lru_cache
    helpers)."""

    def __init__(self, json_body: dict, status_code: int = 200):
        self._json_body = json_body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("fake error", request=None, response=self)

    def json(self):
        return self._json_body


@pytest.fixture(autouse=True)
def _clear_regional_fallback_cache():
    """Real-regional-data fallback (user-requested follow-up) is cached by
    @lru_cache — a process-wide cache that would otherwise leak a
    monkeypatched fake response (or a real one, if these ever ran with
    network access) from one test into the next. Cleared before AND after
    every test in this file, same discipline test_antecedent_rainfall.py
    already uses for its own lru_cache'd real-fetch functions."""
    _regional_fallback_cached.cache_clear()
    yield
    _regional_fallback_cached.cache_clear()

TEST_DEVICE_ID = "test-rain-01"
STALE_DEVICE_ID = "test-stale-01"

# Device-authentication follow-up (user-requested): a THIRD throwaway test
# device, kept deliberately separate from TEST_DEVICE_ID/STALE_DEVICE_ID
# above so every pre-existing test in this file keeps running against an
# unauthenticated sensor exactly as before — nothing about those fixtures
# changes. This one alone carries a real (test-only) api_key_hash.
AUTH_DEVICE_ID = "test-auth-01"
AUTH_DEVICE_PLAINTEXT_KEY = "test-only-plaintext-key-never-a-real-secret"


@pytest.fixture(autouse=True)
def _provision_test_sensors():
    """Provisions the two throwaway test sensors before each test and
    deletes them (and their readings) afterward — so this suite never
    leaves fake 'test-*' devices sitting in a real GET /sensors response
    after the test run ends."""
    with session_scope() as db:
        village = db.scalar(select(Village).where(Village.name == "Kedarnath"))
        assert village is not None, "expected village 'Kedarnath' — has scripts/seed_pilot_region.py run?"

        for device_id in (TEST_DEVICE_ID, STALE_DEVICE_ID):
            existing = db.scalar(select(Sensor).where(Sensor.external_device_id == device_id))
            if existing is None:
                db.add(
                    Sensor(
                        external_device_id=device_id,
                        village_id=village.id,
                        sensor_type=SensorType.RAINFALL,
                        status=SensorStatus.OFFLINE,
                        last_seen_at=None,
                    )
                )
            else:
                db.execute(SensorReading.__table__.delete().where(SensorReading.sensor_id == existing.id))
                existing.last_seen_at = None
                existing.status = SensorStatus.OFFLINE
        db.commit()

    yield

    with session_scope() as db:
        for device_id in (TEST_DEVICE_ID, STALE_DEVICE_ID):
            sensor = db.scalar(select(Sensor).where(Sensor.external_device_id == device_id))
            if sensor is not None:
                db.execute(SensorReading.__table__.delete().where(SensorReading.sensor_id == sensor.id))
                db.delete(sensor)
        db.commit()


@pytest.fixture(autouse=True)
def _provision_authenticated_test_sensor():
    """Device-authentication follow-up (user-requested): a dedicated
    throwaway sensor provisioned WITH a real api_key_hash, so auth
    enforcement can be tested without touching TEST_DEVICE_ID/STALE_DEVICE_ID
    (which stay keyless, exercising the honest pre-migration/un-rotated
    behavior that every pre-existing test in this file already covers)."""
    with session_scope() as db:
        village = db.scalar(select(Village).where(Village.name == "Kedarnath"))
        assert village is not None, "expected village 'Kedarnath' — has scripts/seed_pilot_region.py run?"

        existing = db.scalar(select(Sensor).where(Sensor.external_device_id == AUTH_DEVICE_ID))
        if existing is None:
            db.add(
                Sensor(
                    external_device_id=AUTH_DEVICE_ID,
                    village_id=village.id,
                    sensor_type=SensorType.RAINFALL,
                    status=SensorStatus.OFFLINE,
                    last_seen_at=None,
                    api_key_hash=hash_device_api_key(AUTH_DEVICE_PLAINTEXT_KEY),
                )
            )
        else:
            db.execute(SensorReading.__table__.delete().where(SensorReading.sensor_id == existing.id))
            existing.last_seen_at = None
            existing.status = SensorStatus.OFFLINE
            existing.api_key_hash = hash_device_api_key(AUTH_DEVICE_PLAINTEXT_KEY)
        db.commit()

    yield

    with session_scope() as db:
        sensor = db.scalar(select(Sensor).where(Sensor.external_device_id == AUTH_DEVICE_ID))
        if sensor is not None:
            db.execute(SensorReading.__table__.delete().where(SensorReading.sensor_id == sensor.id))
            db.delete(sensor)
        db.commit()


def _get_sensor(device_id: str) -> dict:
    sensors = client.get("/api/v1/sensors").json()
    matches = [s for s in sensors if s["external_device_id"] == device_id]
    assert matches, f"expected provisioned test sensor {device_id!r} not found"
    return matches[0]


def test_unregistered_device_gets_a_clear_404_not_a_silent_accept():
    r = client.post(
        "/api/v1/sensor-reading",
        json={"external_device_id": "not-a-real-device", "value": 5.0, "unit": "mm/hr", "source": "simulated"},
    )
    assert r.status_code == 404
    assert "not-a-real-device" in r.json()["detail"]


def test_provisioned_but_never_reported_sensor_is_honestly_offline():
    sensor = _get_sensor(TEST_DEVICE_ID)
    assert sensor["status"] == "offline"
    assert sensor["last_seen_at"] is None
    assert sensor["last_value"] is None, "must never fabricate a reading for a node that hasn't reported"


def test_posting_a_reading_flips_status_to_online_and_is_readable_back():
    r = client.post(
        "/api/v1/sensor-reading",
        json={"external_device_id": TEST_DEVICE_ID, "value": 12.5, "unit": "mm/hr", "source": "simulated"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["value"] == 12.5
    assert body["source"] == "simulated"

    sensor = _get_sensor(TEST_DEVICE_ID)
    assert sensor["status"] == "online"
    assert sensor["last_value"] == 12.5
    assert sensor["last_unit"] == "mm/hr"
    assert sensor["seconds_since_last_seen"] is not None
    assert sensor["seconds_since_last_seen"] < 10

    readings = client.get("/api/v1/sensor-readings?limit=10").json()
    assert any(x["external_device_id"] == TEST_DEVICE_ID and x["value"] == 12.5 for x in readings)


def test_stale_reading_reports_stale_not_online(monkeypatch):
    """A reading old enough to be past 'online' but within 'stale' must
    report stale — status is recomputed live from freshness, never trusted
    from a stored column (see app/api/routes/sensors.py:_compute_status)."""
    old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    with session_scope() as db:
        sensor = db.scalar(select(Sensor).where(Sensor.external_device_id == STALE_DEVICE_ID))
        db.add(SensorReading(sensor_id=sensor.id, value=3.0, unit="mm/hr", source="simulated", observed_at=old_time))
        sensor.last_seen_at = old_time
        db.commit()

    sensor_out = _get_sensor(STALE_DEVICE_ID)
    assert sensor_out["status"] == "stale", (
        "10 minutes old is past the default 300s online threshold but within the 1800s stale threshold"
    )


def test_invalid_source_is_rejected_not_silently_stored():
    r = client.post(
        "/api/v1/sensor-reading",
        json={"external_device_id": TEST_DEVICE_ID, "value": 1.0, "unit": "mm/hr", "source": "definitely_real_trust_me"},
    )
    assert r.status_code == 422


def test_keyless_sensor_still_accepts_readings_with_no_credential_at_all():
    """Device-authentication follow-up (user-requested): a sensor with no
    api_key_hash on file (the honest pre-migration/not-yet-rotated state)
    must keep working exactly as before — no retroactive lockout. This is
    the same request the pre-existing
    test_posting_a_reading_flips_status_to_online_and_is_readable_back
    already made; repeated here explicitly as the "control" case alongside
    the new auth-enforcement tests below."""
    r = client.post(
        "/api/v1/sensor-reading",
        json={"external_device_id": TEST_DEVICE_ID, "value": 7.0, "unit": "mm/hr", "source": "simulated"},
    )
    assert r.status_code == 201


def test_reading_without_api_key_is_rejected_for_a_sensor_that_has_one():
    r = client.post(
        "/api/v1/sensor-reading",
        json={"external_device_id": AUTH_DEVICE_ID, "value": 9.0, "unit": "mm/hr", "source": "simulated"},
    )
    assert r.status_code == 401
    assert AUTH_DEVICE_ID in r.json()["detail"]


def test_reading_with_wrong_api_key_is_rejected():
    r = client.post(
        "/api/v1/sensor-reading",
        json={"external_device_id": AUTH_DEVICE_ID, "value": 9.0, "unit": "mm/hr", "source": "simulated"},
        headers={"X-Device-Api-Key": "definitely-the-wrong-key"},
    )
    assert r.status_code == 401
    assert AUTH_DEVICE_ID in r.json()["detail"]


def test_reading_with_correct_api_key_is_accepted():
    r = client.post(
        "/api/v1/sensor-reading",
        json={"external_device_id": AUTH_DEVICE_ID, "value": 9.0, "unit": "mm/hr", "source": "simulated"},
        headers={"X-Device-Api-Key": AUTH_DEVICE_PLAINTEXT_KEY},
    )
    assert r.status_code == 201
    assert r.json()["value"] == 9.0


def test_authenticated_field_reflects_whether_a_sensor_has_a_real_key_on_file():
    keyless = _get_sensor(TEST_DEVICE_ID)
    assert keyless["authenticated"] is False

    keyed = _get_sensor(AUTH_DEVICE_ID)
    assert keyed["authenticated"] is True


def test_chamoli_sensor_nodes_are_correctly_linked_to_chamoli_villages():
    """Phase 12 follow-up (user-requested): the Chamoli Disaster Valley's
    sensor nodes must resolve to REAL Chamoli villages (Reni/Tapovan/
    Vishnuprayag — not Mandakini) — a regression guard against
    scripts/seed_iot_nodes.py's village lookup silently matching the wrong
    valley if a future edit ever introduced a name collision. Skips
    cleanly (not a failure) if scripts/seed_iot_nodes.py hasn't been run
    in this checkout yet — same tolerance as the Kedarnath fixture lookup
    above."""
    sensors = client.get("/api/v1/sensors").json()
    chamoli_devices = {s["external_device_id"]: s for s in sensors if s["external_device_id"].startswith("esp32-reni-")}
    if not chamoli_devices:
        pytest.skip("scripts/seed_iot_nodes.py has not provisioned Chamoli nodes in this checkout")

    expected_villages = {
        "esp32-reni-rain-01": "Reni",
        "esp32-reni-soil-01": "Reni",
    }
    for device_id, expected_village in expected_villages.items():
        assert device_id in chamoli_devices
        assert chamoli_devices[device_id]["village_name"] == expected_village

    # Deliberately NOT sensored — see scripts/seed_iot_nodes.py's docstring
    # for why Joshimath was excluded from demo-node placement.
    joshimath_devices = [s for s in sensors if s.get("village_name") == "Joshimath"]
    assert joshimath_devices == []


def test_offline_rainfall_sensor_gets_a_real_regional_fallback_value(monkeypatch):
    """Real-regional-data fallback (user-requested follow-up): TEST_DEVICE_ID
    is provisioned offline (no reading) by the autouse fixture above, so
    GET /sensors should fall back to a REAL (mocked) Open-Meteo rainfall
    estimate for its village — tagged source="derived", and status must
    stay honestly "offline" (this is not a substitute for a live device)."""

    def fake_get(url, params=None, timeout=None):
        assert "api.open-meteo.com" in url
        return _FakeOpenMeteoResponse({"current": {"rain": 4.2, "precipitation": 4.2}})

    monkeypatch.setattr("app.providers.base.httpx.get", fake_get)

    sensor = _get_sensor(TEST_DEVICE_ID)
    assert sensor["status"] == "offline", "the fallback must never make a device look live"
    assert sensor["last_value"] is None, "the device's OWN reading must stay untouched"
    assert sensor["fallback_value"] == 4.2
    assert sensor["fallback_unit"] == "mm/hr"
    assert sensor["fallback_source"] == "derived"


def test_online_sensor_never_calls_the_fallback_provider_at_all(monkeypatch):
    """A sensor with a fresh reading of its own must not pay the extra
    network cost, and must never show a fallback value alongside its real
    one — the two must never be presentable at the same time.

    Note: GET /sensors returns the WHOLE fleet, and this sandbox's other
    seeded esp32-* sensors are legitimately offline too (no simulator
    running here), so they DO trigger their own real fallback jobs — this
    test can't assert "httpx.get is never called at all" without being
    flaky against however many other real devices happen to be seeded. It
    instead gives every such call a harmless fake response and asserts
    only that THIS specific online sensor never shows a fallback value."""

    def fake_get(url, params=None, timeout=None):
        return _FakeOpenMeteoResponse(
            {
                "current": {"rain": 1.0, "precipitation": 1.0},
                "hourly": {"time": ["2020-01-01T00:00"], "soil_moisture_0_to_1cm": [0.3]},
            }
        )

    r = client.post(
        "/api/v1/sensor-reading",
        json={"external_device_id": TEST_DEVICE_ID, "value": 12.5, "unit": "mm/hr", "source": "simulated"},
    )
    assert r.status_code == 201

    monkeypatch.setattr("app.providers.base.httpx.get", fake_get)

    sensor = _get_sensor(TEST_DEVICE_ID)
    assert sensor["status"] == "online"
    assert sensor["last_value"] == 12.5
    assert sensor["fallback_value"] is None
    assert sensor["fallback_source"] is None


def test_fallback_stays_none_when_open_meteo_is_unavailable(monkeypatch):
    """Honest degradation: if the real provider fails (bad response, HTTP
    error, malformed body), GET /sensors must still return 200 with the
    fallback fields simply left null — never a 500, never a guessed number."""

    def fake_get(url, params=None, timeout=None):
        return _FakeOpenMeteoResponse({}, status_code=503)

    monkeypatch.setattr("app.providers.base.httpx.get", fake_get)

    sensor = _get_sensor(STALE_DEVICE_ID)
    assert sensor["fallback_value"] is None
    assert sensor["fallback_source"] is None


def test_sensor_type_with_no_open_meteo_equivalent_never_gets_a_fallback_value(monkeypatch):
    """Open-Meteo has no water-level or ground-tilt product at any
    resolution — a water_level sensor must stay fallback_value=None rather
    than the route guessing with a rainfall/soil number instead. Every
    OTHER offline sensor in the fleet gets a harmless fake response (see
    test_online_sensor_never_calls_the_fallback_provider_at_all's note on
    why this can't assert zero calls at all) — only this one device's own
    field is asserted."""

    def fake_get(url, params=None, timeout=None):
        return _FakeOpenMeteoResponse(
            {
                "current": {"rain": 1.0, "precipitation": 1.0},
                "hourly": {"time": ["2020-01-01T00:00"], "soil_moisture_0_to_1cm": [0.3]},
            }
        )

    monkeypatch.setattr("app.providers.base.httpx.get", fake_get)

    device_id = "test-water-level-01"
    with session_scope() as db:
        village = db.scalar(select(Village).where(Village.name == "Kedarnath"))
        db.add(
            Sensor(
                external_device_id=device_id,
                village_id=village.id,
                sensor_type=SensorType.WATER_LEVEL,
                status=SensorStatus.OFFLINE,
                last_seen_at=None,
            )
        )
        db.commit()
    try:
        sensor = _get_sensor(device_id)
        assert sensor["status"] == "offline"
        assert sensor["fallback_value"] is None
        assert sensor["fallback_source"] is None
    finally:
        with session_scope() as db:
            s = db.scalar(select(Sensor).where(Sensor.external_device_id == device_id))
            if s is not None:
                db.delete(s)
            db.commit()


def test_sensor_with_no_village_never_gets_a_fallback_value(monkeypatch):
    """A sensor with village_id IS NULL has no coordinates to look up
    regional weather for — must stay fallback_value=None, not crash. Every
    OTHER offline sensor in the fleet gets a harmless fake response (see
    test_online_sensor_never_calls_the_fallback_provider_at_all's note on
    why this can't assert zero calls at all) — only this one device's own
    field is asserted."""

    def fake_get(url, params=None, timeout=None):
        return _FakeOpenMeteoResponse(
            {
                "current": {"rain": 1.0, "precipitation": 1.0},
                "hourly": {"time": ["2020-01-01T00:00"], "soil_moisture_0_to_1cm": [0.3]},
            }
        )

    monkeypatch.setattr("app.providers.base.httpx.get", fake_get)

    device_id = "test-no-village-01"
    with session_scope() as db:
        db.add(
            Sensor(
                external_device_id=device_id,
                village_id=None,
                sensor_type=SensorType.RAINFALL,
                status=SensorStatus.OFFLINE,
                last_seen_at=None,
            )
        )
        db.commit()
    try:
        sensor = _get_sensor(device_id)
        assert sensor["status"] == "offline"
        assert sensor["fallback_value"] is None
    finally:
        with session_scope() as db:
            s = db.scalar(select(Sensor).where(Sensor.external_device_id == device_id))
            if s is not None:
                db.delete(s)
            db.commit()
