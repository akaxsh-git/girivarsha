# Architecture

## Product framing

Girivarsha is a **hyper-local last-mile disaster intelligence layer**, not a replacement for regional forecasting agencies. It consumes regional/public data (rainfall, satellite soil moisture, historical hazard records) and fuses it with local terrain analysis and IoT observations to answer six questions per village/ward:

1. Is this location becoming dangerous? (**hazard**)
2. Why? (**explanation**)
3. How confident are we? (**confidence / data quality**)
4. How much lead time may be available? (**lead time**)
5. Which villages/zones are affected? (**exposure**)
6. What should authorities consider doing? (**action**)

The system deliberately separates **hazard** (probability/severity of a dangerous event), **exposure** (people/infrastructure potentially affected), **vulnerability** (susceptibility to damage), and **action** (recommended response) rather than collapsing everything into one number.

## Pipeline

```
EXTERNAL / REGIONAL DATA  (rainfall APIs, satellite soil moisture, historical hazard inventories)
        │
        ▼
DATA INGESTION            (app/providers/ — adapter per source, real or simulated)
        │
        ▼
CLEANING + NORMALIZATION  (missing-value handling, unit normalization, outlier flags)
        │
        ▼
GEOSPATIAL / MICRO-CATCHMENT ENGINE   (DEM → slope/aspect/flow accumulation → catchment delineation, gis/)
        │
        ▼
MULTI-SOURCE FEATURE ENGINEERING      (rainfall windows, soil trends, terrain indices, historical susceptibility)
        │
        ▼
HYBRID RISK ENGINE
        ├── Layer A: transparent weighted baseline (always available)
        └── Layer B: tree-based ML model — XGBoost / Random Forest (Phase 5, once labelled events exist)
        │
        ▼
RISK SCORE + CONFIDENCE + LEAD TIME   (0-100 score, band, % confidence, sensor-health-aware)
        │
        ▼
EXPLAINABILITY ENGINE                 (ranked real component contributions → plain-language drivers, Phase 9 — real today for Layer A; becomes a genuine SHAP explanation automatically if/when Layer B is ever deployed)
        │
        ▼
VILLAGE / ZONE IMPACT ANALYSIS        (which downstream settlements are exposed, via catchment topology)
        │
        ▼
EVACUATION RECOMMENDATION             (nearest shelter, route, priority — decision support only)
        │
        ▼
AUTHORITY DASHBOARD  +  CITIZEN ALERT
```

Every stage is a separate module with a defined interface so it can be replaced independently (e.g. swap the baseline scorer for the ML model without touching ingestion or the dashboard).

## Implementation status by stage

