"""
Phase 8: stands in for the physical ESP32 nodes on the MQTT side, since no
real hardware exists in this build environment (see docs/IoT_Architecture.md
for exactly what that means and doesn't mean).

This is the ONLY simulated component of the Phase 8 pipeline — it publishes
to the same MQTT topics real firmware (iot/firmware/*.ino) would use, with
the same JSON payload shape, and always declares "source": "simulated" so
nothing downstream can mistake it for a real observation. Everything after
the broker (iot/mqtt_bridge.py, the backend ingestion endpoint, the
database) is real and processes these messages exactly as it would process
messages from real hardware.

Readings are NOT uniform random noise — rainfall follows a slow drifting
base rate with occasional short "storm bursts" (same honesty-tested pattern
as ml/generate_synthetic_training_data.py's storm-day mechanic), and soil
moisture responds to recent rainfall with lag/decay rather than moving
independently — because a flat random-noise stream would be an even less
defensible stand-in for real sensor behaviour than this.

Device authentication (user-requested follow-up): if scripts/seed_iot_nodes.py
has generated a key for a given device (iot/device_keys.json — gitignored,
see scripts/_device_key_utils.py), that plaintext key is included in the
published payload's "api_key" field, exactly as real firmware would send
its own flashed-in key (see iot/firmware/*/*.ino) — iot/mqtt_bridge.py
forwards it to the backend as the X-Device-Api-Key header. A device with
no known key (not yet provisioned with one) publishes without "api_key",
matching the honest un-authenticated fallback the backend still accepts
for those nodes.

Usage:
    pip install -r iot/requirements.txt
    python iot/simulate_sensor_publisher.py --mqtt-host localhost --interval 5
    python iot/simulate_sensor_publisher.py --interval 2 --iterations 5   # short run for testing
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

import paho.mqtt.client as mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("simulate_sensor_publisher")

DEVICE_KEYS_PATH = Path(__file__).resolve().parent / "device_keys.json"


def _load_device_keys() -> dict[str, str]:
    if not DEVICE_KEYS_PATH.exists():
        log.warning(
            "%s not found — publishing without api_key for every device "
            "(run scripts/seed_iot_nodes.py or scripts/rotate_sensor_api_keys.py to provision keys)",
            DEVICE_KEYS_PATH,
        )
        return {}
    with DEVICE_KEYS_PATH.open() as f:
        return json.load(f)

# Must match scripts/seed_iot_nodes.py exactly — same device ids, same
# locations, so the simulator's traffic lines up with what was provisioned.
# Reni/Tapovan/Vishnuprayag (Chamoli Disaster Valley) added alongside the
# original Mandakini trio — Phase 12 follow-up, user-requested.
LOCATIONS = ["kedarnath", "gaurikund", "rudraprayag", "reni", "tapovan", "vishnuprayag"]


@dataclass
class LocationState:
    rain_mm_hr: float = 0.5
    storm_ticks_remaining: int = 0
    soil_pct: float = 32.0


def step_location(state: LocationState, rng: random.Random) -> None:
    # Rainfall: slow drift, with a small per-tick chance of entering a
    # multi-tick storm burst (mirrors ml/generate_synthetic_training_data.py).
    if state.storm_ticks_remaining > 0:
        state.rain_mm_hr = max(0.0, state.rain_mm_hr + rng.uniform(-3, 4))
        state.storm_ticks_remaining -= 1
    else:
        state.rain_mm_hr = max(0.0, state.rain_mm_hr + rng.uniform(-0.8, 0.8))
        if rng.random() < 0.04:
            state.storm_ticks_remaining = rng.randint(3, 8)
            state.rain_mm_hr += rng.uniform(8, 25)
    state.rain_mm_hr = round(min(state.rain_mm_hr, 60.0), 1)

    # Soil moisture: rises when it's raining, decays slowly otherwise —
    # never an independent random walk.
    if state.rain_mm_hr > 2:
        state.soil_pct += min(3.0, state.rain_mm_hr * 0.08)
    else:
        state.soil_pct -= 0.3
    state.soil_pct = round(min(max(state.soil_pct, 8.0), 96.0), 1)


def publish(client: mqtt.Client, device_id: str, value: float, unit: str, device_keys: dict[str, str]) -> None:
    topic = f"girivarsha/sensors/{device_id}/reading"
    body: dict[str, object] = {"value": value, "unit": unit, "source": "simulated"}
    api_key = device_keys.get(device_id)
    if api_key:
        body["api_key"] = api_key
    payload = json.dumps(body)
    result = client.publish(topic, payload, qos=1)
    result.wait_for_publish(timeout=5)
    log.info(
        "Published %s -> %s = %s %s (authenticated=%s)",
        topic, device_id, value, unit, bool(api_key),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mqtt-host", default="localhost")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between publish rounds")
    parser.add_argument("--iterations", type=int, default=None, help="Stop after N rounds (omit to run forever)")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    states = {loc: LocationState() for loc in LOCATIONS}
    device_keys = _load_device_keys()

    # Real bug found and fixed (reported live from the user's own machine):
    # client.connect() only starts the TCP handshake — it returns before the
    # broker's CONNACK actually arrives. The old code called loop_start()
    # and immediately began publishing, so if the broker was even slightly
    # slow to accept the connection, the very first publish()'s
    # wait_for_publish() would raise "the client is not currently
    # connected." Fixed by waiting for the real on_connect callback (with a
    # bounded timeout, so a genuinely unreachable broker still fails fast
    # and honestly rather than hanging forever) before publishing anything
    # — the same "wait for the real event, don't assume the moment you
    # asked" discipline iot/mqtt_bridge.py's own on_connect already uses.
    connected = {"ok": False}

    def _on_connect(_client, _userdata, _flags, reason_code, _properties=None):
        connected["ok"] = reason_code == 0
        if reason_code == 0:
            log.info("Connected to MQTT broker %s:%s — simulating %d locations", args.mqtt_host, args.mqtt_port, len(LOCATIONS))
        else:
            log.error("MQTT connect failed: %s", reason_code)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="girivarsha-sensor-simulator")
    client.on_connect = _on_connect
    try:
        client.connect(args.mqtt_host, args.mqtt_port, keepalive=30)
    except Exception as exc:
        # A genuinely unreachable broker (not running, wrong host/port)
        # raises synchronously here, before on_connect ever fires — same
        # honest fail-fast handling iot/mqtt_bridge.py's own connect() call
        # already has, instead of a bare, unhelpful traceback.
        log.error("Could not reach MQTT broker at %s:%s (%s) — is mosquitto running?", args.mqtt_host, args.mqtt_port, exc)
        return
    client.loop_start()

    wait_deadline = time.monotonic() + 10.0
    while not connected["ok"] and time.monotonic() < wait_deadline:
        time.sleep(0.1)
    if not connected["ok"]:
        log.error("Could not connect to MQTT broker at %s:%s within 10s — is mosquitto running?", args.mqtt_host, args.mqtt_port)
        client.loop_stop()
        return

    i = 0
    try:
        while args.iterations is None or i < args.iterations:
            for loc in LOCATIONS:
                step_location(states[loc], rng)
                publish(client, f"esp32-{loc}-rain-01", states[loc].rain_mm_hr, "mm/hr", device_keys)
                publish(client, f"esp32-{loc}-soil-01", states[loc].soil_pct, "pct", device_keys)
            i += 1
            if args.iterations is None or i < args.iterations:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
        log.info("Simulator stopped after %d round(s).", i)


if __name__ == "__main__":
    main()
