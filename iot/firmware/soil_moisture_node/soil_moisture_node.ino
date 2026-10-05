/*
 * Girivarsha — ESP32 capacitive soil-moisture node (Phase 8).
 *
 * HONESTY NOTE: same as rainfall_node.ino — this is real, buildable
 * Arduino/ESP32 code, NOT flashed to or tested on physical hardware
 * (none exists in this build environment). See docs/IoT_Architecture.md.
 *
 * Sensor: a capacitive soil moisture sensor (e.g. the common
 * "Capacitive Soil Moisture Sensor v1.2") on an analog pin. Capacitive
 * sensors are used instead of resistive ones deliberately — resistive
 * probes corrode within weeks of continuous burial, which would silently
 * degrade readings in exactly the kind of unattended field deployment
 * this system needs.
 *
 * Calibration: ADC_DRY / ADC_WET are raw analogRead() values from YOUR
 * specific sensor unit in air (dry) and in a cup of water (wet) — these
 * vary between individual sensor units, so they must be measured, not
 * assumed from this file.
 *
 * Publishes to: girivarsha/sensors/<DEVICE_ID>/reading
 * Payload:      {"value": <0-100 pct>, "unit": "pct", "source": "real", "api_key": "<DEVICE_API_KEY>"}
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
const char* DEVICE_ID    = "esp32-kedarnath-soil-01";  // must match scripts/seed_iot_nodes.py
const char* DEVICE_API_KEY = "CHANGE_ME_SEE_iot_device_keys_json";  // this device's own key — see note above
const char* WIFI_SSID    = "CHANGE_ME";
const char* WIFI_PASS    = "CHANGE_ME";
const char* MQTT_HOST    = "CHANGE_ME";
const int   MQTT_PORT    = 1883;
const int   SENSOR_PIN  = 34;   // ADC1-capable pin (ADC2 conflicts with WiFi on ESP32)
const int   ADC_DRY     = 3000; // raw reading in open air — calibrate per unit
const int   ADC_WET     = 1200; // raw reading fully submerged in water — calibrate per unit
const unsigned long PUBLISH_INTERVAL_MS = 5UL * 60UL * 1000UL;  // soil moisture changes slowly — every 5 min is plenty

WiFiClient espClient;
PubSubClient mqtt(espClient);

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

float readSoilMoisturePct() {
  int raw = analogRead(SENSOR_PIN);
  // Lower raw ADC = wetter for most capacitive sensors (inverse of resistive probes).
  float pct = 100.0 * (float)(ADC_DRY - raw) / (float)(ADC_DRY - ADC_WET);
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  return pct;
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12); // ESP32 default ADC resolution (0-4095)
  connectWiFi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
}

void loop() {
  if (!mqtt.connected()) connectMQTT();
  mqtt.loop();

  static unsigned long lastPublish = 0;
  unsigned long now = millis();
  if (now - lastPublish >= PUBLISH_INTERVAL_MS || lastPublish == 0) {
    lastPublish = now;
    float pct = readSoilMoisturePct();

    StaticJsonDocument<256> doc;
    doc["value"] = pct;
    doc["unit"] = "pct";
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