| Stage | Status | Where |
|---|---|---|
| Data ingestion (adapter pattern) | ✅ Interface + simulated rainfall/soil-moisture providers, **and real ones** (Open-Meteo, opt-in, no API key — Phase 9-10) | `backend/app/providers/` |
| Database (schema + migrations) | ✅ Full 14-table Postgres+PostGIS schema, Alembic-migrated | `backend/app/models/`, `backend/migrations/` |
| Pilot region data | ✅ Real, sourced villages + 1 historical event seeded | `scripts/seed_pilot_region.py`, `docs/Data_Sources.md` |
| Cleaning/normalization | ⏳ Not needed by the baseline; would apply once real ML training data exists | — |
| Micro-catchment engine (topology) | ✅ Real upstream/downstream river order, consumed by the baseline risk engine | `backend/app/models/orm.py` (`MicroCatchment`) |
| Micro-catchment engine (polygons) | ⏳ Delineation algorithm written + tested on synthetic DEM; real pilot-region polygon blocked on network access for DEM download (see `docs/GIS_Methodology.md`) | `gis/` |
| Map UI (villages + catchment topology) | ✅ Phase 3 — Leaflet map, real village markers, catchment panel | `frontend/src/components/PilotMap.tsx`, `CatchmentPanel.tsx` |
| Feature engineering | ✅ Baseline's 4 components are real; ML feature ladder (Phase 5) built + tested on synthetic data | `backend/app/services/risk_engine.py`, `ml/generate_synthetic_training_data.py` |
| Risk engine (baseline) | ✅ Phase 4 — transparent weighted scorer, `GET /risk/map`, `GET /risk/{id}`, `GET /alerts` | `backend/app/services/risk_engine.py`, `alerts_engine.py` |
| Risk engine (ML) | ⏳ Pipeline built + tested on synthetic data (Phase 5); NOT deployed — real training blocked on insufficient labelled events (1). `GET /risk/*` uses only the baseline. | `ml/` |
| Explainability | ✅ Phase 9 — real, model-agnostic `GET /model/explanation/{id}`, ranking + narrating the active baseline's own real components; explicitly not a fabricated SHAP explanation of the undeployed ML layer | `backend/app/services/explanation.py` |
| Lead time | ✅ Phase 10 — real prototype estimator (straight-line distance ÷ assumed flow velocity) on `GET /risk/map`/`GET /risk/{id}`; explicitly not validated hydraulic routing | `backend/app/services/lead_time.py` |
| Region registry (multi-valley scaling) | ✅ Phase 11 — `Region` model, `GET /regions`, `?region_id=` scoping on `/villages`/`/catchments`/`/risk/map`; 2 `active` real valleys, 3 honestly `planned` | `backend/app/models/orm.py` (`Region`), `backend/app/api/routes/regions.py`, `docs/Region_Onboarding.md` |
| Impact analysis / evacuation | ✅ Phase 12 — `networkx` shortest-path routing over the real per-catchment elevation-order topology, `GET /evacuation/route/{id}`, transparent `GET /evacuation/priority` ranking; explicitly not real road/trail routing | `backend/app/services/evacuation.py`, `backend/app/api/routes/evacuation.py` |
| Historical event replay | ✅ Phase 12 — real, cited, ordered sub-event timelines for the 2 seeded historical disasters, step-through UI; each entry honestly tagged by how precisely it's documented (`exact_time`/`approximate`/`date_only`), no fabricated minute-by-minute reconstruction | `backend/app/models/orm.py` (`EventTimelineEntry`), `backend/app/api/routes/replay.py`, `scripts/seed_event_timelines.py` |
| Dashboards (citizen + authority) | ✅ Phase 6-7 — two real routes, `/` and `/authority`, both on the same real endpoints; Phase 9-10 added the "Explain this score" panel and lead-time surfacing to both | `frontend/src/views/` |
| IoT ingestion | ✅ Phase 8 — real broker/bridge/ingestion pipeline, simulated hardware publisher (see `docs/IoT_Architecture.md`); still a separate data path from the risk engine's providers, not yet merged (see `docs/Future_Work.md`) | `iot/` |
| Glacial-lake proximity (GLOF advisory context) | ✅ Phase 12 follow-up — real great-circle distance to the nearest of 4,881 real, satellite-mapped glacial lakes (Zhang et al. 2023), surfaced as `glacial_lake_distance_km`/`glacial_lake_note` on `GET /risk/map`/`GET /risk/{id}`; deliberately advisory-only, never folded into `risk_score`/`risk_level` | `backend/app/services/glacial_lake_proximity.py`, `scripts/prepare_glacial_lake_data.py` |

## Micro-catchment concept (problem-statement item 7)

Risk is **not** assigned independently per village. The pilot region is modelled as:

```
District → Watershed → Micro-catchment → Stream network → Downstream villages/zones
```

A village downstream of a rapidly-changing upstream catchment gets different risk than one outside that flow path, even under identical local rainfall. The upstream/downstream topology this needs is real as of Phase 2 and does not require polygon geometry, so the risk engine (Phase 4) can consume it today. Polygon boundaries (Phase 3, `gis/`) sharpen exactly where a catchment's edge falls on a map — they refine the picture but don't gate the topology-based logic. See `docs/GIS_Methodology.md` for exactly what's real vs. pending in the GIS pipeline right now.

## Sensor-failure / fallback hierarchy (problem-statement item 13)

```
LOCAL SENSOR
   │ unavailable
   ▼
SATELLITE / REGIONAL ESTIMATE
   │ unavailable
   ▼
ANTECEDENT RAINFALL / HISTORICAL PROXY
   │
   ▼
REDUCED CONFIDENCE (never a silent default)
```

The `DataProvider` interface (`backend/app/providers/base.py`) is designed around this: every reading carries a `source` tag (`real` / `simulated` / `derived`) and providers raise `ProviderUnavailableError` instead of returning a default value. As of Phase 4, the risk engine (`backend/app/services/risk_engine.py`) actually does this: `confidence_pct` is computed from each component's real/derived/simulated tier (see `TIER_CONFIDENCE`). By default, with only the SIMULATED tier active for rainfall/soil moisture, every prediction's confidence is honestly capped near 40% — but as of Phase 9-10, setting `GIRIVARSHA_ACTIVE_RAINFALL_PROVIDER=real`/`GIRIVARSHA_ACTIVE_SOIL_PROVIDER=real` genuinely switches those components to Open-Meteo's live forecast API (free, no key) and confidence rises accordingly (~40% → ~85%+), with no change to this formula — exactly the mechanism this paragraph originally promised. See README.md's "Real weather data" section.

