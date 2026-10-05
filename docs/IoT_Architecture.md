# IoT Architecture

**Status: Phase 8 complete, extended to a second valley (Phase 12 follow-up, user-requested).** Real pipeline, actually built and run end-to-end in this build environment — with one honest gap: no physical ESP32 hardware exists here, so the publisher standing at the very start of the pipeline is a simulator, not a board. Everything downstream of that is real code that was actually executed, not just written.

## What's real vs. simulated — the exact line

```
ESP32 firmware (iot/firmware/*/*.ino)          <-- REAL CODE, NOT flashed/tested on hardware
      │  MQTT publish (JSON)                       (no physical boards in this build env)
      ▼
─────────────────────────────────────────────  <-- this line is where "simulated" ends
MQTT broker (mosquitto)                        <-- REAL — actually installed and run
      │
      ▼
iot/mqtt_bridge.py                             <-- REAL — actually run, subscribes + forwards
      │  HTTP POST
      ▼
POST /api/v1/sensor-reading                    <-- REAL — DB-backed, tested (tests/backend/test_sensors.py)
      │
      ▼
Postgres (sensors, sensor_readings tables)     <-- REAL — Phase 2 schema, actually populated
      │
      ▼
GET /api/v1/sensors, /sensor-readings          <-- REAL — live-computed status, tested
      │
      ▼
Authority dashboard "Sensor network" panel     <-- REAL — Phase 8 frontend
```

`iot/simulate_sensor_publisher.py` is the only simulated piece — it stands in for the missing physical boards on the MQTT side, publishing to the exact same topics and JSON shape real firmware would use, and always declaring `"source": "simulated"` so nothing downstream can mistake it for a real observation. Real firmware sketches exist (`iot/firmware/rainfall_node/`, `iot/firmware/soil_moisture_node/`) — genuine, buildable Arduino/ESP32 C++ against WiFi.h + PubSubClient + ArduinoJson — but they have not been flashed to or tested on actual boards, because none exist in this build environment. That gap is stated here, not hidden.

## Verified end-to-end run (this build environment, 2026-09-04)

This was actually executed, not just described:

1. Installed and started a real `mosquitto` MQTT broker.
2. Provisioned 6 real sensor nodes (`scripts/seed_iot_nodes.py`) — 3 pilot locations (Kedarnath/source, Gaurikund/mid-valley, Rudraprayag/outlet) × 2 sensor types (rainfall, soil moisture) — matching the two inputs the Phase 4 risk engine consumes per village. Every node started honestly `offline`, since none had reported yet.
3. Started `iot/mqtt_bridge.py`, which connected to the broker and subscribed to `girivarsha/sensors/+/reading`.
4. Ran `iot/simulate_sensor_publisher.py` for several rounds. It published realistic (not uniform-random) rainfall/soil-moisture values to MQTT.
5. Confirmed in the bridge's log that every message was received and forwarded via `POST /api/v1/sensor-reading`, and the backend returned `201` for each:
   ```
   Forwarded esp32-kedarnath-rain-01 = 12.9 mm/hr (source=simulated) -> backend OK
   Forwarded esp32-kedarnath-soil-01 = 33.0 pct (source=simulated) -> backend OK
   ... (24 messages total across 4 rounds x 6 devices)
   ```
6. Confirmed via `GET /api/v1/sensors` that every node correctly flipped to `"status": "online"` with the right `last_value`/`last_unit`, computed live from freshness (not a stored flag) — and via `GET /api/v1/sensor-readings` that the individual readings landed in Postgres with `"source": "simulated"` intact.

This proves the entire pipeline mechanics are correct — the broker, the bridge, the ingestion contract, the freshness-based status computation, and the database round-trip. It does not prove anything about real-world sensor hardware, which this build environment cannot possess.

## Extended to the Chamoli Disaster Valley (Phase 12 follow-up, user-requested, 2026-09-04)

