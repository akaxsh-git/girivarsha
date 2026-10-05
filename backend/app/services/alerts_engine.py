"""
Phase 4: turns a RiskAssessment into an Alert row, with a small explicit
state machine — not a fresh row on every single request. GREEN/no-alert
never gets a row (a "no alert" alert is meaningless); YELLOW/ORANGE/RED
open one open Alert per village, updating its level in place if risk
moves between bands, and closing it (resolved_at set) when risk drops back
to LOW.

Alert level maps 1:1 from risk level — a transparent baseline stays
transparent all the way to the alert, no separate undocumented threshold
set introduced here.

Real bug found and fixed here (Phase 15+ follow-up): the "one open alert
per village" invariant this docstring already claimed was only ever
enforced by the check-then-act logic below (SELECT for an existing open
alert, then INSERT if none/different) — safe within a single serialized
request, but with nothing backing it up at the database level, two
genuinely concurrent requests scoring the SAME village around the same
moment (an overlapping dashboard poll, a page refresh fired while a
previous slow `/risk/map` call was still in flight) could both see "no
open alert yet" and both insert one — observed live as the same village
appearing multiple times in the Active Alerts panel. A new partial unique
index (migration `36ac87f278e4`) now enforces this invariant for real;
`sync_alert_for_village` below catches the resulting `IntegrityError` on a
genuine race and adopts whichever request's alert actually won, instead of
letting a 500 escape or leaving two open rows for one village.

Real-time push + SMS follow-up (user-requested): callers that want to react
to an actual state change (open a new alert, escalate/de-escalate an
existing one, or resolve one) — rather than just the final Alert row — can
pass a `transitions` list; `sync_alert_for_village` appends one
`AlertTransition` to it for every REAL change it makes, and appends
nothing on a no-op (already open at the same level). This is purely
additive: existing callers that don't pass `transitions` see byte-for-byte
identical behavior and return value. See
app/services/alert_broadcaster.py (SSE push) and
app/services/notifications.py (SMS dispatch), both driven off this list
from app/api/routes/risk.py — never off a fabricated or synthetic event.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.orm import Alert, AlertLevel, RiskLevel, Village
from app.services.risk_engine import RiskAssessment


@dataclass(frozen=True)
class AlertTransition:
    """One real, already-committed-or-about-to-be-committed change to a
    village's alert state — never constructed for a no-op. `level` is None
    only for a "resolved" event (dropped back to GREEN, no alert level
    applies)."""

    village_id: int
    village_name: str
    event: Literal["opened", "escalated", "resolved"]
    level: AlertLevel | None
    message: str | None
    alert_id: int | None

RISK_TO_ALERT = {
    RiskLevel.LOW: AlertLevel.GREEN,
    RiskLevel.MODERATE: AlertLevel.YELLOW,
    RiskLevel.HIGH: AlertLevel.ORANGE,
    RiskLevel.CRITICAL: AlertLevel.RED,
}

ALERT_MESSAGES = {
    AlertLevel.YELLOW: "Elevated risk indicators — monitor conditions. Prototype baseline signal, not an official warning.",
    AlertLevel.ORANGE: "High risk indicators — heightened caution advised. Prototype baseline signal, not an official warning.",
    AlertLevel.RED: "Critical risk indicators — take precaution and follow local authority guidance. Prototype baseline signal, not an official warning.",
}


def sync_alert_for_village(
    db: Session,
    village: Village,
    assessment: RiskAssessment,
    transitions: list[AlertTransition] | None = None,
) -> Alert | None:
    """Returns the currently-open Alert for this village after syncing it to
    the latest assessment (or None if the village is at LOW/GREEN and has no
    open alert). Does not commit — caller controls the transaction.

    `transitions` is optional and purely additive (see module docstring) —
    when given, one AlertTransition is appended for every real state change
    this call makes; nothing is appended for a no-op."""
    new_level = RISK_TO_ALERT[assessment.level]
    existing = db.scalar(
        select(Alert).where(Alert.village_id == village.id, Alert.resolved_at.is_(None))
    )

    if new_level == AlertLevel.GREEN:
        if existing is not None:
            existing.resolved_at = datetime.now(timezone.utc)
            if transitions is not None:
                transitions.append(
                    AlertTransition(
                        village_id=village.id,
                        village_name=village.name,
                        event="resolved",
                        level=None,
                        message=None,
                        alert_id=existing.id,
                    )
                )
        return None

    if existing is not None and existing.level == new_level:
        return existing  # already open at the right level — no-op, no duplicate row

    event: Literal["opened", "escalated"] = "escalated" if existing is not None else "opened"

    if existing is not None:
        existing.resolved_at = datetime.now(timezone.utc)

    alert = Alert(
        village_id=village.id,
        risk_prediction_id=None,  # linked by caller once the RiskPrediction row is flushed, if desired
        level=new_level,
        message=ALERT_MESSAGES[new_level],
    )
    db.add(alert)
    try:
        # A SAVEPOINT (not the outer transaction) around just this insert —
        # so a unique-violation here only unwinds this one insert, never the
        # whole /risk/map request's transaction (which still has other
        # villages' work pending in the same session).
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        # Real race, not a bug in this village's own logic: another request
        # (see module docstring) won the "open this village's alert" race
        # between our SELECT above and this INSERT — the partial unique
        # index caught it. Don't create a second open row; adopt whichever
        # one actually landed instead. Deliberately does NOT append a
        # transition here — the request that actually won the race already
        # reports its own "opened"/"escalated" transition, so reporting one
        # here too would double-broadcast/double-SMS the exact same alert.
        db.expunge(alert)
        return db.scalar(
            select(Alert).where(Alert.village_id == village.id, Alert.resolved_at.is_(None))
        )
    if transitions is not None:
        transitions.append(
            AlertTransition(
                village_id=village.id,
                village_name=village.name,
                event=event,
                level=new_level,
                message=alert.message,
                alert_id=alert.id,
            )
        )
    return alert
