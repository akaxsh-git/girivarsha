"""
SMS-reach follow-up (user-requested): lets a villager or authority opt a
phone number in (or out) of SMS alerts for one village. No account/auth
system exists yet — same MVP-appropriate posture already documented for
User/RBAC in docs/Limitations.md — so this needs only a village id + phone
number, not a login. Actual delivery is handled by
app/services/notifications.py, dispatched from app/api/routes/risk.py
whenever a real alert transition warrants it; this route only manages the
subscription list itself.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.orm import NotificationSubscription, Village

router = APIRouter(tags=["notifications"])

# Deliberately permissive (7-15 digits, optional leading +) rather than a
# strict E.164 validator — this app has no way to verify a number is
# actually reachable (that's what the real Twilio provider's own delivery
# status is for), so the goal here is only to reject obvious junk input,
# not to claim a validated phone number format.
_PHONE_RE = re.compile(r"^\+?[0-9]{7,15}$")


class SubscribeRequest(BaseModel):
    village_id: int
    phone_number: str

    @field_validator("phone_number")
    @classmethod
    def _valid_phone(cls, v: str) -> str:
        v = v.strip()
        if not _PHONE_RE.match(v):
            raise ValueError("phone_number must be 7-15 digits, optionally with a leading +")
        return v


class SubscriptionOut(BaseModel):
    village_id: int
    phone_number: str
    status: str  # "subscribed" | "already_subscribed" | "unsubscribed" | "not_subscribed"


@router.post("/notifications/subscribe", response_model=SubscriptionOut)
def subscribe(payload: SubscribeRequest, db: Session = Depends(get_db)):
    village = db.get(Village, payload.village_id)
    if village is None:
        raise HTTPException(status_code=404, detail=f"No village with id={payload.village_id}")

    existing = db.scalar(
        select(NotificationSubscription).where(
            NotificationSubscription.village_id == payload.village_id,
            NotificationSubscription.phone_number == payload.phone_number,
            NotificationSubscription.unsubscribed_at.is_(None),
        )
    )
    if existing is not None:
        return SubscriptionOut(
            village_id=payload.village_id, phone_number=payload.phone_number, status="already_subscribed"
        )

    db.add(NotificationSubscription(village_id=payload.village_id, phone_number=payload.phone_number))
    db.commit()
    return SubscriptionOut(village_id=payload.village_id, phone_number=payload.phone_number, status="subscribed")


@router.post("/notifications/unsubscribe", response_model=SubscriptionOut)
def unsubscribe(payload: SubscribeRequest, db: Session = Depends(get_db)):
    existing = db.scalar(
        select(NotificationSubscription).where(
            NotificationSubscription.village_id == payload.village_id,
            NotificationSubscription.phone_number == payload.phone_number,
            NotificationSubscription.unsubscribed_at.is_(None),
        )
    )
    if existing is None:
        return SubscriptionOut(
            village_id=payload.village_id, phone_number=payload.phone_number, status="not_subscribed"
        )

    existing.unsubscribed_at = datetime.now(timezone.utc)
    db.commit()
    return SubscriptionOut(village_id=payload.village_id, phone_number=payload.phone_number, status="unsubscribed")
