"""
Dispatches real SMS alerts to villagers/authorities who opted in, when a
real alert transition (app/services/alerts_engine.py::AlertTransition)
actually opens or escalates a village to ORANGE/RED. User-requested
follow-up: web-dashboard-only reach doesn't help someone without a data
connection, which is the realistic case for the population this app is
meant to serve.

Deliberately conservative about when to notify:
  * never on a no-op (AlertTransition is only ever constructed for a real
    change — see alerts_engine.py),
  * never on YELLOW (the lowest, least-actionable alert band) or on a
    "resolved" event — SMS is for the moments a subscriber said they want
    an interruption for, not every state change,
  * never twice for the same underlying alert — the race-condition path in
    sync_alert_for_village deliberately does NOT append a transition for
    the losing side of a genuine concurrent-request race, so this module
    never sees (and can't double-send for) that alert twice.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import AlertLevel, NotificationSubscription
from app.providers.notification import DeliveryResult, NotificationProvider
from app.services.alerts_engine import AlertTransition

# Only these two levels are dispatched as SMS — see module docstring.
NOTIFY_LEVELS = {AlertLevel.ORANGE, AlertLevel.RED}


def should_notify(transition: AlertTransition) -> bool:
    return transition.event in ("opened", "escalated") and transition.level in NOTIFY_LEVELS


def active_subscriptions_for_village(db: Session, village_id: int) -> list[NotificationSubscription]:
    return list(
        db.scalars(
            select(NotificationSubscription).where(
                NotificationSubscription.village_id == village_id,
                NotificationSubscription.unsubscribed_at.is_(None),
            )
        ).all()
    )


def dispatch_transition(
    db: Session, provider: NotificationProvider, transition: AlertTransition
) -> list[DeliveryResult]:
    """Sends (or, with the default LogNotificationProvider, records) one SMS
    per active subscriber to this village, for a real ORANGE/RED
    open/escalation. Returns the DeliveryResult per subscriber notified —
    an empty list is the normal, common case (no subscribers, or a
    transition this module doesn't notify for by design)."""
    if not should_notify(transition):
        return []
    subscriptions = active_subscriptions_for_village(db, transition.village_id)
    if not subscriptions:
        return []
    message = (
        f"Girivarsha alert: {transition.village_name} is now {transition.level.value if transition.level else ''} risk. "
        f"{transition.message or ''} Prototype decision-support signal, not an official warning."
    ).strip()
    return [
        provider.send_sms(phone_number=sub.phone_number, message=message) for sub in subscriptions
    ]