**As of the Phase 8+ sensor-wiring follow-up (user-requested), LOCAL SENSOR is genuinely the first thing tried, not just the top of a diagram.** `risk_engine.py`'s `_fresh_sensor_reading()` checks the Phase 8 IoT sensor network (`app/api/routes/sensors.py`'s own live freshness computation, factored out into `app/services/sensor_freshness.py` so both endpoints use identical thresholds) before falling through to the configured provider — a village with a currently-`online` sensor uses that sensor's own reading and its own declared `source` tag (never silently upgraded to REAL just because a sensor exists — this build's demo sensors still declare `simulated`, honestly, since no physical hardware exists here); a village with no sensor, or an offline/stale one, falls through to the provider path exactly as before this change. This is now a real, complete implementation of the diagram above: LOCAL SENSOR → SATELLITE/REGIONAL ESTIMATE (Open-Meteo, if `real` is configured) → ANTECEDENT/SIMULATED PROXY → REDUCED CONFIDENCE, all three stages now actually wired rather than the first stage being aspirational. See `tests/backend/test_risk_sensor_wiring.py` for the fallback-behavior tests and `docs/Limitations.md` for what this does and doesn't prove.

## Pilot region

**Chosen (Phase 2): the Mandakini valley, Rudraprayag district, Uttarakhand** — the real catchment of the 16-17 June 2013 Kedarnath flash flood. 6 real, sourced villages seeded, real river-order topology modelled. Full reasoning and citations in `docs/Data_Sources.md`.

**Second real valley (Phase 11): the Chamoli Disaster Valley, Chamoli district, Uttarakhand** — the Rishiganga/Dhauliganga corridor to the Alaknanda at Vishnuprayag/Joshimath, real site of the 7 February 2021 rock-ice-avalanche flash flood. 4 real, sourced villages (all `surveyed` precision), 1 real historical event. Added to prove the region registry (below) generalizes to a genuinely different, independently-sourced valley — not a duplicated copy of Mandakini. Full reasoning and citations in `docs/Data_Sources.md`.

## Region registry — scaling to more than one valley (Phase 11)

Through Phase 10, the schema/API/frontend all implicitly assumed exactly one pilot valley. A user request to extend coverage to flash-flood-prone villages across northern India surfaced that assumption directly — and ran straight into problem-statement item 2's explicit constraint not to attempt modelling all of India. The resolution, and the reason this section exists: build the architecture to scale honestly, populate it only as far as real sourcing work has actually gone.

```
Region (real, named valley; status: active | planned)
   └── MicroCatchment (1+ per region)
          └── Village (1+ per catchment)
                 └── HistoricalEvent (0+ per village)
```

`Region` (`backend/app/models/orm.py`) groups one or more `MicroCatchment` rows and carries a `status` field that is never allowed to overclaim: `active` means real village-level data is seeded in this database right now; `planned` means the valley is real, documented, and cited (a genuine flash-flood/landslide/GLOF-prone place with a real historical disaster) but has not yet been sourced to village level — `village_count` stays honestly `0` for those. `GET /regions` (`backend/app/api/routes/regions.py`) lists all of them; `?region_id=` on `GET /villages`, `GET /catchments`, and `GET /risk/map` scopes to one region at a time, with no filter behaving exactly as it did before Phase 11 so every existing caller keeps working unchanged.

As of Phase 11, 2 regions are `active` (Mandakini Valley, Chamoli Disaster Valley — see above) and 3 are `planned` (South Lhonak/Teesta in Sikkim, Jhelum Basin/Kashmir Valley in J&K, Beas River Basin/Kullu-Manali in Himachal Pradesh — each a real, cited valley the architecture already supports). See `docs/Region_Onboarding.md` for the real checklist a `planned` region goes through to become `active`, and `docs/Data_Sources.md` for the full citation list.

The Authority dashboard's region selector (`frontend/src/views/AuthorityView.tsx`) scopes the map, catchment panel, risk panel, explanation panel, and (client-side, against the scoped village list) sensors and alerts to whichever region is selected, defaulting to "All regions." `PilotMap.tsx`'s elevation-order visual-aid line is grouped per catchment rather than drawn once globally, specifically so two unrelated valleys' villages showing on screen together never get connected by a nonsense line between them.

## Evacuation routing + historical event replay (Phase 12)

