"""
Shared helpers for scripts/seed_iot_nodes.py and
scripts/rotate_sensor_api_keys.py (device-authentication follow-up,
user-requested). Not a standalone script — imported by the two above.

`iot/device_keys.json` is this build's own local, gitignored record of
plaintext device API keys — the ONLY place a plaintext key is ever
written or shown, since the database only ever stores its SHA-256 hash
(app/api/routes/sensors.py::hash_device_api_key). A real fleet deployment
would hand each key to its device via a real provisioning step (flashing
NVS/EEPROM, a factory config service, etc.) instead of a shared JSON file
— this file exists because this build environment has no such
provisioning pipeline, and iot/simulate_sensor_publisher.py /
iot/mqtt_bridge.py need *some* real place to read a device's key from to
actually exercise the new auth check end-to-end. Never commit it — see
.gitignore.
"""
from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api.routes.sensors import hash_device_api_key  # noqa: E402  (re-exported for callers)

DEVICE_KEYS_PATH = Path(__file__).resolve().parents[1] / "iot" / "device_keys.json"

__all__ = ["hash_device_api_key", "generate_device_api_key", "load_device_keys", "save_device_keys", "DEVICE_KEYS_PATH"]


def generate_device_api_key() -> str:
    """A fresh, high-entropy per-device key — same construction GitHub/
    Stripe-style tokens use. 32 random bytes, URL-safe base64: no
    ambiguous characters to transcribe, no padding."""
    return secrets.token_urlsafe(32)


def load_device_keys() -> dict[str, str]:
    if not DEVICE_KEYS_PATH.exists():
        return {}
    return json.loads(DEVICE_KEYS_PATH.read_text())


def save_device_keys(keys: dict[str, str]) -> None:
    DEVICE_KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEVICE_KEYS_PATH.write_text(json.dumps(keys, indent=2, sort_keys=True) + "\n")
