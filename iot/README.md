# iot/

Phase 8's real IoT pipeline. See `docs/IoT_Architecture.md` for the full status and the exact line between "real" and "simulated" in this pipeline.

- `mqtt_bridge.py` — real MQTT-to-HTTP bridge. Subscribes to `girivarsha/sensors/+/reading` and forwards each message to `POST /api/v1/sensor-reading`. This is the actual production bridge, not a stand-in for anything.
- `simulate_sensor_publisher.py` — stands in for physical ESP32 hardware (none exists in this build environment). Publishes realistic (not uniform-random) rainfall/soil-moisture readings to the same MQTT topics real firmware would use, always declaring `"source": "simulated"`.
- `firmware/rainfall_node/`, `firmware/soil_moisture_node/` — real, buildable ESP32 Arduino sketches. **Not flashed to or tested on physical hardware** — see the honesty note at the top of each `.ino` file.
- `requirements.txt` — deps for the two Python scripts above (`paho-mqtt`, `requests`). Kept separate from `backend/requirements.txt`, same reasoning as `gis/` and `ml/`.
- `device_keys.json` — **gitignored, not committed.** This build's own local record of each device's plaintext API key (device-authentication follow-up — see `docs/IoT_Architecture.md`'s "Sensor authentication" section), written by `scripts/seed_iot_nodes.py` / `scripts/rotate_sensor_api_keys.py` and read by `simulate_sensor_publisher.py`. A real fleet would provision each device's key via its own hardware/config pipeline instead of a shared file like this.

## Running the real pipeline locally

**1. Install and start an MQTT broker** (mosquitto is the easiest option):
```bash
# macOS
brew install mosquitto
brew services start mosquitto
```

**2. Provision the sensor node registry** (run `scripts/seed_pilot_region.py` first if you haven't):
```bash
cd backend && source .venv/bin/activate
python ../scripts/seed_iot_nodes.py
```

**3. Install this folder's dependencies:**
```bash
pip install -r ../iot/requirements.txt
```

**4. Start the bridge** (in one terminal tab — leave it running):
```bash
python ../iot/mqtt_bridge.py --mqtt-host localhost --api-base http://localhost:8000
```

**5. Start the simulated publisher** (in another tab — leave it running, or use `--iterations N` for a short test run):
```bash
python ../iot/simulate_sensor_publisher.py --mqtt-host localhost --interval 5
```

**6. Check it worked:**
```bash
curl http://localhost:8000/api/v1/sensors
```
Every node should show `"status": "online"` with a real `last_value` within a few seconds of step 5 starting, and `"authenticated": true` for every node step 2 just provisioned (it generated a real key for each one — see step 2 output and `device_keys.json`). The Authority dashboard's "Sensor network" panel shows the same thing live.

This exact sequence was run in this project's build environment to verify the pipeline end-to-end — see the transcript in `docs/IoT_Architecture.md`.

## Upgrading an existing deployment onto device authentication

If you provisioned nodes with an older version of `scripts/seed_iot_nodes.py` (before the device-authentication follow-up), they exist with no key on file — `GET /sensors` reports `"authenticated": false` for them, and they keep working exactly as before. To give them real keys:
```bash
cd backend && source .venv/bin/activate
alembic upgrade head                      # picks up migration 5dbcb12077f4 (adds the column)
python ../scripts/rotate_sensor_api_keys.py
```
Then update whatever's actually publishing for those devices (a real board's firmware, or this folder's simulator/bridge — they pick up `device_keys.json` automatically) with its new key before it next reports, or it will start getting `401`s.
