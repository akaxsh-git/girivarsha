"""
Phase 8: real MQTT-to-HTTP bridge.

Subscribes to `girivarsha/sensors/+/reading` on an MQTT broker and forwards
every message onto the real backend ingestion endpoint,
POST /api/v1/sensor-reading. This is exactly the service a production
deployment would run between the MQTT broker and the backend — nothing
about this script is a stand-in or simulation; it's the real bridge.

The device publishing to MQTT (real ESP32 firmware — see iot/firmware/ —
or, in this build environment where no physical hardware exists,
iot/simulate_sensor_publisher.py standing in for it) is the only simulated
part of this pipeline. Everything downstream of the broker, including this
script, is real code that was actually run — see docs/IoT_Architecture.md
for the verification transcript.

Usage:
    pip install -r iot/requirements.txt
    python iot/mqtt_bridge.py --mqtt-host localhost --api-base http://localhost:8000

Topic scheme: girivarsha/sensors/<external_device_id>/reading
Payload (JSON): {"value": <float>, "unit": "<str>", "source": "real"|"simulated"|"derived", "observed_at": "<ISO8601>" (optional), "api_key": "<str>" (optional)}
The device id is taken from the TOPIC, not trusted from the payload body —
a compromised/misconfigured device can't spoof another node's identity by
editing its own payload.

Device authentication (user-requested follow-up): "api_key" is this
device's own credential (real firmware — iot/firmware/*/*.ino — sends its
flashed-in key; iot/simulate_sensor_publisher.py sends whichever key
scripts/seed_iot_nodes.py generated for it, if any). This bridge forwards
it verbatim as the X-Device-Api-Key HTTP header — it never inspects,
stores, or needs to know any device's key itself, so a compromised bridge
config exposes nothing devices haven't already published. A device that
sends no "api_key" is forwarded with no header, which the backend still
accepts for a sensor that has no key on file yet (see
app/api/routes/sensors.py).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

import paho.mqtt.client as mqtt
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("mqtt_bridge")

TOPIC_FILTER = "girivarsha/sensors/+/reading"


def make_on_message(api_base: str):
    def on_message(_client, _userdata, msg: mqtt.MQTTMessage) -> None:
        parts = msg.topic.split("/")
        if len(parts) != 4 or parts[0] != "girivarsha" or parts[1] != "sensors" or parts[3] != "reading":
            log.warning("Ignoring message on unexpected topic %s", msg.topic)
            return
        device_id = parts[2]

        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            log.warning("Dropping malformed payload on %s: %s", msg.topic, exc)
            return

        body = {
            "external_device_id": device_id,
            "value": payload.get("value"),
            "unit": payload.get("unit"),
            "source": payload.get("source", "simulated"),
        }
        if payload.get("observed_at"):
            body["observed_at"] = payload["observed_at"]

        # Device authentication (user-requested follow-up): forward this
        # device's own key, if it sent one, as the header the backend
        # checks — never as part of the JSON body, so it never ends up
        # logged or stored alongside the reading data itself.
        headers = {}
        api_key = payload.get("api_key")
        if api_key:
            headers["X-Device-Api-Key"] = api_key

        try:
            resp = requests.post(f"{api_base}/api/v1/sensor-reading", json=body, headers=headers, timeout=5)
        except requests.RequestException as exc:
            log.error("Backend unreachable forwarding %s: %s", device_id, exc)
            return

        if resp.status_code == 201:
            log.info("Forwarded %s = %s %s (source=%s) -> backend OK", device_id, body["value"], body["unit"], body["source"])
        elif resp.status_code == 404:
            log.error("Backend rejected %s: unregistered device (run scripts/seed_iot_nodes.py)", device_id)
        elif resp.status_code == 401:
            log.error("Backend rejected %s: missing or invalid API key (run scripts/rotate_sensor_api_keys.py?)", device_id)
        else:
            log.error("Backend rejected %s: HTTP %s %s", device_id, resp.status_code, resp.text[:200])

    return on_message


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mqtt-host", default="localhost")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--api-base", default="http://localhost:8000")
    parser.add_argument("--duration", type=float, default=None, help="Exit after N seconds (omit to run forever — for real deployment)")
    args = parser.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="girivarsha-mqtt-bridge")
    client.on_message = make_on_message(args.api_base)

    def on_connect(_client, _userdata, _flags, reason_code, _properties=None):
        if reason_code == 0:
            log.info("Connected to MQTT broker %s:%s", args.mqtt_host, args.mqtt_port)
            client.subscribe(TOPIC_FILTER)
            log.info("Subscribed to %s", TOPIC_FILTER)
        else:
            log.error("MQTT connect failed: %s", reason_code)

    client.on_connect = on_connect

    try:
        client.connect(args.mqtt_host, args.mqtt_port, keepalive=30)
    except Exception as exc:
        log.error("Could not reach MQTT broker at %s:%s (%s) — is mosquitto running?", args.mqtt_host, args.mqtt_port, exc)
        sys.exit(1)

    client.loop_start()
    try:
        if args.duration:
            time.sleep(args.duration)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
        log.info("Bridge stopped.")


if __name__ == "__main__":
    main()
