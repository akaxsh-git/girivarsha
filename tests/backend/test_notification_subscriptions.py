"""
SMS-reach follow-up (user-requested): tests for
POST /notifications/subscribe and /notifications/unsubscribe
(app/api/routes/notifications.py) and the NotificationSubscription model
they manage. Needs a running, migrated, seeded Postgres — see
test_villages.py's skip pattern.
"""
import sys
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
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.models.database import session_scope  # noqa: E402
from app.models.orm import NotificationSubscription, Village  # noqa: E402

client = TestClient(app)

TEST_PHONE = "+919999999001"


@pytest.fixture
def _village_id():
    with session_scope() as db:
        village = db.scalar(select(Village))
        assert village is not None, "expected at least one seeded village"
        village_id = village.id

    yield village_id

    with session_scope() as db:
        db.execute(
            NotificationSubscription.__table__.delete().where(
                NotificationSubscription.phone_number == TEST_PHONE
            )
        )
        db.commit()


def test_subscribe_creates_a_new_subscription(_village_id):
    resp = client.post("/api/v1/notifications/subscribe", json={"village_id": _village_id, "phone_number": TEST_PHONE})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "subscribed"
    assert body["phone_number"] == TEST_PHONE

    with session_scope() as db:
        sub = db.scalar(
            select(NotificationSubscription).where(
                NotificationSubscription.village_id == _village_id,
                NotificationSubscription.phone_number == TEST_PHONE,
            )
        )
        assert sub is not None
        assert sub.unsubscribed_at is None


def test_subscribing_twice_is_idempotent_not_a_duplicate_row(_village_id):
    client.post("/api/v1/notifications/subscribe", json={"village_id": _village_id, "phone_number": TEST_PHONE})
    resp = client.post("/api/v1/notifications/subscribe", json={"village_id": _village_id, "phone_number": TEST_PHONE})
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_subscribed"

    with session_scope() as db:
        count = len(
            db.scalars(
                select(NotificationSubscription).where(
                    NotificationSubscription.village_id == _village_id,
                    NotificationSubscription.phone_number == TEST_PHONE,
                    NotificationSubscription.unsubscribed_at.is_(None),
                )
            ).all()
        )
        assert count == 1


def test_unsubscribe_soft_deletes_the_subscription(_village_id):
    client.post("/api/v1/notifications/subscribe", json={"village_id": _village_id, "phone_number": TEST_PHONE})
    resp = client.post("/api/v1/notifications/unsubscribe", json={"village_id": _village_id, "phone_number": TEST_PHONE})
    assert resp.status_code == 200
    assert resp.json()["status"] == "unsubscribed"

    with session_scope() as db:
        sub = db.scalar(
            select(NotificationSubscription).where(
                NotificationSubscription.village_id == _village_id,
                NotificationSubscription.phone_number == TEST_PHONE,
            )
        )
        assert sub is not None
        assert sub.unsubscribed_at is not None


def test_unsubscribing_when_not_subscribed_is_honest_not_an_error(_village_id):
    resp = client.post("/api/v1/notifications/unsubscribe", json={"village_id": _village_id, "phone_number": TEST_PHONE})
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_subscribed"


def test_subscribe_rejects_an_unknown_village():
    resp = client.post("/api/v1/notifications/subscribe", json={"village_id": 999999, "phone_number": TEST_PHONE})
    assert resp.status_code == 404


@pytest.mark.parametrize("bad_phone", ["abc", "123", "", "12345678901234567890"])
def test_subscribe_rejects_an_implausible_phone_number(_village_id, bad_phone):
    resp = client.post("/api/v1/notifications/subscribe", json={"village_id": _village_id, "phone_number": bad_phone})
    assert resp.status_code == 422