**Evacuation routing.** No real road/trail network is sourced yet (tracked in `docs/Future_Work.md`), so routing reuses the one real topology the app already has: consecutive elevation-order villages within a micro-catchment — the same proxy already used for `upstream_rainfall` (risk engine) and the nearest-upstream-village lookup (Phase 10 lead time). `backend/app/services/evacuation.py` builds a `networkx.DiGraph` per catchment (nodes = villages, edges between consecutive elevation-order pairs, weighted by real haversine distance — `lead_time.py`'s `haversine_meters`, reused rather than reimplemented) and runs `nx.shortest_path` from the requested origin down to the catchment's real lowest-elevation seeded village. The destination is never a fabricated "shelter" — it's whichever real village the catchment topology already ends at. `estimated_minutes` divides route distance by `ASSUMED_WALKING_SPEED_KMH = 5.0`, cited to Naismith's Rule (a documented hiking-pace heuristic, not a fitted or measured value for this terrain). A hop is flagged `unsafe` when either endpoint's *live*, freshly-computed `risk_level` is `HIGH`/`CRITICAL` — a derived heuristic combining data the app already trusts elsewhere, not a new hazard model. `GET /evacuation/route/{village_id}`'s `note` field states plainly that this is prototype routing, not real road/trail data. `GET /evacuation/priority` reuses the same live risk + lead-time inputs to produce a transparent, explainable sort (severity, then warning time, then score) rather than inventing a composite risk-priority formula — consistent with the project's stance (see `docs/Limitations.md`) against manufacturing a false sense of precision.

**Historical event replay.** `EventTimelineEntry` (`backend/app/models/orm.py`) stores one real, individually-cited sub-event per row, ordered by `sequence_order`, against a `HistoricalEvent`. `scripts/seed_event_timelines.py` currently seeds two: the 2013 Kedarnath disaster and the 2021 Reni/Tapovan (Chamoli) disaster, each built entirely from documented, cited sources — never an invented minute-by-minute narrative. Every entry's `time_precision` (`exact_time`, `approximate`, or `date_only`) says exactly how well-documented that moment actually is, so the two disasters' genuinely sparse public timelines are represented honestly rather than smoothed over. Real IST-sourced clock times (IMD bulletins, survivor-account timestamps) are converted to the correct UTC instant before storage; `date_only` entries are deliberately left at UTC-midnight rather than converted, since there is no real clock time to convert and converting would silently shift the displayed calendar date backward by one day. `GET /replay/events` only lists events that actually have a seeded timeline — an event without one simply doesn't appear, rather than appearing empty or fabricated. The frontend's `ReplayPanel.tsx` steps through the real ordered array client-side (Previous/Next); there is no backend replay "session" or simulated clock, matching the removal of the old `POST /replay/start` stub.

## Glacial-lake-proximity advisory field (Phase 12 follow-up)

User-requested follow-up: how close is each village to a real, mapped glacial lake — genuinely useful GLOF-risk context that the Phase 4 baseline's 4 components don't capture at all. `scripts/prepare_glacial_lake_data.py` is a one-off prep script (needs `geopandas`, kept out of `backend/requirements.txt` the same way the DEM delineation tooling is — see `gis/requirements.txt`) that reads the real Zhang et al. 2023 shapefile (figshare 21708590), filters to India's 3 Himalayan regions, computes real lake centroids in the source's own projected CRS (never directly in a geographic CRS, which would silently distort the result), and writes a lightweight, committed CSV: `data/derived/real_himalaya_glacial_lakes.csv` (4,881 real lakes). `backend/app/services/glacial_lake_proximity.py` loads that CSV once per process (`lru_cache`), and `nearest_glacial_lake(lat, lon)` does a real linear-scan nearest-neighbor search (haversine, reusing `lead_time.py`'s `haversine_meters` — well under a millisecond at ~4,900 rows, no spatial index needed) to find the closest lake, capped at `MAX_RELEVANT_DISTANCE_KM = 100` before a lake stops being reported as "nearby."

This is deliberately exposed as an **advisory field** (`glacial_lake_distance_km` / `glacial_lake_note` on both `GET /risk/map` and `GET /risk/{village_id}`, computed live in `risk_engine.compute_risk_for_village` alongside `lead_time` — same non-persisted pattern as `lead_time_note`), not folded into `risk_score`/`risk_level` as a 5th weighted component. Two real reasons, stated in the module's own docstring: raw straight-line distance is a weak proxy for actual GLOF hazard (lake type, dam material, volume, and downstream channel/slope all matter and aren't modeled here), and there is no real calibration data to say how much weight proximity should carry relative to the baseline's existing components — the same honesty problem `docs/ML_Methodology.md` documents for the undeployed ML layer. If a lake-attribute-aware GLOF hazard model becomes available, that's the path to a real weighted component (tracked in `docs/Future_Work.md`); until then, an uncalibrated number folded into the score would look more precise than it is.
