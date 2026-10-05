# Data Sources

Per problem-statement item 6, every piece of data in this system is tagged as one of:

- **REAL** — an actual public observation/dataset.
- **SIMULATED** — a virtual/synthetic stream used to demonstrate system behaviour, always labelled as such.
- **DERIVED** — computed from real and/or simulated inputs (e.g. slope from a real DEM).

## Current status (Phase 9-10 update)

`SimulatedRainfallProvider`/`SimulatedSoilMoistureProvider` (`backend/app/providers/base.py`) are still the **default** — but as of Phase 9-10, `RealRainfallProvider`/`RealSoilMoistureProvider` are genuinely implemented (not placeholders) against [Open-Meteo](https://open-meteo.com/en/docs)'s free forecast API, which needs **no API key**. Set `GIRIVARSHA_ACTIVE_RAINFALL_PROVIDER=real` and/or `GIRIVARSHA_ACTIVE_SOIL_PROVIDER=real` in `backend/.env` to switch either input from simulated to live — see README.md's "Real weather data (optional)" section for the exact steps and what it does to confidence.

**Why this wasn't verified end-to-end in this build environment:** this sandbox's outbound network is restricted to an allowlist (package registries, WebSearch/WebFetch) — a direct `curl` to `api.open-meteo.com` was rejected by the egress proxy (`403`, confirmed via `curl -v`), the same restriction already documented above for the geocoding APIs. Unit tests (`tests/backend/test_providers.py`) cover the parsing/error-handling logic against a mocked response shape taken from Open-Meteo's published API docs, and the honest-fallback path was verified live in this sandbox (setting the env var to `real` here correctly raises `ProviderUnavailableError` and the risk engine degrades to the same simulated-tagged 0.0 fallback it already uses for any provider failure — it does not crash). **The live HTTP call itself has not been exercised from a real network connection** — the exact command to do that yourself:
```bash
curl "https://api.open-meteo.com/v1/forecast?latitude=30.7346&longitude=79.0669&current=precipitation,rain&timezone=UTC"
```
No API key needed, so this is a one-line check on any normal connection (unlike the OpenTopography DEM download, which needed a real registered key and was verified by the user directly — see `docs/GIS_Methodology.md`).

**What Phase 2 added:** real, sourced pilot-region data in the database — 6 villages, 1 micro-catchment, and 1 historical event for the **Mandakini valley, Rudraprayag district, Uttarakhand** (the catchment behind the 16–17 June 2013 Kedarnath flash flood). See `scripts/seed_pilot_region.py` for the full seed and per-row citations. Every village row carries `source_citation`-equivalent detail in its `provenance` field, plus a `coordinate_precision` flag:

| Village | Elevation (m) | Coordinate precision | Why |
|---|---|---|---|
| Kedarnath | 3583 | `surveyed` | Wikipedia infobox states coordinates directly (30.73°N, 79.07°E) |
| Rambara | 2740 | `approximate` | Elevation sourced (Mandakini River article); no precise coordinates found — interpolated along the documented river corridor |
| Gaurikund | 1982 | `approximate` | Elevation sourced (6,502 ft, Gaurikund article); coordinates interpolated |
| Sonprayag | 1360 | `approximate` | Confluence location and river relationship sourced; **elevation is an unverified estimate**, not sourced — flagged for follow-up |
| Ukhimath | 1311 | `approximate` | Elevation sourced; coordinates interpolated; possible side-valley position noted as a caveat |
| Rudraprayag | 895 | `surveyed` | Wikipedia infobox states coordinates directly (30.28°N, 78.98°E) |

**Why "approximate" instead of survey-grade for 4 of 6 villages:** this sandbox's outbound network access is restricted to an allowlist (package registries, WebSearch/WebFetch) — direct calls to OpenStreetMap Overpass, Nominatim, and open elevation APIs were all rejected by the egress proxy (verified: connection attempts logged `connect_rejected`). Rather than fabricate decimal-precision coordinates, positions were interpolated along the real, Wikipedia-documented river path between the two anchor points that do have surveyed coordinates. **Replacing these four with verified coordinates (OSM extract, Bhuvan/Survey of India data, or field GPS) is open follow-up work — tracked in `docs/Limitations.md`, not hidden.**

The micro-catchment's upstream→downstream topology (Kedarnath → Rambara → Gaurikund → Sonprayag/Ukhimath → Rudraprayag) is real, sourced from the Mandakini River Wikipedia article's documented path — this is genuine river topology, not an invented ordering. Its *polygon* geometry (`geom` column) is intentionally left null; that requires real DEM delineation, which is Phase 3 GIS work.

## Second pilot valley — Chamoli Disaster Valley (Phase 11)

**Chamoli district, Uttarakhand** — the Rishiganga/Dhauliganga corridor to the Alaknanda at Vishnuprayag/Joshimath, real site of the 7 February 2021 disaster: a ~27 million m³ rock-ice avalanche detached from a hanging glacier near Ronti Peak (Nanda Devi region) and ran down as a catastrophic debris flow/flash flood, destroying the Rishiganga and Tapovan-Vishnugad hydropower projects and killing roughly 200 people. Seeded by `scripts/seed_chamoli_valley.py`; linked into the region registry (`GET /regions`, `status: "active"`) by `scripts/seed_regions.py`.

| Village | Elevation (m) | Coordinate precision | Source |
|---|---|---|---|
| Reni (Raini) | 1973 | `surveyed` | GEER Association Chamoli reconnaissance report (peer-reviewed engineering survey) — Wikipedia's own article has no infobox coordinates |
| Tapovan | 1787 | `surveyed` | Wikipedia, *Tapovan Vishnugad Hydropower Plant* (intake sill position) |
| Vishnuprayag | 1372 | `surveyed` | Wikipedia, *Vishnuprayag* — real Dhauliganga/Alaknanda confluence, modelled as this catchment's outlet |
| Joshimath | 1875 | `surveyed` | Wikipedia, *Joshimath* — see caveat below |

All 4 rows are `surveyed` precision — on coordinates, this valley is better-sourced than Mandakini (which has 4-of-6 `approximate`). No population figures are included (left `null`) — none could be verified for these specific settlements through the sources used, and an honest `null` was preferred over a guess.

**Known, concrete limitation — Joshimath's elevation vs. real river order:** Joshimath's Wikipedia elevation (1,875m) reflects the *town's* position on a terrace above the river, not the river's true elevation at the immediately-adjacent Vishnuprayag confluence (1,372m) — even though Vishnuprayag is the actually-upstream point on the real river course relative to Joshimath. Because the risk/lead-time engine's "upstream" proxy orders purely by elevation within a catchment (see the note below and `docs/Limitations.md`), it picks Joshimath ahead of Vishnuprayag as "upstream" for villages like Tapovan — backwards from the real topology. This was deliberately left visible rather than patched by adjusting the elevation number to make the proxy look cleaner; see `scripts/seed_chamoli_valley.py`'s docstring and Joshimath's own `provenance` field for the same note in the code itself.

One real historical event is seeded: the 7 February 2021 flash flood, tied to Reni, `severity: "catastrophic"`.

Sources: [2021 Uttarakhand flood](https://en.wikipedia.org/wiki/2021_Uttarakhand_flood), [Tapovan Vishnugad Hydropower Plant](https://en.wikipedia.org/wiki/Tapovan_Vishnugad_Hydropower_Plant), [Vishnuprayag](https://en.wikipedia.org/wiki/Vishnuprayag), [Joshimath](https://en.wikipedia.org/wiki/Joshimath), [Dhauliganga River](https://en.wikipedia.org/wiki/Dhauliganga_River), [Rishiganga](https://en.wikipedia.org/wiki/Rishiganga) (all fetched 2026-09-04); ESA, ["Satellites reveal cause of Chamoli disaster"](https://www.esa.int/Applications/Observing_the_Earth/Satellites_reveal_cause_of_Chamoli_disaster); GEER Association Chamoli reconnaissance report (https://geerassociation.org/components/com_geer_reports/geerfiles/Chamoli_Report.pdf).

## Region registry — scaling beyond one valley (Phase 11)

`GET /regions` lists 5 real, named, documented flash-flood/landslide-prone Himalayan valleys, not placeholders: Mandakini Valley and the Chamoli Disaster Valley (`status: "active"` — real village-level data seeded, as above), plus 3 honestly `status: "planned"` valleys that the schema/API already support but that have **not** been sourced to village level (`village_count: 0`, never a fabricated number):

| Region | State | Real, cited event |
|---|---|---|
| South Lhonak / Teesta Valley | Sikkim | 3-4 October 2023 GLOF (South Lhonak Lake outburst, 90+ dead, Teesta III dam destroyed) |
| Jhelum Basin / Kashmir Valley | Jammu and Kashmir | September 2014 J&K floods (277 dead in J&K, Srinagar submerged) |
| Beas River Basin (Kullu-Manali) | Himachal Pradesh | July 2023 North India floods (severe monsoon flash flooding, Kullu-Manali-Leh highway destroyed) |

See `docs/Region_Onboarding.md` for exactly what sourcing a `planned` region up to `active` requires — the same rigor Mandakini and Chamoli both went through.

## Real ML training-data sources (Phase 12 follow-up)

Two real, published, third-party datasets back `ml/assemble_real_events.py` (raw files committed under `ml/data/raw/`, full per-file citations in `ml/data/raw/README.md`):

- **Global inventory of moraine-dammed GLOFs (1900-2020)** — Zenodo record [15825574](https://zenodo.org/records/15825574) (DOI: 10.5281/zenodo.15825574). 609 real, individually-sourced GLOF events worldwide; this project uses the 70-event Himalayan-arc subset (India, Nepal, Bhutan, Pakistan), all with real coordinates.
- **India Flood Inventory with Impacts (IFI-Impacts) v3, 1967-2023** — Zenodo record [16994648](https://zenodo.org/records/16994648) (DOI: 10.5281/zenodo.4742142; project home: [hydrosenselab/India-Flood-Inventory](https://github.com/hydrosenselab/India-Flood-Inventory)). 6,876 real, IMD-sourced flood events; this project uses the 404-event subset from India's Himalayan hill states with flash-flood/cloudburst/landslide/GLOF-tagged causes. **No coordinates in the source data** originally — see the geocoding follow-up below for how 311 of these gained real coordinates.
- Real rainfall features for the trainable subset come from **NASA POWER** (`power.larc.nasa.gov`, MERRA-2 reanalysis, free, no API key) — live calls made by `ml/backfill_real_weather.py`, fetched 2026-09-04.

See `docs/ML_Methodology.md` for what was actually trained on this data and the honest metrics that came out of it.

## Real district-centroid geocoding for the IFI candidates (Phase 12 follow-up #2, user-requested)

**OpenStreetMap Nominatim** (`nominatim.openstreetmap.org`, free, no API key, ODbL-licensed OSM data) — `ml/geocode_ifi_candidates.py` makes real, rate-limited, retried live calls resolving `"<district> district, <state>, India"` to OSM's own real administrative-boundary centroid for that district. Fetched 2026-09-04. Applied only to the 332 (of 404) IFI candidate events recorded against exactly one district; 311 resolved successfully (21 had no Nominatim match), written to `ml/data/real_india_hillstate_events_geocoded.csv` with `coordinate_precision: district_centroid_geocoded`. The other 72 candidate events (recorded against 2-27 districts each) are deliberately left uncoordinated — no single point can honestly represent a multi-district event. `ml/backfill_ifi_weather.py` then attached real NASA POWER rainfall to all 311, producing 927 real training rows; `ml/merge_real_training_data.py` combines these with the original 144-row point-precision dataset into the 1,071-row `ml/data/real_flood_training_features_combined.csv` used by `ml/train_real.py`. See `docs/ML_Methodology.md` for the resulting metrics and `docs/Limitations.md` for what district-centroid precision does and doesn't mean for those numbers.

## Real glacial-lake inventory (Phase 12 follow-up — glacial-lake-proximity advisory field)

**Zhang, G., T. Bolch, T. Yao, D. R. Rounce, W. Chen, G. Veh, O. King, S. K. Allen, M. Wang, and W. Wang (2023), "Underestimated mass loss from lake-terminating glaciers in the greater Himalaya", Nature Geoscience** (DOI: [10.1038/s41561-023-01150-1](https://doi.org/10.1038/s41561-023-01150-1)). Data: figshare record [21708590](https://figshare.com/articles/dataset/Glacial_lake_inventory_1990_2000_2010_2015_and_2020_in_the_greater_Himalaya/21708590), downloaded 2026-09-04. 9,208 real, individually satellite-mapped (Landsat) glacial lakes across the Hindu Kush-Himalaya as of 2020 (the dataset's most recent of 5 snapshots), each with area, elevation, lake type, and parent-glacier RGI ID.

`scripts/prepare_glacial_lake_data.py` filters this to the 3 regions covering India's Himalayan arc (Western/Central/Eastern Himalaya, per the source dataset's own region classification), producing 4,881 real lakes (Central Himalaya 2,132, Eastern Himalaya 1,505, Western Himalaya 1,244), committed as `data/derived/real_himalaya_glacial_lakes.csv`. `backend/app/services/glacial_lake_proximity.py` loads this CSV and computes each village's real straight-line distance to the nearest lake — exposed as an **advisory field** (`glacial_lake_distance_km` / `glacial_lake_note`) on `GET /risk/map` and `GET /risk/{village_id}`, deliberately not folded into `risk_score`/`risk_level`. See that module's own docstring, and `docs/Limitations.md`, for why proximity alone isn't a validated GLOF hazard weight.

## Real glacier mass-balance (melt-rate) dataset (Phase 14+ follow-up, user-requested: "incorporate the melting rate of nearby glaciers into the risk score")

**Dussaillant, I. et al. (2025), "Annual mass changes for each glacier in the world from 1976 to 2023", Earth System Science Data** (preprint: [essd-2024-323](https://essd.copernicus.org/preprints/essd-2024-323/)), published via the **World Glacier Monitoring Service (WGMS)** as the "Annual Mass-Change Estimates" (AMCE) product — an update/extension of the widely-cited Hugonnet et al. (2021, *Nature*) "Accelerated global glacier mass loss in the early twenty-first century" methodology. Downloaded from [wgms.ch/downloads/wgms-amce-2026-02-10.zip](https://wgms.ch/downloads/wgms-amce-2026-02-10.zip) (version 2026-02-10), fetched 2026-09-06.

This is a real, per-glacier, RGI 6.0-identified (`RGIId` + centroid lat/lon) annual mass-balance time series (1957-2025, in metres water-equivalent/year) — negative = ice/snow mass loss. Worth stating plainly for the historical record: the first attempt at this (following Hugonnet et al. 2021's own data-portal link, a DOI resolving to a SEDOO/Theia landing page) dead-ended with no visible download link; WGMS's own re-published, updated version of the same underlying methodology turned out to be the real, actually-downloadable source, found via a second research pass.

`scripts/prepare_glacier_mass_balance_data.py` filters RGI regions 14 (South Asia West) and 15 (South Asia East) — the two regions whose glaciers actually fall in and around Uttarakhand's Garhwal Himalaya — to glaciers within 100km of any seeded pilot village, producing 1,967 real glaciers (483 region 14, 1,484 region 15), committed as `data/derived/real_himalaya_glacier_mass_balance.csv` with each glacier's 2021-2025 mean mass-balance rate, 2016-2020 prior-period mean, and the real trend between them. `backend/app/services/glacial_melt_hazard.py` loads this CSV and:

1. Computes a **genuine 5th weighted risk-engine component** (`glacial_melt_rate`, weight 0.10 — see `app/core/config.py`'s `RiskWeights`) from each village's nearest real glacier's recent mass-balance rate, normalized against the actual observed 5th-95th percentile range across the loaded dataset (not an arbitrary hand-picked cap). Unlike glacial-lake proximity, this IS folded into `risk_score`/`risk_level`, at the user's explicit request — the module's own docstring explains why a glacier's own melt rate is a narrower, more physically-defensible signal to weight than raw lake distance is, while being equally clear that the weight itself is still a small, documented, non-calibrated starting point, not a fitted result.
2. Computes an **advisory-only "GLOF contribution indicator"** (`glof_contribution_pct` / `glof_contribution_tier` / `glof_contribution_note`, 0-100 + LOW/MODERATE/HIGH) — an equal-weighted blend of real glacial-lake proximity and real glacier melt rate. This answers the underlying "how probable is a flash flood based on nearby glacial data" question honestly: it is explicitly **not** a calibrated statistical probability (no real outcome dataset exists to calibrate one against — the same honesty gap `docs/ML_Methodology.md` documents everywhere else), and every response carries that disclaimer in its own `note` text rather than as a silent bare percentage.

## Real SCS-CN rainfall-runoff layer (user-requested follow-up, from this project's own competitive-landscape research: "a real SCS-CN rainfall-runoff layer... would be the highest-value next addition")

Two real, third-party, live-fetchable datasets back this feature (both queried once by `scripts/prepare_scs_cn_inputs.py`, committed as `data/derived/real_village_scs_cn_inputs.csv` — no runtime dependency on either service):

- **ISRIC SoilGrids v2.0** — Poggio, L. et al. (2021), "SoilGrids 2.0: producing soil information for the globe with quantified spatial uncertainty", *SOIL*, 7, 217-240 (DOI: [10.5194/soil-7-217-2021](https://doi.org/10.5194/soil-7-217-2021)). Free, no-API-key REST API (`rest.isric.org/soilgrids/v2.0/properties/query`) — real, modelled 0-5cm soil clay/sand/silt percentages at each village's exact coordinate, fetched 2026-09-06.
- **ESA WorldCover 10m v200 (2021)** — Zanaga, D. et al. (2022), "ESA WorldCover 10 m 2021 v200" (DOI: [10.5281/zenodo.7254221](https://doi.org/10.5281/zenodo.7254221)). Free, public S3-hosted 10m global land-cover raster; `scripts/prepare_scs_cn_inputs.py` reads the single COG tile covering the pilot region directly via `rasterio`'s HTTP-range-read (`/vsicurl/`) mechanism — no full-tile download needed — fetched 2026-09-06.

`scripts/prepare_scs_cn_inputs.py` converts each village's real soil texture into a standard USDA texture class (boundary-condition classification against the published USDA soil-texture triangle) and then into a standard NRCS Hydrologic Soil Group (A/B/C/D), and reads its real WorldCover land-cover class. One disclosed real edge case found and handled: Vishnuprayag's exact coordinate sits at a literal river confluence and samples as WorldCover's "permanent water" class — the script falls back to an 11x11-pixel (~110m) window and takes the most common non-water/non-snow class instead of guessing, with the substitution disclosed in that village's own `land_cover_source_note` field rather than silently swapped in.

`backend/app/services/scs_cn_runoff.py` combines this real per-village soil/land-cover data with each village's current (possibly What-If-overridden) rainfall rate and soil-moisture reading to compute a real **SCS-CN (Soil Conservation Service Curve Number) direct-runoff-depth estimate** — the standard USDA-SCS (1972) method, still the basis of the modern NRCS TR-55 manual, with multiple published applications to Indian Himalayan hill catchments. This is a **second, independent, physically-grounded estimate** (`scs_cn_runoff_depth_mm`, `scs_cn_curve_number`, and related fields on `GET /risk/map`, `GET /risk/{village_id}`, and `POST /simulate`) shown **alongside**, and deliberately never folded into, `risk_score`/`risk_level` — same restraint already applied to the glacial-lake advisory field. See that module's own docstring, and `docs/Limitations.md`, for every disclosed simplification (a single assumed "hydrologic condition" per land-cover class since WorldCover has no condition field of its own; current soil moisture used as an Antecedent Moisture Condition proxy rather than 5-day antecedent rainfall; a 1-hour assumed storm duration converting the app's live rainfall rate into the depth the method needs; lambda=0.20, the method's own classic default initial-abstraction ratio).

## Real OpenStreetMap road/trail network (user-requested follow-up: "let's do the real road/trail data")

The "real OSM road-network... remains blocked by this build environment's own network restrictions" line that had sat in `docs/Future_Work.md` since Phase 3 is now out of date — this sandbox's connection to the Overpass API is genuinely flaky (repeated `Connection reset by peer` on `overpass-api.de`, occasional `429`s on the `overpass.kumi.systems` mirror) but no longer categorically rejected, and enough retries got through.

`scripts/prepare_road_network_data.py` fetches every real OpenStreetMap way tagged `highway=*` (deliberately including footway/path/track/bridleway, not just vehicle roads — Kedarnath itself has no road access at all) within a bounding box around each pilot valley, via the Overpass API, retrying across `overpass-api.de` and `overpass.kumi.systems`. Data is (c) OpenStreetMap contributors, licensed [ODbL 1.0](https://www.openstreetmap.org/copyright), fetched 2026-09-06. Excludes `highway=construction/proposed/razed/abandoned/planned` (not real, currently-usable routes). Output: **71,157 real nodes, 71,288 real edges** (62,051 Mandakini + 9,237 Chamoli), committed as `data/derived/real_himalaya_road_network.json` (6.1MB). Real highway-type breakdown: 30,934 unclassified, 17,349 path, 5,122 trunk, 4,996 track, 4,567 tertiary, 2,700 primary, plus smaller counts of secondary/residential/service/footway/bridleway/steps/living_street/pedestrian/road.

`backend/app/services/road_network.py` loads this once per process and provides real Dijkstra shortest-path routing between any two coordinates that each snap within 1.5km of the fetched network (a grid-bucketed nearest-neighbor search, not scipy/numpy — kept dependency-free). `backend/app/services/evacuation.py` uses this for each hop of a village's evacuation route, replacing the straight-line elevation-order-proxy distance with a real routed road/trail distance **wherever both endpoints actually snap and a real path connects them** — every hop's own `distance_source` field says honestly which case applied, never blended silently. See `docs/Limitations.md` for the concrete disclosed gap this surfaced (Rambara's own approximate coordinate lands on a real but disconnected trail fragment in the fetched extent).

## Real rainfall intensity-duration (I-D) landslide threshold (user-requested follow-up, from this project's own competitive-landscape research)

**Kanungo, D. P. & Sharma, Shaifaly (2014), "Rainfall thresholds for prediction of shallow landslides around Chamoli-Joshimath region, Garhwal Himalayas, India," *Landslides*, Vol. 11, pp. 629-638, DOI: [10.1007/s10346-013-0438-9](https://doi.org/10.1007/s10346-013-0438-9).** A real, peer-reviewed, region-specific study — unusually well-matched to this project, since the study area is literally this app's own Chamoli Disaster Valley pilot region (Reni/Tapovan/Vishnuprayag/Joshimath). Fetched/read 2026-09-06.

The paper derives a real intensity-duration (I-D) threshold for triggering shallow landslides in this region, for events up to 24 hours: **I = 1.82 x D^(-0.23)** (I in mm/hr, D in hours), with a stated critical/minimum intensity of **0.87 mm/hr** below which the paper's own dataset found no association between rainfall and a triggered landslide at any duration up to 24h.

`backend/app/services/rainfall_threshold.py` uses this real, cited formula as a **third independent indicator** (`rainfall_threshold_hours_to_threshold`, `rainfall_threshold_status`, `rainfall_threshold_applicability`) alongside the Phase 4 weighted score and the SCS-CN runoff estimate above, on `GET /risk/map`, `GET /risk/{village_id}`, and `POST /simulate` — deliberately never folded into `risk_score`/`risk_level`. Given a village's current (possibly What-If-overridden) rainfall rate, it solves for the duration at which that rate, held constant, would cross the published threshold curve — the same idiom real Flash Flood Guidance systems use ("how much rain in X hours would cause flooding"), applied here to a real regional curve instead of an invented one.

**Honestly disclosed two-tier applicability**, not silently blended: the Chamoli Disaster Valley genuinely IS the region the paper studied (`rainfall_threshold_applicability="direct_fit"`); the Mandakini valley (Kedarnath-Rudraprayag) is a different catchment in the same broader Garhwal Himalaya climatic/geological zone, so applying the same curve there is disclosed as a **regional proxy** (`"regional_proxy"`) — every result's `rainfall_threshold_note` states plainly which case applied. See `backend/app/services/rainfall_threshold.py`'s module docstring for the full formula and every other disclosed simplification (a constant-rate assumption, not a real hyetograph).

## Real antecedent-precipitation-index (user-requested follow-up)

The SCS-CN layer above (see "Real SCS-CN rainfall-runoff layer") disclosed one specific simplification: it used a village's *current* soil-moisture reading as a proxy for its Antecedent Moisture Condition (AMC), rather than the method's own textbook input — cumulative rainfall over the preceding days. This follow-up replaces that proxy with real rainfall history wherever it's available.

**NASA POWER (Prediction Of Worldwide Energy Resources), `power.larc.nasa.gov/api/temporal/daily/point`, parameter `PRECTOTCORR`, `community=AG`** — a free, no-API-key REST API backed by MERRA-2 reanalysis, already used elsewhere in this project (`ml/backfill_real_weather.py`). `backend/app/services/antecedent_rainfall.py` fetches each village's most recent 35 days of daily rainfall and sums the most recent real 5/10/20 days into `antecedent_rainfall_5day_mm` / `_10day_mm` / `_20day_mm`.

**One disclosed real-world limitation found while building this**: NASA POWER's most recent ~7-8 days of `PRECTOTCORR` consistently return its `-999.0` fill value — the source's own data hasn't finished processing yet, not a fetch failure. The module fetches a wide window and computes its sums from "the most recent real data actually available," never assuming that ends today, and states the exact lag honestly in every result's `note` (e.g. `"...as of 2026-08-30 (8d ago, due to this source's own processing latency, not today's live rainfall)"`).

The 5-day sum classifies **Antecedent Moisture Condition (AMC I/II/III)** using the classic SCS/NRCS season-dependent thresholds (Chow, Maidment & Mays, *Applied Hydrology* — the same textbook already cited for the SCS-CN method itself): growing season (Apr-Oct, disclosed simplification) I &lt;35.6mm, II 35.6-53.3mm, III &gt;53.3mm; dormant season I &lt;12.7mm, II 12.7-27.9mm, III &gt;27.9mm. `backend/app/services/scs_cn_runoff.py` uses this AMC class in place of the soil-moisture proxy **only when the antecedent result is genuinely real** (`antecedent_rainfall_source == "real"`) — the default `GIRIVARSHA_ACTIVE_ANTECEDENT_PROVIDER=simulated` setting deliberately leaves the original soil-moisture-proxy behavior untouched, so switching this feature on never silently changes any existing response by default. `scs_cn_note` states plainly which case applied.

As a bonus, disclosed context (not a separate risk field), the 10-day and 20-day sums are checked against the same **Kanungo & Sharma (2014)** thresholds already used for the I-D landslide threshold above (10-day &ge;55mm, 20-day &ge;185mm associated with landslide triggering in Chamoli-Joshimath) and noted when met or exceeded.

Exposed on `GET /risk/map` (`antecedent_rainfall_5day_mm`, `antecedent_rainfall_source`), `GET /risk/{village_id}` (all of `_5day_mm`/`_10day_mm`/`_20day_mm`/`_as_of`/`_source`/`_note`), and `POST /simulate` (a single, non-baseline/simulated-pair figure, since this is rainfall *history* and is deliberately unaffected by the rainfall/soil-moisture what-if overrides — see `antecedent_rainfall_note` there for why). Cached once per village per calendar day (`@lru_cache` keyed on rounded coordinate + today's date) to avoid repeat network calls per request.

## Target data inventory (to be integrated Phase 2+)

| Category | Target real source(s) | Status |
|---|---|---|
| Rainfall | Open-Meteo forecast API (free, no key) | **Integrated (opt-in, Phase 9-10)** — `GIRIVARSHA_ACTIVE_RAINFALL_PROVIDER=real`. IMD / NASA GPM-IMERG remain future upgrades for a India-specific, higher-resolution source. |
| Soil moisture | Open-Meteo forecast API (free, no key) | **Integrated (opt-in, Phase 9-10)** — `GIRIVARSHA_ACTIVE_SOIL_PROVIDER=real`, reports volumetric water content (top 0-1cm layer). NASA SMAP remains a future upgrade for satellite ground-truth. Real IoT sensors (Phase 8) are a separate, not-yet-wired-into-the-risk-engine data path — see `docs/IoT_Architecture.md`. |
| Terrain / DEM | SRTM / ASTER | Not yet integrated |
| Historical hazards | ISRO Landslide Atlas / NRSC, or other authoritative datasets | Partially integrated (Phase 12 follow-up) — see "Real ML training-data sources" above: 70 real, coordinate-located GLOF events + 404 real, cited (uncoordinated) hill-state flood events assembled from two published datasets, not yet ISRO's own atlas specifically |
| River/water level | IoT (ESP32 water-level sensor, real for the live demo where possible; simulated elsewhere) | Not yet integrated |
| Roads / trails | OpenStreetMap (Overpass API) | **Integrated (user-requested follow-up)** — real road/trail network for both pilot valleys now backs evacuation-route hop distances wherever it covers them; see "Real OpenStreetMap road/trail network" above |
| Shelters | NDMA/district shelter registries, on-ground survey | Not yet integrated — see `docs/Region_Onboarding.md` for what real sourcing would need |
| Glacial lake proximity (GLOF advisory context) | Zhang et al. 2023 / figshare 21708590 | **Integrated (Phase 12 follow-up)** — real, advisory-only field, not a weighted risk-engine input; see "Real glacial-lake inventory" above |
| Glacier melt rate (mass balance) | WGMS Annual Mass-Change Estimates (Dussaillant et al. 2025 / Hugonnet et al. 2021 methodology) | **Integrated (Phase 14+ follow-up, user-requested)** — real, weighted risk-engine component (`glacial_melt_rate`) plus an advisory GLOF contribution indicator; see "Real glacier mass-balance" above |
| Rainfall-runoff (soil/land-cover-based) | ISRIC SoilGrids v2.0 + ESA WorldCover 10m v200, via the standard SCS-CN method | **Integrated (Phase 14+ follow-up, user-requested)** — real, independent NRCS TR-55 runoff estimate shown alongside (never folded into) `risk_score`; see "Real SCS-CN rainfall-runoff layer" above |
| Rainfall intensity-duration landslide threshold | Kanungo & Sharma (2014), a real region-specific published study | **Integrated (user-requested follow-up, from this project's own competitive-landscape research)** — real, third independent advisory indicator, direct fit for Chamoli, disclosed regional proxy for Mandakini; see "Real rainfall intensity-duration (I-D) landslide threshold" above |
| Antecedent precipitation index (AMC classification) | NASA POWER (MERRA-2 reanalysis), free no-key API | **Integrated (opt-in, user-requested follow-up)** — `GIRIVARSHA_ACTIVE_ANTECEDENT_PROVIDER=real`; real 5/10/20-day rainfall sums drive the SCS-CN AMC classification (replacing the soil-moisture proxy) only when real, with the source's own ~7-8 day reporting lag honestly disclosed; see "Real antecedent-precipitation-index" above |

**Adapter pattern:** each category gets a `RealXProvider` and a `SimulatedXProvider` behind the same `DataProvider` interface (see `docs/Architecture.md`), selected via config (`GIRIVARSHA_ACTIVE_*_PROVIDER`). If a real API turns out to be inaccessible (auth-gated, rate-limited, down) the simulated provider stays the fallback and that limitation is documented here, not hidden.

## Rules this repo follows

- Never fabricate a real API response.
- Never present synthetic data as if it came from a government source.
- Every UI surface showing simulated data carries a visible "simulated" label (see the frontend's "SIMULATED DEMO DATA" pattern used in the concept dashboards, and the `source` field returned by every provider).
- When a real API is genuinely unavailable, the correct response is to build the adapter interface + a clearly-labelled simulated provider and keep going — not to stop, and not to fake the real one.

## Pilot region — chosen (Phase 2)

**Mandakini valley, Rudraprayag district, Uttarakhand** — the real catchment of the 16–17 June 2013 Kedarnath disaster, one of India's deadliest flash-flood/debris-flow events (widely reported figure: ~5,700 people declared dead or missing). This was a deliberate choice, not an arbitrary one:

- It is real, extensively documented, and directly on-topic for a flash-flood-in-hilly-regions system.
- The historical event gives the (eventual) ML layer at least one real, citable labelled event to reason about — rather than a valley with zero historical grounding.
- The river's real path (glacier source → Kedarnath → Rambara → Gaurikund → Sonprayag → confluence at Rudraprayag) gives genuine upstream/downstream topology to model, not an invented one.

Sources: [Mandakini River](https://en.wikipedia.org/wiki/Mandakini_River), [Kedarnath](https://en.wikipedia.org/wiki/Kedarnath), [Rudraprayag](https://en.wikipedia.org/wiki/Rudraprayag), [Gaurikund](https://en.wikipedia.org/wiki/Gaurikund), [Sonprayag](https://en.wikipedia.org/wiki/Sonprayag), [Ukhimath](https://en.wikipedia.org/wiki/Ukhimath) (all fetched 2026-09-03); [Down To Earth — "Remembering 2013 Uttarakhand Floods"](https://www.downtoearth.org.in/natural-disasters/heavens-rage-41497); ["A Tragic Flash Flood in Kedarnath Valley"](https://www.researchgate.net/publication/313221054_A_Tragic_Flash_Flood_in_Kedarnath_Valley_Its_Causes_and_Effects_in_Upstream_and_Down_Stream_of_Mandakini_River_Garhwal_Himalaya_Uttrakhand_India) (ResearchGate).
