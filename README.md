# Girivarsha

**Hyper-local last-mile disaster intelligence for flash floods and landslides in hilly regions.**

> **Girivarsha is a prototype decision-support system. It is not an official government warning mechanism** and does not replace IMD, CWC, NDMA SACHET, ISRO/NRSC, or C-FLOOD. It exists to turn their regional intelligence into village-level, explainable, actionable warnings — see [`docs/Product_Positioning.md`](docs/Product_Positioning.md) for the full positioning.

## What this is, right now

This repository is being built **incrementally, phase by phase** (see [`docs/Future_Work.md`](docs/Future_Work.md) for the full 14-phase build order). Each phase is implemented, tested, and reported before the next begins — nothing here is claimed to work unless it has actually been run.

**Current status: Phase 14 — demo polish, complete and verified. The original 14-phase build plan is now fully done** — every phase, plus several user-requested follow-ups beyond it (region registry/second valley, real ML training data, glacial-lake advisory field, extended IoT sensor network, What-If Simulator, glacier melt-rate risk component + GLOF contribution indicator, all-villages evacuation route summary, a competitive-landscape research pass, a real SCS-CN rainfall-runoff layer, a `/risk/map` performance fix, a real duplicate-alert race-condition fix, a visual-polish pass giving both views a modern/clean look, real-time (SSE) alert push, an SMS + Hindi/English reach follow-up, a real OpenStreetMap road/trail network for evacuation routing, a real rainfall intensity-duration landslide threshold indicator, a real antecedent-precipitation-index (AMC classification) follow-up, real per-device IoT authentication, and server-side region filtering for sensors/alerts — see `docs/Future_Work.md`). See `docs/Future_Work.md` for the full phase-by-phase history and what's still open beyond the 14-phase plan itself.

