"""
Real bug found live on the user's own machine, not a hypothetical: the
Authority dashboard's Active Alerts panel showed Kedarnath listed THREE
separate times, each its own open ORANGE row, while every other village
appeared once. Traced to `app/services/alerts_engine.py::sync_alert_for_village`
only ever guarding the "one open alert per village" invariant with an
in-app check-then-act (SELECT for an existing open alert, then INSERT if
none/different level) — safe within a single serialized request, but with
nothing enforcing it at the database level, so two genuinely concurrent
requests scoring the same village around the same moment (an overlapping
dashboard poll, a page refresh fired while a previous slow `/risk/map`
call was still in flight — exactly the conditions the pre-performance-fix
~48s `/risk/map` made likely) could both see "no open alert yet" and both
insert one.

Fixed with migration `36ac87f278e4` (a partial unique index: at most one
un-resolved alert per village, enforced by Postgres itself) plus a
SAVEPOINT + IntegrityError-catch in `sync_alert_for_village` so a genuine
race degrades to "adopt whichever request's alert actually won," not a
500 or a second open row.

This suite proves both halves: the raw DB constraint actually rejects a
second concurrent open alert (deterministic — two real sessions, no
thread-timing games needed since Postgres's own MVCC read-committed
semantics make the interleaving exact), and `sync_alert_for_village`
itself handles that exact scenario gracefully via a monkeypatched
`db.flush` that deterministically forces the race window open at exactly
the right moment, without relying on real (flaky) thread scheduling.

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
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.models.database import session_scope  # noqa: E402
from app.models.orm import Alert, AlertLevel, RiskLevel, Village  # noqa: E402
from app.services.alerts_engine import sync_alert_for_village  # noqa: E402
from app.services.risk_engine import RiskAssessment  # noqa: E402

TARGET_VILLAGE_NAME = "Kedarnath"


def _fake_assessment(village_id: int, level: RiskLevel) -> RiskAssessment:
    return RiskAssessment(
        village_id=village_id,
        score=0.0,
        level=level,
        confidence_pct=0.0,
        components=[],
    )


@pytest.fixture
def _village_with_no_open_alerts():
    """Resolves any existing open alert(s) for TARGET_VILLAGE_NAME before
    the test (so it starts from a clean, known state regardless of what
    earlier tests in the same run did to it via /risk/map) and cleans up
    everything this test itself creates afterward."""
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


def test_db_level_constraint_rejects_a_second_concurrent_open_alert(_village_with_no_open_alerts):
    """The actual fix, tested directly against the database: two real,
    independent sessions both see 'no open alert yet' for this village
    (both transactions start before either commits — real MVCC, not a
    simulated race), then both try to open one. The second commit must be
    rejected by the partial unique index, not silently allowed through."""
    village_id = _village_with_no_open_alerts

    with session_scope() as db_a:
        existing_a = db_a.scalar(
            select(Alert).where(Alert.village_id == village_id, Alert.resolved_at.is_(None))
        )
        assert existing_a is None, "fixture should have started from a clean state"

        # A second, fully independent session/transaction — a stand-in for
        # a genuinely concurrent overlapping request — also sees nothing
        # open yet, and wins the race by committing first.
        with session_scope() as db_b:
            existing_b = db_b.scalar(
                select(Alert).where(Alert.village_id == village_id, Alert.resolved_at.is_(None))
            )
            assert existing_b is None
            winner = Alert(village_id=village_id, level=AlertLevel.ORANGE, message="winner")
            db_b.add(winner)
            db_b.commit()

        # db_a's transaction started before db_b committed, so — from its
        # own read-committed snapshot — it still believes no alert is open,
        # exactly like the real bug. Its own insert must now be rejected by
        # the database itself, not silently create a second open row.
        loser = Alert(village_id=village_id, level=AlertLevel.ORANGE, message="loser")
        db_a.add(loser)
        with pytest.raises(IntegrityError):
            db_a.flush()
        # A failed flush leaves the session's transaction in a state that
        # refuses further use (including the implicit commit session_scope
        # issues on a clean exit) until explicitly rolled back — exactly
        # why sync_alert_for_village's own fix uses a SAVEPOINT rather than
        # leaving this to the caller, see alerts_engine.py.
        db_a.rollback()


def test_sync_alert_for_village_adopts_the_winner_on_a_genuine_race(monkeypatch, _village_with_no_open_alerts):
    """The graceful-degradation half of the fix: sync_alert_for_village must
    not raise a 500, and must not leave two open rows, when the exact race
    above happens to it. A monkeypatched db.flush deterministically forces
    a concurrent winner to commit at precisely the moment this function's
    own flush would otherwise have raced it — no thread-timing flakiness."""
    village_id = _village_with_no_open_alerts

    with session_scope() as db:
        village = db.get(Village, village_id)
        real_flush = db.flush

        def _flush_after_a_concurrent_request_wins_first(*args, **kwargs):
            # Stands in for another request's transaction committing this
            # village's first-ever open alert in the exact window between
            # our own "no existing alert" check (already run, above, before
            # sync_alert_for_village's internal flush is reached) and our
            # own insert actually landing.
            with session_scope() as other:
                winner = Alert(village_id=village_id, level=AlertLevel.ORANGE, message="winner (concurrent)")
                other.add(winner)
                other.commit()
            return real_flush(*args, **kwargs)

        monkeypatch.setattr(db, "flush", _flush_after_a_concurrent_request_wins_first)

        result = sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.HIGH))
        db.commit()

    assert result is not None
    assert result.message == "winner (concurrent)", "must adopt the alert that actually won the race"

    with session_scope() as verify:
        open_alerts = verify.scalars(
            select(Alert).where(Alert.village_id == village_id, Alert.resolved_at.is_(None))
        ).all()
        assert len(open_alerts) == 1, (
            f"expected exactly one open alert to survive the race, found {len(open_alerts)} — "
            "this is the exact bug (Kedarnath appearing 3 times in Active Alerts) if it regresses"
        )


def test_ordinary_non_racing_calls_are_unaffected(_village_with_no_open_alerts):
    """Sanity check: the SAVEPOINT/IntegrityError-handling machinery above
    must not change behavior for the overwhelmingly common non-racing case
    — open once, stay open at unchanged level (no-op), transition levels,
    resolve on drop to LOW. Same assertions the pre-fix code already had to
    satisfy, proving nothing about ordinary operation regressed."""
    village_id = _village_with_no_open_alerts

    with session_scope() as db:
        village = db.get(Village, village_id)

        first = sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.MODERATE))
        db.commit()
        assert first is not None
        assert first.level == AlertLevel.YELLOW

        same_level_again = sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.MODERATE))
        db.commit()
        assert same_level_again.id == first.id, "unchanged level must be a no-op, not a new row"

        escalated = sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.CRITICAL))
        db.commit()
        assert escalated.id != first.id
        assert escalated.level == AlertLevel.RED

        resolved = sync_alert_for_village(db, village, _fake_assessment(village_id, RiskLevel.LOW))
        db.commit()
        assert resolved is None

    with session_scope() as verify:
        open_alerts = verify.scalars(
            select(Alert).where(Alert.village_id == village_id, Alert.resolved_at.is_(None))
        ).all()
        assert open_alerts == [], "dropping to LOW must resolve the open alert, leaving none open"
