"""
Phase 8: provisions the sensor node registry. Originally Mandakini-only;
extended (Phase 12 follow-up, user-requested) to also cover the Chamoli
Disaster Valley, so the region registry's second `active` valley isn't
left honestly-but-conspicuously at 0/0 sensors forever.

This deliberately mirrors the roadmap's "2-3 ESP32 nodes for the live demo"
(docs/IoT_Architecture.md) rather than instrumenting every village — per
valley, 3 real locations spanning the catchment (source / mid-valley /
outlet, by real elevation and real river topology), each with a rainfall +
soil-moisture pair, matching the two inputs the Phase 4 risk engine
actually consumes per village.

Chamoli's 3 chosen locations — Reni (source, 1973m), Tapovan (mid-valley,
1787m, the real Tapovan-Vishnugad hydropower site destroyed in the 2021
disaster), Vishnuprayag (outlet, 1372m) — follow BOTH the real elevation
order AND the real river topology (Rishiganga from Reni -> Dhauliganga
past Tapovan -> Alaknanda confluence at Vishnuprayag), unlike Joshimath,
whose real elevation famously breaks the app's elevation-order upstream/
downstream proxy for this valley (see docs/Limitations.md, docs/
Data_Sources.md) — Joshimath is deliberately left unsensored here rather
than picked for demo-node placement based on a proxy already flagged as
unreliable at exactly this village.

Nodes are provisioned with NO readings and `last_seen_at = NULL`, so
GET /sensors will honestly report every one of them 'offline' until
iot/simulate_sensor_publisher.py (or real hardware, one day) actually
sends something through iot/mqtt_bridge.py -> POST /sensor-reading. This
script does not fabricate a first reading just to make the dashboard look
populated immediately.

Device-authentication follow-up (user-requested): every node created by
THIS run of the script also gets a real, random API key (only its SHA-256
hash is stored — see app/api/routes/sensors.py); the plaintext is printed
once and saved to iot/device_keys.json (gitignored) for
iot/simulate_sensor_publisher.py / iot/mqtt_bridge.py to use. Re-running
this script never touches an already-provisioned node's key — use
scripts/rotate_sensor_api_keys.py to add or rotate a key for a node that
predates this feature.

Run: cd backend && source .venv/bin/activate && python ../scripts/seed_iot_nodes.py
(Run scripts/seed_pilot_region.py and scripts/seed_chamoli_valley.py first —
this script looks up villages by name.)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select

from app.models.database import session_scope
from app.models.orm import Sensor, SensorStatus, SensorType, Village

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _device_key_utils import (  # noqa: E402
    DEVICE_KEYS_PATH,
    generate_device_api_key,
    hash_device_api_key,
    load_device_keys,
    save_device_keys,
)

# device ids follow the same scheme the real firmware (iot/firmware/*.ino)
# and the bridge simulator (iot/simulate_sensor_publisher.py) use — change
# one place, and all three line up.
NODES = [
    # Mandakini Valley (Phase 8 original 3 nodes)
    dict(external_device_id="esp32-kedarnath-rain-01", village_name="Kedarnath", sensor_type=SensorType.RAINFALL),
    dict(external_device_id="esp32-kedarnath-soil-01", village_name="Kedarnath", sensor_type=SensorType.SOIL_MOISTURE),
    dict(external_device_id="esp32-gaurikund-rain-01", village_name="Gaurikund", sensor_type=SensorType.RAINFALL),
    dict(external_device_id="esp32-gaurikund-soil-01", village_name="Gaurikund", sensor_type=SensorType.SOIL_MOISTURE),
    dict(external_device_id="esp32-rudraprayag-rain-01", village_name="Rudraprayag", sensor_type=SensorType.RAINFALL),
    dict(external_device_id="esp32-rudraprayag-soil-01", village_name="Rudraprayag", sensor_type=SensorType.SOIL_MOISTURE),
    # Chamoli Disaster Valley (Phase 12 follow-up, user-requested) — see
    # module docstring for why Reni/Tapovan/Vishnuprayag, not Joshimath.
    dict(external_device_id="esp32-reni-rain-01", village_name="Reni", sensor_type=SensorType.RAINFALL),
    dict(external_device_id="esp32-reni-soil-01", village_name="Reni", sensor_type=SensorType.SOIL_MOISTURE),
    dict(external_device_id="esp32-tapovan-rain-01", village_name="Tapovan", sensor_type=SensorType.RAINFALL),
    dict(external_device_id="esp32-tapovan-soil-01", village_name="Tapovan", sensor_type=SensorType.SOIL_MOISTURE),
    dict(external_device_id="esp32-vishnuprayag-rain-01", village_name="Vishnuprayag", sensor_type=SensorType.RAINFALL),
    dict(external_device_id="esp32-vishnuprayag-soil-01", village_name="Vishnuprayag", sensor_type=SensorType.SOIL_MOISTURE),
]


def main() -> None:
    with session_scope() as db:
        villages_by_name = {v.name: v for v in db.scalars(select(Village)).all()}
        missing = {n["village_name"] for n in NODES} - set(villages_by_name)
        if missing:
            raise SystemExit(
                f"Villages {missing} not found — run scripts/seed_pilot_region.py first."
            )

        # Device-authentication follow-up (user-requested): every NEWLY
        # provisioned node gets its own real API key here, at creation
        # time — the one moment its plaintext can be known at all (see
        # scripts/_device_key_utils.py's module docstring). An already-
        # existing node is left exactly as it is, key or no key; use
        # scripts/rotate_sensor_api_keys.py to give a pre-existing,
        # never-keyed node a key after the fact.
        device_keys = load_device_keys()
        new_plaintext_keys: dict[str, str] = {}

        created, skipped = 0, 0
        for spec in NODES:
            existing = db.scalar(
                select(Sensor).where(Sensor.external_device_id == spec["external_device_id"])
            )
            if existing is not None:
                skipped += 1
                continue
            plaintext_key = generate_device_api_key()
            new_plaintext_keys[spec["external_device_id"]] = plaintext_key
            db.add(
                Sensor(
                    external_device_id=spec["external_device_id"],
                    village_id=villages_by_name[spec["village_name"]].id,
                    sensor_type=spec["sensor_type"],
                    status=SensorStatus.OFFLINE,
                    last_seen_at=None,
                    battery_pct=None,
                    api_key_hash=hash_device_api_key(plaintext_key),
                )
            )
            created += 1

        if new_plaintext_keys:
            device_keys.update(new_plaintext_keys)
            save_device_keys(device_keys)

        print(f"Provisioned {created} sensor node(s), {skipped} already existed. All start 'offline' until real readings arrive.")
        if new_plaintext_keys:
            print(
                f"Generated {len(new_plaintext_keys)} new device API key(s) — saved to {DEVICE_KEYS_PATH} "
                "(gitignored; this is the only place the plaintext is ever written). "
                "iot/simulate_sensor_publisher.py and iot/mqtt_bridge.py read from this file automatically."
            )


if __name__ == "__main__":
    main()
