"""
Real-time push + SMS-reach follow-up (user-requested): tests that
`sync_alert_for_village`'s new, purely-additive `transitions` parameter
(app/services/alerts_engine.py) reports exactly the real state changes it
makes — one AlertTransition per opened/escalated/resolved alert, nothing
for a no-op — and that passing it changes nothing about the function's
existing return value or behavior (see test_alerts_race_condition.py for
the race-condition-specific coverage of this same function).

Needs a running, migrated, seeded Postgres — same skip pattern as
test_villages.py.
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

from app.models.database import session_scope  # noqa: E402
from app.models.orm import Alert, AlertLevel, RiskLevel, Village  # noqa: E402
from app.services.alerts_engine import sync_alert_for_village  # noqa: E402
from app.services.risk_engine import RiskAssessment  # noqa: E402

TARGET_VILLAGE_NAME = "Kedarnath"


def _fake_assessment(village_id: int, level: RiskLevel) -> RiskAssessment:
    return RiskAssessment(village_id=village_id, score=0.0, level=level, confidence_pct=0.0, components=[])


@pytest.fixture
def _village_with_no_open_alerts():
    with session_scope() as db:
        village = db.scalar(select(Village).where(Village.name == TARGET_VILLAGE_NAME))
        assert village is not None, f"expected seeded village {TARGET_VILLAGE_NAME!r}"
        village_id = village.id
        db.execute(Alert.__table__.delete().where(Alert.village_id == village_id))
        db.commit()

    yield village_id

    with session_scope() as db:
        db.execute(Alert.__table__.delete().where(Alert.village_id == village_id))
        db.commit()


def test_opening_a_new_alert_reports_one_opened_transition(_village_with_no_open_alerts):
    village_id = _village_with_no_open_alerts
    with session_scope() as db:
        village = db.get(Village, village_id)
        transitions = []
        sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.MODERATE), transitions=transitions)
        db.commit()

    assert len(transitions) == 1
    t = transitions[0]
    assert t.event == "opened"
    assert t.level == AlertLevel.YELLOW
    assert t.village_id == village_id
    assert t.village_name == TARGET_VILLAGE_NAME
    assert t.alert_id is not None


def test_an_unchanged_level_reports_no_transition(_village_with_no_open_alerts):
    village_id = _village_with_no_open_alerts
    with session_scope() as db:
        village = db.get(Village, village_id)
        sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.MODERATE), transitions=[])
        db.commit()

        transitions = []
        sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.MODERATE), transitions=transitions)
        db.commit()

    assert transitions == [], "a no-op (already open at the same level) must not report a transition"


def test_escalation_reports_one_escalated_transition_at_the_new_level(_village_with_no_open_alerts):
    village_id = _village_with_no_open_alerts
    with session_scope() as db:
        village = db.get(Village, village_id)
        sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.MODERATE), transitions=[])
        db.commit()

        transitions = []
        sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.CRITICAL), transitions=transitions)
        db.commit()

    assert len(transitions) == 1
    assert transitions[0].event == "escalated"
    assert transitions[0].level == AlertLevel.RED


def test_dropping_to_low_reports_one_resolved_transition_with_no_level(_village_with_no_open_alerts):
    village_id = _village_with_no_open_alerts
    with session_scope() as db:
        village = db.get(Village, village_id)
        sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.HIGH), transitions=[])
        db.commit()

        transitions = []
        sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.LOW), transitions=transitions)
        db.commit()

    assert len(transitions) == 1
    assert transitions[0].event == "resolved"
    assert transitions[0].level is None


def test_never_having_been_open_and_staying_at_low_reports_nothing(_village_with_no_open_alerts):
    village_id = _village_with_no_open_alerts
    with session_scope() as db:
        village = db.get(Village, village_id)
        transitions = []
        result = sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.LOW), transitions=transitions)
        db.commit()

    assert result is None
    assert transitions == []


def test_omitting_transitions_entirely_still_works_exactly_as_before(_village_with_no_open_alerts):
    """Backward-compatibility guarantee this whole feature depends on: every
    existing caller of sync_alert_for_village that doesn't pass
    `transitions` (there are several across this codebase, and more may be
    added later) must see byte-for-byte identical behavior."""
    village_id = _village_with_no_open_alerts
    with session_scope() as db:
        village = db.get(Village, village_id)
        alert = sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.MODERATE))
        db.commit()
        assert alert is not None
        assert alert.level == AlertLevel.YELLOW
