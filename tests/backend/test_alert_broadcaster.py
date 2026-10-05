"""
Real-time push follow-up (user-requested): unit tests for the in-memory
SSE fan-out in app/services/alert_broadcaster.py. No database needed —
this module has no DB dependency at all, by design (see its own module
docstring on why it's deliberately in-memory, not a broker).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import queue  # noqa: E402

from app.services import alert_broadcaster  # noqa: E402


def test_subscribe_then_publish_delivers_to_the_subscriber():
    q = alert_broadcaster.subscribe()
    try:
        event = {"village_id": 1, "event": "opened"}
        alert_broadcaster.publish(event)
        assert q.get_nowait() == event
    finally:
        alert_broadcaster.unsubscribe(q)


def test_publish_fans_out_to_every_subscriber():
    q1 = alert_broadcaster.subscribe()
    q2 = alert_broadcaster.subscribe()
    try:
        event = {"village_id": 2, "event": "escalated"}
        alert_broadcaster.publish(event)
        assert q1.get_nowait() == event
        assert q2.get_nowait() == event
    finally:
        alert_broadcaster.unsubscribe(q1)
        alert_broadcaster.unsubscribe(q2)


def test_unsubscribe_stops_further_delivery():
    q = alert_broadcaster.subscribe()
    alert_broadcaster.unsubscribe(q)
    alert_broadcaster.publish({"village_id": 3, "event": "opened"})
    assert q.empty(), "an unsubscribed client must not receive events published afterward"


def test_publish_with_no_subscribers_does_not_raise():
    # The common case for most of this app's lifetime (no dashboard tab
    # currently has /alerts/stream open) — must be a complete no-op, never
    # an error that could break the /risk/map request calling it.
    alert_broadcaster.publish({"village_id": 4, "event": "resolved"})


def test_a_full_subscriber_queue_is_dropped_not_blocked():
    q = alert_broadcaster.subscribe()
    try:
        # Fill the queue past its bound — publish() must drop this
        # subscriber (via queue.Full) rather than ever blocking the caller,
        # since publish() runs inline inside a real user-facing request.
        for i in range(alert_broadcaster._QUEUE_MAXSIZE + 5):
            alert_broadcaster.publish({"i": i})
        assert alert_broadcaster.subscriber_count() == 0, "a full subscriber must be unsubscribed automatically"
    finally:
        # Already removed by publish() above in the normal case, but make
        # this test resilient (no leaked subscriber across the test module)
        # even if the maxsize behavior above ever changes.
        alert_broadcaster.unsubscribe(q)


def test_subscriber_count_reflects_active_subscriptions():
    before = alert_broadcaster.subscriber_count()
    q = alert_broadcaster.subscribe()
    try:
        assert alert_broadcaster.subscriber_count() == before + 1
    finally:
        alert_broadcaster.unsubscribe(q)
    assert alert_broadcaster.subscriber_count() == before
