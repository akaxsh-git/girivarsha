"""
Outbound SMS notification adapter — the same DataProvider-style honesty
pattern as app/providers/base.py (real vs. simulated, swappable at runtime
via config), applied to *outbound* alert delivery instead of inbound
readings (user-requested follow-up: "reach" for villagers without a data
connection to see the web dashboard).

Every dispatch attempt returns a DeliveryResult tagged with whether a
message was actually, verifiably accepted by a real carrier (SENT), or was
only logged because no real provider is configured (LOGGED_ONLY) — this
app never claims an SMS reached a phone unless a real provider's own API
response said so.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import httpx

logger = logging.getLogger("girivarsha.notifications")


class DeliveryStatus(str, Enum):
    SENT = "sent"  # a real provider's API confirmed acceptance
    LOGGED_ONLY = "logged_only"  # no real provider configured — recorded, not actually delivered
    FAILED = "failed"  # a real provider was configured and rejected/errored


@dataclass
class DeliveryResult:
    status: DeliveryStatus
    provider_name: str
    detail: str | None = None
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class NotificationProvider(ABC):
    """Base adapter. One concrete subclass per backing SMS gateway."""

    name: str = "base"

    @abstractmethod
    def send_sms(self, *, phone_number: str, message: str) -> DeliveryResult:
        """Attempt to deliver one SMS. Must never raise for an ordinary
        delivery failure — return DeliveryStatus.FAILED instead, so one
        subscriber's bad/disconnected number can't take down an alert
        dispatch loop for every other subscriber."""
        raise NotImplementedError


class LogNotificationProvider(NotificationProvider):
    """Default provider when no real SMS gateway is configured. Records the
    message that WOULD have been sent (server log + the returned
    DeliveryResult, which the frontend's subscribe confirmation surfaces
    honestly) but never claims it reached the phone — status is always
    LOGGED_ONLY, never SENT. This is the honest default for local
    development, exactly the role SimulatedRainfallProvider plays for
    weather data in app/providers/base.py."""

    name = "log_only_v1"

    def send_sms(self, *, phone_number: str, message: str) -> DeliveryResult:
        logger.info("SMS (LOGGED ONLY, not actually sent) to %s: %s", phone_number, message)
        return DeliveryResult(
            status=DeliveryStatus.LOGGED_ONLY,
            provider_name=self.name,
            detail=(
                "No real SMS provider configured — set "
                "GIRIVARSHA_ACTIVE_SMS_PROVIDER=twilio plus "
                "GIRIVARSHA_TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM_NUMBER in "
                "backend/.env to actually deliver messages."
            ),
        )


TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"
TWILIO_TIMEOUT_SECONDS = 8.0


class TwilioSmsProvider(NotificationProvider):
    """Real adapter for Twilio's SMS API (https://www.twilio.com/docs/sms).
    Opt-in only, same posture as RealRainfallProvider/RealSoilMoistureProvider
    in app/providers/base.py — requires real account credentials, never
    activates itself by default.

    Honesty note: this exact HTTP call has not been exercised in this build
    environment — no Twilio account credentials exist here, and outbound
    network reachability to api.twilio.com has not been verified from this
    sandbox (same class of restriction already documented for
    api.open-meteo.com in app/providers/base.py). Anyone with a real Twilio
    trial or paid account can verify it directly by setting the three
    environment variables above."""

    name = "twilio_sms_v1"

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        timeout_seconds: float = TWILIO_TIMEOUT_SECONDS,
    ) -> None:
        self._sid = account_sid
        self._token = auth_token
        self._from = from_number
        self._timeout = timeout_seconds

    def send_sms(self, *, phone_number: str, message: str) -> DeliveryResult:
        url = f"{TWILIO_API_BASE}/Accounts/{self._sid}/Messages.json"
        try:
            response = httpx.post(
                url,
                data={"To": phone_number, "From": self._from, "Body": message},
                auth=(self._sid, self._token),
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return DeliveryResult(
                status=DeliveryStatus.SENT,
                provider_name=self.name,
                detail=f"Twilio accepted message, sid={payload.get('sid')}",
            )
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.warning("Twilio SMS dispatch to %s failed: %r", phone_number, exc)
            return DeliveryResult(
                status=DeliveryStatus.FAILED,
                provider_name=self.name,
                detail=f"Twilio request failed: {exc!r}",
            )


def get_notification_provider(
    active: str,
    *,
    account_sid: str | None,
    auth_token: str | None,
    from_number: str | None,
) -> NotificationProvider:
    """Reads GIRIVARSHA_ACTIVE_SMS_PROVIDER ("log_only" | "twilio"). Falls
    back to LogNotificationProvider — never crashes, never silently claims
    real delivery — if "twilio" is requested but any credential is missing,
    same typo-degrades-honestly philosophy as
    app/providers/base.py::get_rainfall_provider."""
    if active == "twilio" and account_sid and auth_token and from_number:
        return TwilioSmsProvider(account_sid, auth_token, from_number)
    return LogNotificationProvider()
