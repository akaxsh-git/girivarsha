"""
Phase 8+ follow-up (user-requested): wiring real sensor readings into the
Phase 4 risk engine's providers — the top of the documented fallback
hierarchy (docs/Architecture.md, "Sensor-failure / fallback hierarchy,
problem-statement item 13") was real code and real docs since Phase 4/8,
but LOCAL SENSOR was never actually consulted before falling straight to
the configured provider. This suite tests the new wiring in
app/services/risk_engine.py (`_fresh_sensor_reading`, and the
`_fetch_rainfall`/`_fetch_soil` call sites that now check it first).

Provisions its own throwaway test sensor on an otherwise-unsensored village
(Sonprayag — Mandakini's own seed data never gives it a sensor node) so
this suite doesn't depend on scripts/seed_iot_nodes.py having been run, and
never collides with the real esp32-* fleet if it has.
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
from app.models.orm import DataSource, Sensor, SensorReading, SensorStatus, SensorType, Village  # noqa: E402
from app.services.risk_engine import compute_risk_for_village  # noqa: E402

TEST_DEVICE_ID = "test-risk-wiring-rain-01"
TARGET_VILLAGE_NAME = "Sonprayag"


@pytest.fixture
def _throwaway_sensor():
    """Provisions one throwaway rainfall sensor on TARGET_VILLAGE_NAME,
    offline (no reading) by default — each test sets its own state.
    Cleaned up afterward regardless of what state the test left it in."""
    with session_scope() as db:
        village = db.scalar(select(Village).where(Village.name == TARGET_VILLAGE_NAME))
        assert village is not None, f"expected seeded village {TARGET_VILLAGE_NAME!r} — has scripts/seed_pilot_region.py run?"
        existing = db.scalar(select(Sensor).where(Sensor.external_device_id == TEST_DEVICE_ID))
        if existing is None:
            db.add(
                Sensor(
                    external_device_id=TEST_DEVICE_ID,
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
        village_id = village.id

    yield village_id

    with session_scope() as db:
        sensor = db.scalar(select(Sensor).where(Sensor.external_device_id == TEST_DEVICE_ID))
        if sensor is not None:
            db.execute(SensorReading.__table__.delete().where(SensorReading.sensor_id == sensor.id))
            db.delete(sensor)
        db.commit()


def _rainfall_component(assessment):
    return next(c for c in assessment.components if c.name == "rainfall_intensity")


def test_village_with_no_sensor_falls_back_to_provider_unchanged():
    """Sanity baseline: a village nobody has provisioned a sensor for at
    all must behave exactly as before this follow-up — no crash, provider
    -sourced reading, no sensor mentioned in the description."""
    with session_scope() as db:
        village = db.scalar(select(Village).where(Village.name == "Rambara"))
        assert village is not None
        assessment = compute_risk_for_village(village, db)
    rc = _rainfall_component(assessment)
    assert "sensor" not in rc.description.lower()


def test_offline_sensor_falls_back_to_provider(_throwaway_sensor):
    """A registered-but-never-reported sensor (offline) must not be used —
    same fallback behavior as before a sensor existed at all."""
    with session_scope() as db:
        village = db.get(Village, _throwaway_sensor)
        assessment = compute_risk_for_village(village, db)
    rc = _rainfall_component(assessment)
    assert "sensor" not in rc.description.lower()


def test_stale_sensor_falls_back_to_provider(_throwaway_sensor):
    """A sensor whose last reading has aged past the online threshold must
    not be used, even though it HAS reported at some point — same freshness
    rule GET /sensors uses (app/services/sensor_freshness.py)."""
    old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    with session_scope() as db:
        sensor = db.scalar(select(Sensor).where(Sensor.external_device_id == TEST_DEVICE_ID))
        db.add(
            SensorReading(
                sensor_id=sensor.id, value=99.0, unit="mm/hr", source=DataSource.REAL, observed_at=old_time
            )
        )
        sensor.last_seen_at = old_time
        db.commit()

        village = db.get(Village, _throwaway_sensor)
        assessment = compute_risk_for_village(village, db)
    rc = _rainfall_component(assessment)
    assert "sensor" not in rc.description.lower()
    assert rc.raw_value != 99.0, "a stale reading's value must never leak into the score"


def test_online_sensor_reading_is_used_with_its_own_source_tag(_throwaway_sensor):
    """The real point of this follow-up: an online sensor's actual reading
    — and its own declared source tag — is what the risk engine now uses,
    not a provider-generated value."""
    now = datetime.now(timezone.utc)
    with session_scope() as db:
        sensor = db.scalar(select(Sensor).where(Sensor.external_device_id == TEST_DEVICE_ID))
        db.add(
            SensorReading(sensor_id=sensor.id, value=42.5, unit="mm/hr", source=DataSource.REAL, observed_at=now)
        )
        sensor.last_seen_at = now
        db.commit()

        village = db.get(Village, _throwaway_sensor)
        assessment = compute_risk_for_village(village, db)
    rc = _rainfall_component(assessment)
    assert rc.raw_value == 42.5
    assert rc.source == DataSource.REAL, "must use the sensor reading's OWN source tag, not assume real"
    assert TEST_DEVICE_ID in rc.description, "must be transparent about which sensor produced this number"


def test_a_simulated_tagged_sensor_reading_does_not_fake_real_confidence(_throwaway_sensor):
    """This build's demo sensors (iot/simulate_sensor_publisher.py) declare
    source='simulated' — using their readings must NOT silently upgrade
    confidence to the REAL tier just because a sensor exists. Only an
    actual real-hardware reading (source='real') should do that."""
    now = datetime.now(timezone.utc)
    with session_scope() as db:
        sensor = db.scalar(select(Sensor).where(Sensor.external_device_id == TEST_DEVICE_ID))
        db.add(
            SensorReading(
                sensor_id=sensor.id, value=10.0, unit="mm/hr", source=DataSource.SIMULATED, observed_at=now
            )
        )
        sensor.last_seen_at = now
        db.commit()

        village = db.get(Village, _throwaway_sensor)
        assessment = compute_risk_for_village(village, db)
    rc = _rainfall_component(assessment)
    assert rc.raw_value == 10.0
    assert rc.source == DataSource.SIMULATED
