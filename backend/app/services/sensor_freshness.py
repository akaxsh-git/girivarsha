"""
Shared freshness-status computation for real sensor readings.

Extracted out of app/api/routes/sensors.py (Phase 8) so that this Phase 8+
follow-up (wiring real sensor readings into the Phase 4 risk engine's
providers) uses the EXACT same online/stale/offline thresholds and logic as
GET /sensors — a village's risk score and its sensor-panel status must never
be computed from two different freshness definitions that could quietly
drift apart. Status is always recomputed live from `last_seen_at`, never
trusted from a stored column (same discipline as everywhere else in this
codebase — see the module docstring in app/models/schemas.py's SensorOut).
"""
from __future__ import annotations

from datetime import datetime

from app.core.config import get_settings
from app.models.orm import SensorStatus


def compute_sensor_status(last_seen_at: datetime | None, *, now: datetime) -> tuple[str, float | None]:
    """Returns (status, age_seconds). A node with no reading yet is honestly
    'offline', not defaulted to 'online'."""
    settings = get_settings()
    if last_seen_at is None:
        return SensorStatus.OFFLINE.value, None
    age_seconds = (now - last_seen_at).total_seconds()
    if age_seconds <= settings.sensor_thresholds.online_max_seconds:
        return SensorStatus.ONLINE.value, age_seconds
    if age_seconds <= settings.sensor_thresholds.stale_max_seconds:
        return SensorStatus.STALE.value, age_seconds
    return SensorStatus.OFFLINE.value, age_seconds