Phase 8's sensor network originally covered Mandakini only — Phase 11's second `active` region (Chamoli) had real village/catchment/risk data from day one but sat at an honest, if conspicuous, `0/0` sensors on the Authority dashboard. Re-ran the exact same verification as above with the extended fleet:

1. Provisioned 6 more real sensor nodes for Chamoli — **Reni (source, 1973m), Tapovan (mid-valley, 1787m — the real Tapovan-Vishnugad hydropower site destroyed in the 2021 disaster), Vishnuprayag (outlet, 1372m)** × 2 sensor types. **Joshimath was deliberately left unsensored** — see `scripts/seed_iot_nodes.py`'s docstring: Joshimath's real elevation is documented elsewhere in this repo (`docs/Limitations.md`, `docs/Data_Sources.md`) as breaking the app's elevation-order upstream/downstream proxy for this valley, so picking it for demo-node placement based on the same unreliable proxy would compound the issue rather than sidestep it. Reni → Tapovan → Vishnuprayag matches BOTH real elevation order and real river topology.
2. `iot/simulate_sensor_publisher.py`'s `LOCATIONS` list extended to include `reni`, `tapovan`, `vishnuprayag` alongside the original three.
3. Re-ran the full broker → bridge → ingestion → `GET /sensors` chain. All 12 devices (6 Mandakini + 6 Chamoli) confirmed `"status": "online"` with real, freshly-computed values; bridge log confirmed all 12 real-time forwards returned `201`.
4. Confirmed via the Authority dashboard, scoped to "Chamoli Disaster Valley," that "Sensors online" reads `6/6` (was `0/0`) and the Sensor network panel lists exactly the 6 real Chamoli devices with real village names — no Mandakini sensor leaking into the Chamoli-scoped view, and no fabricated Joshimath entry.
5. New regression test (`tests/backend/test_sensors.py::test_chamoli_sensor_nodes_are_correctly_linked_to_chamoli_villages`) guards against a future edit accidentally cross-wiring a Chamoli device id to a Mandakini village, and asserts Joshimath specifically has none.

## Sensor node registry (`scripts/seed_iot_nodes.py`)

| Device ID | Location | Type |
|---|---|---|
| `esp32-kedarnath-rain-01` / `-soil-01` | Kedarnath (Mandakini, catchment source, 3583m) | rainfall / soil moisture |
| `esp32-gaurikund-rain-01` / `-soil-01` | Gaurikund (Mandakini, mid-valley, 1982m) | rainfall / soil moisture |
| `esp32-rudraprayag-rain-01` / `-soil-01` | Rudraprayag (Mandakini, catchment outlet, 895m) | rainfall / soil moisture |
| `esp32-reni-rain-01` / `-soil-01` | Reni (Chamoli, catchment source, 1973m) | rainfall / soil moisture |
| `esp32-tapovan-rain-01` / `-soil-01` | Tapovan (Chamoli, mid-valley, 1787m) | rainfall / soil moisture |
| `esp32-vishnuprayag-rain-01` / `-soil-01` | Vishnuprayag (Chamoli, catchment outlet, 1372m) | rainfall / soil moisture |

## Status computation (problem-statement item 24)

`GET /sensors` never trusts a stored `status` column blindly — it recomputes `online` / `stale` / `offline` on every request from `now - last_seen_at`, using configurable thresholds (`GIRIVARSHA_SENSOR_THRESHOLDS__ONLINE_MAX_SECONDS` / `..._STALE_MAX_SECONDS`, default 300s / 1800s). A node that silently stops publishing can never keep reporting a stale "online" forever.

## Sensor authentication (user-requested follow-up — done)

Previously not implemented — the ingestion endpoint trusted any request naming a registered `external_device_id`, with no credential check at all. This is now closed with real per-device API keys, without needing an account/RBAC system (there isn't one — see `docs/Limitations.md`) or mTLS (real, but heavier to stand up than this app's demo MQTT broker needs right now; tracked as a possible future hardening step, not required for this fix).

