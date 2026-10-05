"""
Device-authentication follow-up (user-requested): gives a real API key to
every sensor that doesn't have one yet — the upgrade path for nodes
provisioned by scripts/seed_iot_nodes.py in a session BEFORE this feature
existed. Those nodes have `api_key_hash IS NULL` (the migration
5dbcb12077f4_phase17_sensor_api_keys.py added the column without
backfilling one, since there was never a plaintext to hash), and
POST /sensor-reading keeps accepting their requests un-authenticated until
this script — or a deliberate --force rotation — gives them a key.

By default, only touches sensors with NO key on file, so re-running this
is safe and idempotent: it never silently invalidates a key already
handed to a real device. Pass --force to rotate EVERY sensor's key
(including ones that already have one) — use this only when you actually
mean to invalidate and reissue every device's credential (e.g. a suspected
leak of iot/device_keys.json itself); every device using the old key will
be rejected with 401 until it's reconfigured with the new one.

Run:
    cd backend && source .venv/bin/activate && python ../scripts/rotate_sensor_api_keys.py
    python scripts/rotate_sensor_api_keys.py --force   # rotate ALL, not just keyless ones
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select

from app.models.database import session_scope
from app.models.orm import Sensor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _device_key_utils import (  # noqa: E402
    DEVICE_KEYS_PATH,
    generate_device_api_key,
    hash_device_api_key,
    load_device_keys,
    save_device_keys,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rotate EVERY sensor's key, including ones that already have one (invalidates the old key immediately).",
    )
    args = parser.parse_args()

    device_keys = load_device_keys()
    rotated: dict[str, str] = {}

    with session_scope() as db:
        sensors = db.scalars(select(Sensor)).all()
        if not sensors:
            print("No sensors registered yet — run scripts/seed_iot_nodes.py first.")
            return

        targets = sensors if args.force else [s for s in sensors if s.api_key_hash is None]
        if not targets:
            print(f"All {len(sensors)} registered sensor(s) already have an API key — nothing to do. Pass --force to reissue anyway.")
            return

        for sensor in targets:
            plaintext_key = generate_device_api_key()
            sensor.api_key_hash = hash_device_api_key(plaintext_key)
            rotated[sensor.external_device_id] = plaintext_key
        db.commit()

    device_keys.update(rotated)
    save_device_keys(device_keys)

    verb = "Rotated" if args.force else "Issued"
    print(f"{verb} {len(rotated)} device API key(s) — saved to {DEVICE_KEYS_PATH} (gitignored).")
    print("Update any already-deployed device/bridge config with its new key before it next reports, or it will start getting 401s.")
    for device_id in sorted(rotated):
        print(f"  {device_id}")


if __name__ == "__main__":
    main()
