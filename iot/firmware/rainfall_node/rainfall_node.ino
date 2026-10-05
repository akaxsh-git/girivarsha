/*
 * Girivarsha — ESP32 tipping-bucket rain gauge node (Phase 8).
 *
 * HONESTY NOTE: this is real, buildable Arduino/ESP32 code written against
 * the documented libraries below — it has NOT been flashed to or tested on
 * physical hardware, because no ESP32 boards or tipping-bucket rain gauges
 * exist in the build environment this project was developed in. Treat it
 * as a well-informed first draft, same as docker-compose.yml, and verify
 * wiring/timing on real hardware before a live demo. See
 * docs/IoT_Architecture.md for exactly what in Phase 8 IS verified (the
 * MQTT broker, bridge, and backend ingestion — all real, all actually run).
 *
 * Sensor: a standard tipping-bucket rain gauge, wired so each 0.2794mm
 * (0.011in) tip closes a reed switch to GND — the near-universal design
 * used by cheap tipping-bucket gauges. Adjust MM_PER_TIP for your specific
 * gauge's datasheet.
 *
 * Publishes to: girivarsha/sensors/<DEVICE_ID>/reading
 * Payload:      {"value": <mm/hr>, "unit": "mm/hr", "source": "real", "api_key": "<DEVICE_API_KEY>"}
 *
 * Device authentication (user-requested follow-up): DEVICE_API_KEY below
 * is this node's own credential — the backend checks it against the hash
 * stored for external_device_id at provisioning time (see
 * app/api/routes/sensors.py, docs/IoT_Architecture.md). HONESTY NOTE on
 * this constant specifically: hardcoding a real secret into committed
 * source is NOT how a real fleet should provision keys (a real deployment
 * would flash it into NVS/a factory-config partition per physical board,
 * never into shared firmware source) — it's written as a plain constant
 * here only because that's the simplest way to keep this file buildable
 * and readable as a reference; get the real generated value for this
 * device from iot/device_keys.json (scripts/seed_iot_nodes.py /
 * scripts/rotate_sensor_api_keys.py), never invent one.
 *
 * Libraries (install via Arduino Library Manager):
 *   - WiFi.h            (bundled with the ESP32 board package)
 *   - PubSubClient       by Nick O'Leary
 *   - ArduinoJson        by Benoit Blanchon
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ---- Per-node configuration — change per physical install ----
const char* DEVICE_ID    = "esp32-kedarnath-rain-01";  // must match scripts/seed_iot_nodes.py
const char* DEVICE_API_KEY = "CHANGE_ME_SEE_iot_device_keys_json";  // this device's own key — see note above
const char* WIFI_SSID    = "CHANGE_ME";
const char* WIFI_PASS    = "CHANGE_ME";
const char* MQTT_HOST    = "CHANGE_ME";  // broker IP/hostname reachable from the field site
const int   MQTT_PORT    = 1883;
const int   TIP_PIN     = 27;           // GPIO wired to the rain gauge reed switch (other leg to GND)
const float MM_PER_TIP  = 0.2794;
const unsigned long PUBLISH_INTERVAL_MS = 60UL * 1000UL;  // publish an mm/hr rate once a minute

WiFiClient espClient;
PubSubClient mqtt(espClient);

volatile unsigned long tipCount = 0;
unsigned long windowStartMs = 0;

void IRAM_ATTR onTip() {
  tipCount++;
}

void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println(" connected.");
}

void connectMQTT() {
  while (!mqtt.connected()) {
    Serial.print("Connecting to MQTT broker...");
    if (mqtt.connect(DEVICE_ID)) {
      Serial.println(" connected.");
    } else {
      Serial.print(" failed, rc="); Serial.print(mqtt.state());
      Serial.println(" retrying in 5s");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(TIP_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(TIP_PIN), onTip, FALLING);

  connectWiFi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  windowStartMs = millis();
}

void loop() {
  if (!mqtt.connected()) connectMQTT();
  mqtt.loop();

  unsigned long now = millis();
  if (now - windowStartMs >= PUBLISH_INTERVAL_MS) {
    noInterrupts();
    unsigned long tips = tipCount;
    tipCount = 0;
    interrupts();

    float windowHours = (now - windowStartMs) / 3600000.0;
    float rateMmPerHr = (tips * MM_PER_TIP) / windowHours;
    windowStartMs = now;

    StaticJsonDocument<256> doc;
    doc["value"] = rateMmPerHr;
    doc["unit"] = "mm/hr";
    doc["source"] = "real";
    doc["api_key"] = DEVICE_API_KEY;

    char payload[256];
    size_t n = serializeJson(doc, payload);

    char topic[96];
    snprintf(topic, sizeof(topic), "girivarsha/sensors/%s/reading", DEVICE_ID);

    mqtt.publish(topic, payload, n);
    Serial.print("Published "); Serial.print(topic); Serial.print(" -> "); Serial.println(payload);
  }
}