**Design.** Each provisioned sensor may have an `api_key_hash` (`sensors.api_key_hash`, migration `5dbcb12077f4`) — a SHA-256 hex digest of a real, random per-device key (`secrets.token_urlsafe(32)`, generated in `scripts/seed_iot_nodes.py` at provisioning time, or afterwards via `scripts/rotate_sensor_api_keys.py`). No per-key salt: the key is already a high-entropy random token, not a human password, so an unsalted hash carries no meaningful rainbow-table risk — the same reasoning GitHub/Stripe-style API tokens rely on. The plaintext is shown exactly once, at generation time, and is otherwise recoverable only from `iot/device_keys.json` — a local, gitignored file this build environment uses in place of a real fleet's own device-provisioning pipeline (flashing NVS, a factory-config service, etc.), which `iot/simulate_sensor_publisher.py` and `iot/mqtt_bridge.py` read from so the whole pipeline can be exercised end-to-end without physical hardware.

**End-to-end flow, unchanged topology, one new hop.** A device includes its own key in its published MQTT payload's `"api_key"` field (real firmware — `iot/firmware/*/*.ino` — reads it from a `DEVICE_API_KEY` constant, with an explicit honesty note in each file that a real fleet would provision this per-board, not via committed source; the simulator reads it from `iot/device_keys.json`). `iot/mqtt_bridge.py` forwards it verbatim as the `X-Device-Api-Key` HTTP header — the bridge never inspects, stores, or needs to know any device's key itself, so a compromised bridge exposes nothing devices haven't already published to the broker. `app/api/routes/sensors.py::post_sensor_reading` hashes the header value and compares it to the stored hash with `hmac.compare_digest` (constant-time, so response timing can't be used to guess a key byte-by-byte); a missing or wrong key gets a `401`, distinctly logged by the bridge (`"missing or invalid API key"`) alongside its existing `404`/other-error handling.

**Honestly staged rollout, not a retroactive lockout.** `api_key_hash` is nullable specifically because this column was added after real sensor rows already existed in past sessions' seeded databases, with no way to recover a plaintext key for any of them. A sensor with `api_key_hash IS NULL` is accepted un-authenticated — the exact pre-migration behavior, completely unchanged — until `scripts/rotate_sensor_api_keys.py` gives it a real key (idempotent by default: it only touches keyless sensors, never silently rotates one already in use; `--force` exists for a deliberate full reissue, e.g. after a suspected leak of `iot/device_keys.json`). `GET /sensors`' new `authenticated` field reports this live per node — never hidden — so an operator can see at a glance which devices in a real fleet still need rotating.

**Disclosed limitation, same posture as everywhere else in this project.** This secures the HTTP hop (`POST /sensor-reading`) — it does not add MQTT-broker-level authentication (mosquitto here still accepts any client, same as before), and it does not add TLS on either hop, so a key in transit is only as safe as the network it crosses. A production deployment reachable over the open internet would need at minimum TLS on both the device→broker and bridge→backend hops in addition to this; tracked as a further hardening step in `docs/Future_Work.md`, not silently assumed solved by this follow-up.

## Wired into the risk engine (later follow-up, user-requested)

`GET /risk/*` (Phase 4) originally ran entirely on `SimulatedRainfallProvider`/`SimulatedSoilMoistureProvider`, never reading the sensor readings this phase ingests — that gap is now closed. `backend/app/services/risk_engine.py` checks each village for a fresh (`online`) sensor reading first, falling back to the configured provider (simulated, or real Open-Meteo) exactly as before whenever a village has no sensor or its sensor is offline/stale. See `docs/Architecture.md`'s "Sensor-failure / fallback hierarchy" section and `docs/Limitations.md` for what this does and doesn't prove — in particular, this build's demo sensors still declare `source: "simulated"`, so using one instead of a provider doesn't raise `confidence_pct` on its own here.
