"""
SMS-reach follow-up (user-requested) unit tests:
  * app/providers/notification.py — LogNotificationProvider (default,
    never claims real delivery), TwilioSmsProvider (real adapter, httpx
    monkeypatched — same "network unverifiable from this sandbox" caveat
    already documented for RealRainfallProvider in test_providers.py), and
    the get_notification_provider fallback-on-missing-credentials behavior.
  * app/services/notifications.py — should_notify()/dispatch_transition()
    dispatch exactly the transitions this app has decided warrant an SMS
    (a real ORANGE/RED open or escalation) and nothing else, using a fake
    NotificationProvider so no real network/DB is needed for this file.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.models.orm import AlertLevel  # noqa: E402
from app.providers.notification import (  # noqa: E402
    DeliveryStatus,
    LogNotificationProvider,
    NotificationProvider,
    TwilioSmsProvider,
    get_notification_provider,
)
from app.services.alerts_engine import AlertTransition  # noqa: E402
from app.services.notifications import dispatch_transition, should_notify  # noqa: E402


class _FakeResponse:
    def __init__(self, json_body: dict, status_code: int = 201):
        self._json_body = json_body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("fake error", request=None, response=self)

    def json(self):
        return self._json_body


def test_log_notification_provider_never_claims_real_delivery():
    provider = LogNotificationProvider()
    result = provider.send_sms(phone_number="+911234567890", message="test")
    assert result.status == DeliveryStatus.LOGGED_ONLY
    assert result.provider_name == "log_only_v1"


def test_twilio_provider_reports_sent_on_a_real_shaped_success_response(monkeypatch):
    def fake_post(url, data=None, auth=None, timeout=None):
        assert "/Messages.json" in url
        assert data["To"] == "+911234567890"
        return _FakeResponse({"sid": "SMfake123"})

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = TwilioSmsProvider("ACfake", "tokenfake", "+15005550006")
    result = provider.send_sms(phone_number="+911234567890", message="test")
    assert result.status == DeliveryStatus.SENT
    assert "SMfake123" in (result.detail or "")


def test_twilio_provider_reports_failed_not_an_exception_on_error(monkeypatch):
    def fake_post(url, data=None, auth=None, timeout=None):
        return _FakeResponse({}, status_code=400)

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = TwilioSmsProvider("ACfake", "tokenfake", "+15005550006")
    # Must never raise — a bad/unreachable number for one subscriber can't
    # be allowed to take down dispatch for every other subscriber.
    result = provider.send_sms(phone_number="+911234567890", message="test")
    assert result.status == DeliveryStatus.FAILED


def test_get_notification_provider_falls_back_to_log_only_without_credentials():
    provider = get_notification_provider("twilio", account_sid=None, auth_token=None, from_number=None)
    assert isinstance(provider, LogNotificationProvider)


def test_get_notification_provider_activates_twilio_only_with_all_three_credentials():
    provider = get_notification_provider(
        "twilio", account_sid="ACfake", auth_token="tokenfake", from_number="+15005550006"
    )
    assert isinstance(provider, TwilioSmsProvider)


class _RecordingProvider(NotificationProvider):
    name = "recording_test_provider"

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send_sms(self, *, phone_number: str, message: str):
        self.sent.append((phone_number, message))
        from app.providers.notification import DeliveryResult

        return DeliveryResult(status=DeliveryStatus.SENT, provider_name=self.name)


def _transition(event, level):
    return AlertTransition(
        village_id=1, village_name="Kedarnath", event=event, level=level, message="msg", alert_id=1
    )


@pytest.mark.parametrize(
    "event,level,expected",
    [
        ("opened", AlertLevel.ORANGE, True),
        ("escalated", AlertLevel.RED, True),
        ("opened", AlertLevel.YELLOW, False),  # lowest band — not SMS-worthy by design
        ("resolved", None, False),  # a "risk dropped" event is not an alert to push
    ],
)
def test_should_notify_matches_the_documented_policy(event, level, expected):
    assert should_notify(_transition(event, level)) is expected


def test_dispatch_transition_is_a_noop_when_should_notify_is_false(monkeypatch):
    provider = _RecordingProvider()

    def _fail(*args, **kwargs):
        raise AssertionError("must not query subscriptions for a transition that isn't SMS-worthy")

    monkeypatch.setattr("app.services.notifications.active_subscriptions_for_village", _fail)
    results = dispatch_transition(db=None, provider=provider, transition=_transition("opened", AlertLevel.YELLOW))
    assert results == []
    assert provider.sent == []


def test_dispatch_transition_sends_to_every_active_subscriber(monkeypatch):
    provider = _RecordingProvider()

    class _FakeSub:
        def __init__(self, phone):
            self.phone_number = phone

    monkeypatch.setattr(
        "app.services.notifications.active_subscriptions_for_village",
        lambda db, village_id: [_FakeSub("+911111111111"), _FakeSub("+912222222222")],
    )
    results = dispatch_transition(db=None, provider=provider, transition=_transition("opened", AlertLevel.RED))
    assert len(results) == 2
    assert {p for p, _ in provider.sent} == {"+911111111111", "+912222222222"}
    assert all("Kedarnath" in msg and "RED" in msg for _, msg in provider.sent)