| Component | Status |
|---|---|
| Backend (FastAPI) | ✅ Boots, `/health` + `/version` work, API contract for all planned endpoints exists (returns honest `501` until implemented) |
| Database (PostgreSQL 16 + PostGIS 3.4) | ✅ Full 14-table schema via Alembic migration, real GiST spatial indexes, seeded with real pilot-region data |
| Pilot regions | ✅ Two real, independently-sourced valleys seeded: Mandakini Valley, Rudraprayag district, Uttarakhand (6 real villages + 1 real historical event — the 2013 Kedarnath flash flood) and the Chamoli Disaster Valley, Chamoli district, Uttarakhand (4 real, `surveyed`-precision villages + 1 real historical event — the 7 Feb 2021 flash flood). Plus 3 honestly `planned` real valleys with no village data yet. See `docs/Data_Sources.md`. |
| Region registry (`/regions`, `?region_id=`) | ✅ Phase 11 — lets the system hold multiple genuinely-sourced valleys at once instead of one hard-coded pilot region; scopes `/villages`, `/catchments`, `/risk/map`. See `docs/Region_Onboarding.md` for how a new valley gets added. |
| `/villages`, `/villages/{id}`, `/catchments`, `/historical-events` | ✅ Real, DB-backed, tested |
| Frontend (React + Vite + TS) | ✅ Builds and type-checks cleanly, live-polls backend health, two real routes (see below) |
| Citizen / Authority dashboards | ✅ `/` is the plain-language citizen view (pick a village, see one risk card + lead-time note, no jargon); `/authority` is the full technical dashboard (map, catchment topology, risk, "explain this score", sensor network, alerts, build status). Both call the same real endpoints — the split is presentation-only. |
| Pilot region map | ✅ Real Leaflet map — real village markers (colour-coded by coordinate precision), real catchment topology panel. See `docs/GIS_Methodology.md`. |
| Catchment polygon boundaries | ✅ Real, verified end-to-end (2026-09-04) — real SRTM DEM downloaded, real D8 delineation run, real polygon loaded. `has_polygon_geometry: true`. See `docs/GIS_Methodology.md`. |
| Risk engine (baseline) | ✅ Transparent weighted scorer — `/risk/map`, `/risk/{id}`, `/alerts`, all real and DB-backed. Rainfall/soil-moisture come from a village's own live IoT sensor when one is online (checked first), otherwise from the configured provider — simulated by default, or **real** (opt-in, no API key) — see "Real weather data" below. Confidence reflects whichever is actually active — honestly ~40% with only simulated/derived inputs, genuinely rising with real ones. See `docs/Limitations.md`. |
| Explainability (`/model/explanation/{id}`) | ✅ Real, DB-backed — ranks and narrates the active baseline's own components in plain language (Phase 9). Not a fabricated SHAP explanation of the undeployed ML layer — see `docs/ML_Methodology.md`. |
| Lead-time estimation | ✅ Real prototype (Phase 10) — straight-line distance to the nearest upstream village ÷ a conservative assumed flow velocity, on `/risk/map` and `/risk/{id}`. Explicitly NOT validated hydraulic routing — see `backend/app/services/lead_time.py`. |
| Risk engine (ML) | ⚠️ Pipeline built + tested (synthetic data, `ml/train.py`) **and** run on a real, cited, combined 1,071-row dataset assembled from public sources (`ml/train_real.py` — 345 real positive GLOF + geocoded IFI events, real NASA POWER rainfall features; honest headline: LogisticRegression, mean false-negative rate 27.3% across 4-fold temporal CV, up from an earlier 144-row run's 58.3%) but **still NOT deployed** — real signal found, nowhere near deployment-safe. `GET /risk/*` uses only the baseline. See `docs/ML_Methodology.md`. |
| IoT sensor network | ✅ Real MQTT broker + real bridge + real ingestion API, actually run end-to-end (`/sensors`, `/sensor-readings`, live online/stale/offline status). 12 real sensor nodes provisioned across both pilot valleys (6 Mandakini + 6 Chamoli). Only the MQTT publisher is simulated, standing in for physical ESP32 hardware that doesn't exist in this build environment; real firmware sketches exist but are untested on boards. See `docs/IoT_Architecture.md`. |
| IoT device authentication | ✅ User-requested follow-up, closing a real security gap — `POST /sensor-reading` now requires a real per-device API key (`X-Device-Api-Key` header, SHA-256 hash stored server-side, constant-time compare) for every sensor that has one on file. Nullable-by-design staged rollout: a not-yet-rotated sensor keeps working un-authenticated exactly as before (`GET /sensors`'s new `authenticated` field says which, never hidden). `scripts/rotate_sensor_api_keys.py` issues keys idempotently. Secures the HTTP hop only — no MQTT-broker auth or TLS yet. See `docs/IoT_Architecture.md`/`docs/Limitations.md`. |
| Server-side region filtering for sensors/alerts | ✅ User-requested follow-up, closing a gap flagged since Phase 11 — `GET /sensors` and `GET /alerts` now both accept `?region_id=`, using the same real Sensor/Alert → Village → MicroCatchment → Region join `/villages`/`/catchments`/`/risk/map` already use. The Authority dashboard's own client-side scoping was removed, not kept alongside it — the region boundary a browser sees is now the same one any API caller gets. Omitting the param keeps every existing caller unchanged. See `docs/Limitations.md`. |
| Real-regional-data fallback for offline sensors | ✅ User-requested follow-up ("why do we need the simulator if we have real values") — `GET /sensors` now falls back to a REAL Open-Meteo regional weather estimate whenever a sensor has no live reading of its own, tagged `fallback_source: "derived"`, never conflated with a device's own `last_value` or its `status`. Only rainfall/soil_moisture sensors get one (Open-Meteo has no water-level/tilt product). Fetched concurrently and cached hourly per village — the same N-sequential-real-calls bug already fixed once for `GET /risk/map` was caught and fixed again here before shipping. See `docs/Limitations.md`. |
| Wind map overlay | ✅ User-requested ("like the Mac Weather app") — an opt-in "Show wind" toggle on the Authority map animates particles from REAL Open-Meteo current 10 m wind (`GET /api/v1/wind`, one batched upstream call per area per hour, `source: "real"`, 503 rather than invented data when upstream is down). Coarse regional flow only — valley-scale terrain winds are not resolved and it is not an input to the risk model. See `docs/Limitations.md`. |
| Evacuation routing (`/evacuation/route/{id}`, `/evacuation/routes`, `/evacuation/priority`) | ✅ Phase 12, plus a user-requested real-road-network follow-up — real `networkx` shortest-path over the real per-catchment village topology; each hop's DISTANCE now comes from a real OpenStreetMap road/trail path (71K+ real nodes/edges fetched via the Overpass API) wherever both endpoints snap close enough to it, honestly falling back to the original straight-line proxy where they don't (every hop's own `distance_source` field says which). Transparent priority ranking, not an evacuation order. `/evacuation/routes` returns every village's own route in one call. See `docs/Limitations.md` for the concrete disclosed gap this surfaced. |
| Historical event replay (`/replay/events`, `/replay/{id}`) | ✅ Phase 12 — real, cited, ordered sub-event timelines for both seeded disasters (Kedarnath 2013, Reni/Tapovan 2021), each entry honestly labelled by how precisely it's documented. No fabricated minute-by-minute reconstruction. See `docs/Architecture.md`. |
| Glacial-lake-proximity advisory field | ✅ Phase 12 follow-up — real distance to the nearest of 4,881 real, satellite-mapped Himalayan glacial lakes (Zhang et al. 2023), on `/risk/map` and `/risk/{id}` as `glacial_lake_distance_km`/`glacial_lake_note`. Deliberately advisory-only, never folded into `risk_score`/`risk_level` — see `docs/Limitations.md`. |
| Glacier melt-rate risk component + GLOF contribution indicator | ✅ User-requested follow-up — a genuine 5th weighted risk-engine component (`glacial_melt_rate`) from a real, RGI-identified nearby glacier's recent (2021-2025 mean) mass-balance rate (WGMS/Dussaillant et al. 2025, updating Hugonnet et al. 2021's methodology — 1,967 real regional glaciers), plus an advisory `glof_contribution_pct`/`glof_contribution_tier` blending it with glacial-lake proximity. Explicitly **not** a calibrated flash-flood probability — see `docs/Limitations.md`. |
| SCS-CN rainfall-runoff layer | ✅ User-requested follow-up (top recommendation from a competitive-landscape research pass) — a real, standard NRCS TR-55/SCS-CN direct-runoff-depth estimate (`scs_cn_runoff_depth_mm`, `scs_cn_curve_number`, and related fields) from each village's real soil texture (ISRIC SoilGrids v2.0) and land cover (ESA WorldCover 10m), on `/risk/map`, `/risk/{id}`, and `/simulate`. A second, independent figure shown alongside the weighted score, deliberately never folded into `risk_score`/`risk_level`. See `docs/Data_Sources.md`/`docs/Limitations.md`. |
| Rainfall intensity-duration threshold indicator | ✅ User-requested follow-up (second recommendation from the same competitive-landscape research pass) — a real, third independent indicator (`rainfall_threshold_hours_to_threshold`, `rainfall_threshold_status`, `rainfall_threshold_applicability`) from a real, peer-reviewed, region-specific published curve (Kanungo & Sharma 2014, covering this project's own Chamoli pilot valley directly), on `/risk/map`, `/risk/{id}`, and `/simulate`. Honestly disclosed as a direct fit for Chamoli and a regional proxy for Mandakini — never folded into `risk_score`/`risk_level`. See `docs/Data_Sources.md`/`docs/Limitations.md`. |
| Antecedent-precipitation-index (AMC classification) | ✅ User-requested follow-up (third recommendation from the same competitive-landscape research pass) — real NASA POWER 5/10/20-day rainfall sums (`antecedent_rainfall_5day_mm` and related fields) replace the soil-moisture-as-AMC-proxy in the SCS-CN estimate above, but only when genuinely real (`GIRIVARSHA_ACTIVE_ANTECEDENT_PROVIDER=real`) — the default `simulated` setting leaves the original proxy behavior untouched. The source's own ~7-8 day reporting lag is honestly disclosed. See `docs/Data_Sources.md`/`docs/Limitations.md`. |
| Failure/fallback testing | ✅ Phase 13 — nine real failure modes (sensor offline/stale, unregistered device, invalid data, provider outage, missing dataset, empty region, unreachable backend, malformed MQTT payload) tested explicitly for honest degradation; found and fixed one real crash bug along the way. See `docs/Failure_Mode_Testing.md`. |
| What-If Simulator (`POST /simulate`) | ✅ User-requested follow-up, closing a gap Phase 14 flagged — a presenter overrides one village's rainfall and/or soil-moisture input and the SAME transparent baseline formula recomputes live (no separate "simulation model"). Returns both the real current assessment and the hypothetical one; nothing is persisted or fed into `/alerts`. Authority dashboard "What-if simulator" panel. See `docs/Limitations.md`. |
| Real-time alert push (`GET /alerts/stream`) | ✅ User-requested follow-up — a Server-Sent-Events channel that pushes a real alert open/escalation/resolution to the Authority dashboard the instant `/risk/map` or `/risk/{id}` produces one, instead of only finding out on the dashboard's own next poll. Single-process, in-memory fan-out (see `docs/Limitations.md` for the real limitation that implies); a green "LIVE" badge next to Active Alerts reflects the actual connection state, not a fixed claim. |
| SMS + Hindi/English reach follow-up | ✅ User-requested — a real (optional, opt-in) SMS dispatch on a village's ORANGE/RED alert (`POST /notifications/subscribe`, `docs/Data_Sources.md`-style honest LOG_ONLY-vs-Twilio provider swap, never claims delivery it can't verify — see "Real-time push + SMS alerts" below), plus an English/Hindi toggle on the Citizen view (default English, so nothing changes unless a visitor switches it). |
| Docker Compose | ⚠️ Written, matches the target topology, but **not run** — no Docker daemon was available in the sandbox this was built in. Please run `docker compose up --build` locally and report issues. |

**Tests: 207/207 backend (pytest) + 87/87 frontend (vitest) + 2/2 GIS (pytest, synthetic DEM) + 25/25 ML pipeline (pytest — 5 synthetic-pipeline + 11 real-data-assembly + 9 geocoding/merge/CV) passing — 321 total.** The DB-backed backend tests auto-skip if no database is configured, so `pytest` still runs cleanly without Postgres set up.

## Repository structure

```
/frontend    React + Vite + TypeScript dashboard(s)
/backend     FastAPI application (API, risk engine, providers)
/ml          Model training/eval pipeline (Phase 5 — real code, synthetic-data smoke test; see docs/ML_Methodology.md)
/gis         DEM/terrain processing, catchment delineation scripts (Phase 2-3)
/iot         ESP32 firmware + real MQTT bridge/simulator (Phase 8, see iot/README.md)
/data        Pilot-region data: raw, derived, and clearly-labelled simulated datasets
/scripts     One-off/dev utility scripts
/notebooks   Exploratory analysis
/docs        Architecture, data sources, methodology, API docs, pitch, limitations
/tests       Backend, risk-engine, GIS and end-to-end tests
/docker      Extra Docker assets (compose files live at the repo root)
```

## Running it locally (no Docker)

**Database** (needed since Phase 2 — `/villages`, `/catchments`, `/historical-events` need it; everything else still works without it)

Install PostgreSQL 16 + PostGIS locally (macOS: `brew install postgresql@16 postgis`, then `brew services start postgresql@16`), then:
```bash
createuser girivarsha --pwprompt --superuser   # set password to "girivarsha", or pick your own
createdb girivarsha --owner=girivarsha
psql girivarsha -c "CREATE EXTENSION postgis; CREATE EXTENSION pgrouting;"
```

**Backend**
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set GIRIVARSHA_DATABASE_URL to match what you created above
alembic upgrade head                      # creates all tables
python ../scripts/seed_pilot_region.py      # loads the real Mandakini pilot-region data
python ../scripts/seed_chamoli_valley.py    # loads the real second pilot valley (Chamoli, Phase 11)
python ../scripts/seed_regions.py           # links both into the region registry (GET /regions)
python ../scripts/seed_event_timelines.py   # loads real historical sub-event timelines (GET /replay/*, Phase 12)
uvicorn app.main:app --reload
# -> http://localhost:8000  (interactive docs at /docs)
```
(Skipping the database steps is fine — the app still boots and `/health`, `/version`, `/demo/rainfall-sample` all work; `/villages`, `/catchments`, `/historical-events` will 500 without a configured DB instead of the honest 501 they'd give if simply unbuilt — that's expected, not a bug, since their code exists but needs the DB connection to run.)

**Frontend** (in a second terminal)
```bash
cd frontend
npm install
cp .env.example .env   # optional — defaults to http://localhost:8000
npm run dev
# -> http://localhost:5173
```

Open the frontend — the header should show **"Backend online — Phase 14 - demo polish (original 14-phase plan complete)"** within a couple of seconds, with two tabs: **Citizen view** (`/`, plain-language, pick-your-village — villages now grouped by region) and **Authority dashboard** (`/authority`, the full technical view, including a region selector, the "Explain this score" panel, sensor network panel, evacuation routing, evacuation priority, and historical event replay below). If it says unreachable, the backend isn't running or `VITE_API_BASE_URL` doesn't match where it's listening.

**IoT sensor network** (optional — the app works without it, sensors just show honestly "offline"; see `iot/README.md` for the full walkthrough):
```bash
# provisions all 12 pilot sensor nodes, 6 per valley (run scripts/seed_pilot_region.py
# and scripts/seed_chamoli_valley.py first)
cd backend && source .venv/bin/activate && python ../scripts/seed_iot_nodes.py

# separately: install mosquitto (macOS: brew install mosquitto && brew services start mosquitto),
# then in two more terminal tabs:
pip install -r ../iot/requirements.txt
python ../iot/mqtt_bridge.py                      # tab A — real bridge, leave running
python ../iot/simulate_sensor_publisher.py         # tab B — stands in for physical hardware, leave running
```
The Authority dashboard's "Sensor network" panel should show all 12 nodes (6 Mandakini + 6 Chamoli) flip to `online` within a few seconds — region-scoped views (e.g. Chamoli) show only their own 6.

**Real weather data (optional — no API key needed)**

By default, rainfall and soil-moisture are simulated (clearly labelled `source: "simulated"`), which is why the risk engine's confidence is honestly capped around 40%. To switch either to **real, live data** from [Open-Meteo](https://open-meteo.com/en/docs) (free, no signup, no key), edit `backend/.env`:
```bash
GIRIVARSHA_ACTIVE_RAINFALL_PROVIDER=real
GIRIVARSHA_ACTIVE_SOIL_PROVIDER=real
```
Restart the backend, then hit any risk endpoint (e.g. `curl http://localhost:8000/api/v1/risk/1`) — components fed by the real provider now show `"source": "real"` and confidence rises accordingly (roughly 40% → 85%+ when both are real, since confidence is a direct, transparent function of each input's data-source tag — see `backend/app/services/risk_engine.py`'s `TIER_CONFIDENCE`). If Open-Meteo is unreachable for any reason, the provider fails honestly (`ProviderUnavailableError`) and that component falls back to the same simulated-tagged default the app already uses for any provider outage — it never crashes and never fakes a "real" reading.

**This exact live HTTP call could not be verified from the sandbox this was built in** (outbound network to `api.open-meteo.com` is blocked there, confirmed via `curl -v` — same restriction already documented for the OpenTopography DEM download in `docs/GIS_Methodology.md`). Unlike OpenTopography this needs no API key, so it's a one-line check on your own machine:
```bash
curl "https://api.open-meteo.com/v1/forecast?latitude=30.7346&longitude=79.0669&current=precipitation,rain&timezone=UTC"
```
`tests/backend/test_providers.py` covers the parsing/error-handling logic against a mocked response shape taken from Open-Meteo's published docs, and the honest-fallback path (env var set to `real`, network unavailable → `ProviderUnavailableError`, app doesn't crash) was verified live in this build environment. Please try the toggle on your machine and let me know what you see.

**Real antecedent-precipitation-index / AMC classification (optional, no API key needed)**

By default, the SCS-CN estimate's Antecedent Moisture Condition (AMC I/II/III) is approximated from a village's current soil-moisture reading. To switch to a real 5/10/20-day rainfall history from [NASA POWER](https://power.larc.nasa.gov/) (free, no signup, no key), edit `backend/.env`:
```bash
GIRIVARSHA_ACTIVE_ANTECEDENT_PROVIDER=real
```
Restart the backend, then hit `GET /api/v1/risk/1` — `antecedent_rainfall_source` reads `"real"` and `scs_cn_note` states it's using real antecedent rainfall instead of the soil-moisture proxy. **Unlike the Open-Meteo toggle above, this one WAS verified live in this build environment** — NASA POWER's API is reachable here, and a real call returns genuine MERRA-2 rainfall history (with one disclosed limitation: its most recent ~7-8 days consistently return a "not yet processed" fill value, so the app honestly reports the most recent real day actually available and how many days old it is, rather than guessing at today's figure — see `docs/Data_Sources.md`). If NASA POWER is ever unreachable, the provider falls back honestly to the same clearly-labelled simulated default.

**Real-time push + SMS alerts (optional)**

`GET /api/v1/alerts/stream` is a real Server-Sent-Events channel — open it (or just load the Authority dashboard; it subscribes automatically) and every real alert open/escalation/resolution anywhere in the app (from `/risk/map` or `/risk/{id}`) arrives the instant it happens, not on the dashboard's next poll:
```bash
curl -N http://localhost:8000/api/v1/alerts/stream
```
This is single-process, in-memory fan-out (`backend/app/services/alert_broadcaster.py`) — the honest match for what this app actually deploys as (see `docker-compose.yml`), not infrastructure it doesn't run; it would need a real broker (Redis pub/sub, etc.) to work across multiple worker processes, which is a disclosed limitation, not a hidden one.

SMS is real and opt-in end-to-end (`POST /api/v1/notifications/subscribe`), but **actual delivery** depends on whether a real SMS gateway is configured:
```bash
curl -X POST http://localhost:8000/api/v1/notifications/subscribe \
  -H "Content-Type: application/json" \
  -d '{"village_id": 1, "phone_number": "+919812345678"}'
```
By default (`GIRIVARSHA_ACTIVE_SMS_PROVIDER=log_only`), a subscribed village's real ORANGE/RED alert only logs the message server-side (`DeliveryStatus.LOGGED_ONLY`) — it is never silently claimed as delivered. Set `GIRIVARSHA_ACTIVE_SMS_PROVIDER=twilio` plus `GIRIVARSHA_TWILIO_ACCOUNT_SID`/`AUTH_TOKEN`/`FROM_NUMBER` in `backend/.env` (a real Twilio trial or paid account) to actually send. **This exact Twilio HTTP call has not been exercised in this build environment** — no Twilio credentials exist here, same class of caveat already documented for the Open-Meteo call above; `tests/backend/test_notifications.py` covers the parsing/error-handling logic against a mocked response shape.

The Citizen view's English/Hindi toggle (default English) and its SMS opt-in form both call these same real endpoints — nothing there is a mockup.

**Tests**
```bash
cd backend && source .venv/bin/activate
python -m pytest ../tests/backend -v
```
207/207 passing (the DB-backed tests auto-skip if no database is configured, so this still passes cleanly without Postgres set up; includes `tests/backend/conftest.py` — a global autouse fixture, added alongside the real-regional-data fallback follow-up, that fails fast on any unmocked real `httpx.get` to Open-Meteo so this sandbox's disclosed network restriction can't silently turn any test's `GET /sensors` call into an 8-second real-network timeout; includes `tests/backend/test_regions.py`, which needs `scripts/seed_chamoli_valley.py` + `scripts/seed_regions.py` (now also covering the server-side region filtering follow-up — real `?region_id=` scoping on `/sensors` and `/alerts`, plus each endpoint's unfiltered "everything unchanged" behavior), `tests/backend/test_evacuation.py`/`test_replay.py`, which need `scripts/seed_event_timelines.py`, `tests/backend/test_failure_modes.py` (Phase 13 + a 10th mode for the glacier-melt follow-up + an 11th for the SCS-CN follow-up + a 12th for the road-network follow-up + a 13th for the antecedent-precipitation-index follow-up + a 14th for the device-authentication follow-up), `tests/backend/test_sensors.py` (also now covering the device-authentication follow-up — missing/wrong/correct API key enforcement and the `authenticated` field, via a dedicated new test device that leaves every pre-existing sensor test unchanged; and the real-regional-data fallback follow-up — a mocked real Open-Meteo fallback for offline sensors, an online sensor never triggering the fetch, honest degradation on provider failure, and the two sensor-type/no-village cases that must never get one), `tests/backend/test_risk_sensor_wiring.py` (sensor-into-risk-engine follow-up), `tests/backend/test_simulate.py` (What-If Simulator follow-up, now also covering the SCS-CN, rainfall-threshold, and antecedent-rainfall baseline-vs-simulated/independence comparisons), `tests/backend/test_glacial_melt_hazard.py` (glacier melt-rate follow-up), `tests/backend/test_scs_cn_runoff.py` (SCS-CN follow-up, plus 2 new tests proving real antecedent rainfall drives AMC classification while simulated antecedent rainfall does NOT override the soil-moisture proxy — both exercise their module against a small fixture CSV, doesn't need the real committed dataset, same pattern as `test_glacial_lake_proximity.py`), `tests/backend/test_rainfall_threshold.py` (rainfall intensity-duration threshold follow-up — pure offline unit tests against the real, cited formula, no database or network needed), `tests/backend/test_antecedent_rainfall.py` (antecedent-precipitation-index follow-up — 12 pure offline unit tests mocking `httpx.get` against real NASA POWER-shaped payloads, no live network needed), `tests/backend/test_risk_map_performance.py` (GET /risk/map performance follow-up — dedup/cache correctness and a real cross-catchment "upstream" bug fix, see `docs/Future_Work.md`), `tests/backend/test_alerts_race_condition.py` (a real concurrent-request duplicate-alert bug found live on the user's own machine, fixed with a DB-level constraint — see `docs/Future_Work.md`), `tests/backend/test_alert_broadcaster.py`/`test_alert_transitions.py`/`test_risk_realtime_wiring.py` (real-time SSE push follow-up — the in-memory fan-out, the new AlertTransition reporting in `sync_alert_for_village`, and the risk routes' actual wiring to both the broadcaster and the SMS dispatcher), `tests/backend/test_notifications.py`/`test_notification_subscriptions.py` (SMS-reach follow-up — the LogNotificationProvider/TwilioSmsProvider adapters and the subscribe/unsubscribe endpoints), and `tests/backend/test_road_network.py` (real road/trail network follow-up — the loader/snapper/router against the committed OSM-derived dataset, offline, no live network calls) — all run alongside it).

Frontend component tests:
```bash
cd frontend
npm test
```
87/87 passing (map + wind overlay, catchment panel, risk panel, sensor panel, explanation panel, evacuation panel, priority panel, replay panel, what-if panel, SMS opt-in, and citizen-view components — including a regression test that two regions' villages never get connected by one drawn line across them, glacial-lake-proximity and GLOF-contribution-indicator display coverage in `RiskPanel`/`CitizenView`, explanation-panel coverage of the live-sensor detail line, what-if-panel coverage of the baseline-vs-hypothetical comparison, evacuation-panel coverage of the all-villages route summary table and the real-road-network-vs-straight-line-proxy "route data" badge, SCS-CN rainfall-runoff and rainfall intensity-duration threshold display coverage in `RiskPanel`/`CitizenView`/`WhatIfPanel`, antecedent-rainfall display coverage in `RiskPanel`/`WhatIfPanel` (deliberately omitted from `CitizenView` — see `docs/Limitations.md`), `RiskPanel`'s real-time "LIVE" status badge, `SmsOptIn`'s subscribe/already-subscribed/error states, `CitizenView`'s English/Hindi toggle, `SensorPanel`'s honest "keyed"/"no key" per-device authentication badge from the device-authentication follow-up, and `SensorPanel`'s italic "regional est." fallback value plus the plain-dash case when even that isn't available, from the real-regional-data fallback follow-up).

GIS delineation algorithm test (needs `pip install -r gis/requirements.txt` first — heavy geospatial libraries, kept separate from the main backend requirements since the running API never imports them):
```bash
cd backend && source .venv/bin/activate
pip install -r ../gis/requirements.txt
python -m pytest ../tests/gis -v
```
2/2 passing — verifies the real delineation algorithm against a synthetic DEM (see `docs/GIS_Methodology.md` for why a synthetic DEM, not a real one, was used here).

ML pipeline test (needs `pip install -r ml/requirements.txt` first — same "kept separate" reasoning as GIS above, plus: this trains on synthetic data on purpose, see `docs/ML_Methodology.md`):
```bash
cd backend && source .venv/bin/activate
pip install -r ../ml/requirements.txt
python -m pytest ../tests/ml -v
```
16/16 passing (5 synthetic-pipeline + 11 real-data-assembly) — proves both the synthetic-pipeline mechanics AND the real-data assembly/parsing logic are correct. Run `python ml/train.py` for the synthetic metrics table, or `python ml/train_real.py` for the real one (needs `ml/data/real_flood_training_features.csv`, already committed — regenerate it with `python ml/assemble_real_events.py && python ml/backfill_real_weather.py`, the latter makes live NASA POWER API calls). See `docs/ML_Methodology.md` for what the real numbers do and don't show.

## Running it with Docker (untested — please verify)

```bash
cp .env.example .env
docker compose up --build
# once containers are up, run migrations + seed inside the backend container:
docker compose exec backend alembic upgrade head
docker compose exec backend python ../scripts/seed_pilot_region.py
docker compose exec backend python ../scripts/seed_chamoli_valley.py
docker compose exec backend python ../scripts/seed_regions.py
docker compose exec backend python ../scripts/seed_event_timelines.py
```
This should bring up Postgres/PostGIS, the backend on `:8000`, and the frontend dev server on `:5173`. **This exact command has not been executed** in the environment this was built in (no Docker daemon available) — treat it as a well-informed first draft, not a verified result, and let me know what breaks.

## Try the API directly

```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/version
curl http://localhost:8000/api/v1/demo/rainfall-sample     # working simulated-data provider
curl http://localhost:8000/api/v1/villages                 # real, DB-backed (Phase 2)
curl http://localhost:8000/api/v1/catchments                # real, DB-backed (Phase 2)
curl http://localhost:8000/api/v1/historical-events          # real, DB-backed (Phase 2)
curl http://localhost:8000/api/v1/risk/map                  # real — transparent baseline scores + lead time + glacial-lake distance + GLOF indicator + SCS-CN runoff + rainfall I-D threshold + antecedent rainfall (Phase 4, 10, 12/glacier-melt/SCS-CN/rainfall-threshold/antecedent-rainfall follow-ups)
curl http://localhost:8000/api/v1/risk/1                    # real — full 5-component breakdown (incl. glacial_melt_rate) + lead time + glacial-lake/GLOF advisory notes + SCS-CN runoff + rainfall I-D threshold + antecedent rainfall (5/10/20-day) estimate for village id 1
curl http://localhost:8000/api/v1/model/explanation/1        # real — plain-language "why" narrative (Phase 9)
curl http://localhost:8000/api/v1/alerts                    # real — currently open YELLOW/ORANGE/RED alerts
curl http://localhost:8000/api/v1/sensors                    # real — sensor registry with live status (Phase 8)
curl http://localhost:8000/api/v1/sensor-readings             # real — recent ingested readings (Phase 8)
curl http://localhost:8000/api/v1/regions                    # real — the region registry: active + planned real valleys (Phase 11)
curl "http://localhost:8000/api/v1/villages?region_id=2"      # real — scoped to one region (2 = Chamoli Disaster Valley)
curl http://localhost:8000/api/v1/evacuation/route/7           # real — networkx shortest-path route from village id 7 (Phase 12, NOT real road routing)
curl http://localhost:8000/api/v1/evacuation/routes             # real — every village's own route in one call (user-requested follow-up)
curl http://localhost:8000/api/v1/evacuation/priority           # real — transparent evacuation priority ranking (Phase 12)
curl http://localhost:8000/api/v1/replay/events                # real — historical events with a seeded, cited sub-event timeline (Phase 12)
curl http://localhost:8000/api/v1/replay/1                     # real — full ordered, cited timeline for event id 1 (Phase 12)
```

## Documentation

- [`docs/Architecture.md`](docs/Architecture.md) — full pipeline design (target + current status)
- [`docs/Data_Sources.md`](docs/Data_Sources.md) — real vs. simulated vs. derived data inventory
- [`docs/API_Documentation.md`](docs/API_Documentation.md) — every endpoint, current status, example requests
- [`docs/ML_Methodology.md`](docs/ML_Methodology.md) · [`docs/GIS_Methodology.md`](docs/GIS_Methodology.md) · [`docs/IoT_Architecture.md`](docs/IoT_Architecture.md) — planned methodology per subsystem
- [`docs/Demo_Guide.md`](docs/Demo_Guide.md) — the 5-minute demo script
- [`docs/Limitations.md`](docs/Limitations.md) — honest current limitations
- [`docs/Region_Onboarding.md`](docs/Region_Onboarding.md) — how a real valley moves from `planned` to `active` in the region registry
- [`docs/Future_Work.md`](docs/Future_Work.md) — the phase-by-phase roadmap
- [`docs/Product_Positioning.md`](docs/Product_Positioning.md) — positioning, differentiation, stakeholder Q&A
- [`docs/Deployment.md`](docs/Deployment.md) — free-tier public hosting (Neon + Render)

## Design principles this codebase follows

1. **Never fabricate data or results.** Every reading carries a `source` tag: `real`, `simulated`, or `derived`. Unbuilt endpoints return `501`, never plausible-looking fake JSON.
2. **Adapter pattern for every data source** (`app/providers/`), so a real API can replace a simulated one later without touching anything downstream.
3. **Configurable, not hard-coded**, risk thresholds and provider selection (`app/core/config.py`, env-driven).
4. **Test what you claim.** Nothing in this README is asserted without having actually been run in this environment.
