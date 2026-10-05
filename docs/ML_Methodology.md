# ML Methodology

**Status: baseline (non-ML) layer is real as of Phase 4; the ML layer itself is not yet implemented — planned for Phase 5.** This file will be filled in as the ML layer is actually built, not before, so it never describes a model that doesn't exist.

## What exists today (Phase 4): the transparent baseline, not ML

`backend/app/services/risk_engine.py` implements "Layer A" from `docs/Architecture.md` — a plain, documented weighted sum of four components (current rainfall, soil moisture, max rainfall among upstream villages in the same micro-catchment, and historical-event susceptibility), each normalized 0-1 and combined with configurable weights (`GIRIVARSHA_RISK_WEIGHTS__*` / `backend/app/core/config.py`). It is deliberately not machine learning: there's nothing to train, no train/test split, no metrics to report, because it's a fixed formula, not a fitted model. `GET /api/v1/version` reports `active_model.trained: false` for exactly this reason — it must never be confused with a validated predictive model.

This baseline exists specifically so the ML layer below has something to compare against and fall back to: per the problem statement's "hybrid risk engine" requirement, Phase 5's ML model augments this baseline, it doesn't replace it — if the ML layer is ever unavailable or under-confident, the system can still show a village a transparent, explainable score.

## Phase 5 result: insufficient real data, exactly as flagged above

**This is the explicit statement problem-statement item 9 asks for: there is not enough real labelled historical event data in this pilot region to train or validate a scientifically valid predictive model.** The database has exactly one recorded historical event (2013 Kedarnath — see `docs/Data_Sources.md`). Training a classifier on one positive example produces a model whose reported accuracy is meaningless — it either memorizes that one point or learns nothing, and there is no way to hold out a test set that means anything. Rather than do that and report a fake-looking precision/recall number, Phase 5 built and tested the pipeline that WILL train a real model once enough real events exist, and proved its mechanics work using a synthetic, clearly-labelled dataset instead.

### What was built and actually run

- `ml/generate_synthetic_training_data.py` — generates a labelled dataset. The only real thing in it is the six pilot villages' elevations (checked against `scripts/seed_pilot_region.py` by a test, so they can't silently drift). Rainfall, soil moisture, and the "event" label are synthetic, generated from a known formula — see the module's docstring for exactly what and why.
- `ml/train.py` — the model comparison ladder from problem-statement item 10 (rainfall-only → +soil → +terrain[elevation] → all sources), XGBoost with `scale_pos_weight` for the deliberate class imbalance (~15-20% positive rate, chosen to resemble a rare-hazard base rate), a temporal train/test split (never a random shuffle — the last 20% of days become the test set), and the honest metric set the problem statement asks for (precision, recall, F1, ROC-AUC, false-alarm rate, false-negative rate — never accuracy alone).

### What it actually showed (reproducible: `python ml/train.py`, seed 42, 1200 synthetic days, `ml/artifacts/metrics.json`)

| Model | Features | Precision | Recall | F1 | ROC-AUC | False-alarm rate | False-negative rate |
|---|---|---|---|---|---|---|---|
| A — rainfall only | rainfall_intensity | 0.332 | 0.656 | 0.441 | 0.672 | 0.393 | 0.344 |
| B — +soil | +soil_moisture | 0.343 | 0.583 | 0.432 | 0.665 | 0.333 | 0.417 |
| C — +terrain | +elevation_m | 0.325 | 0.565 | 0.412 | 0.660 | 0.351 | 0.435 |
| D — all sources | +upstream_rainfall, historical_susceptibility | 0.330 | 0.589 | 0.423 | 0.662 | 0.357 | 0.411 |

**Honest reading of this table**: every model scores meaningfully above random (AUC 0.5) on the synthetic ground truth — this is what actually matters here, since it confirms the pipeline mechanics (feature assembly, temporal split, class-imbalance handling, metric computation) are correctly implemented and not silently broken (`tests/ml/test_pipeline.py` asserts exactly this, with a >0.55 AUC floor, and fails loudly if a future change breaks the pipeline). What this table does **not** show is a clean "more data sources = better" progression — Model D isn't clearly ahead of Model A here. That's not being hidden or explained away: with only a synthetic generator and no real events, this run cannot support a real claim about whether multi-source fusion helps in this domain. Answering that for real requires real labelled events, which don't exist yet for this pilot region.

### What would unblock a real model

More real historical flash-flood/landslide events for this valley or comparable Himalayan catchments (e.g. from ISRO's Landslide Atlas, state disaster-management records, or news-archive mining with careful geocoding) — enough to support a genuine train/test split with a meaningful number of positive examples in both. Until then, `GET /api/v1/risk/*` continues to run entirely on the Phase 4 transparent baseline (`backend/app/services/risk_engine.py`), and `GET /api/v1/version`'s `ml_layer` field reports this status (`"status": "not_deployed"`) rather than silently pretending an ML layer is live.

## Real training-data assembly (Phase 12 follow-up, user-requested)

The section above described what would unblock a real model. This is that work, actually done, with an honest accounting of exactly how far it goes.

**What was assembled, and from where:**

- `ml/assemble_real_events.py` pulls two real, published, cited datasets (raw files + full citations in `ml/data/raw/README.md`): the **Global inventory of moraine-dammed GLOFs (1900-2020)** (609 events worldwide, Zenodo 15825574), filtered to the real Himalayan arc most comparable to the two pilot valleys (India, Nepal, Bhutan, Pakistan — 70 events, all real-coordinate-located), and the **India Flood Inventory with Impacts (IFI-Impacts) v3** (6,876 IMD-sourced events, Zenodo 16994648), filtered to India's five Himalayan hill states and flash-flood/cloudburst/landslide/GLOF-tagged causes (404 events). The IFI subset has **no coordinates in the source data** (it's district-level, not point-located) — kept as a real, cited candidate list (`ml/data/real_india_hillstate_candidate_events.csv`) for future region-onboarding/geocoding work, not force-fitted into ML features it doesn't actually have.
- `ml/backfill_real_weather.py` attaches real rainfall features to the 39 GLOF events with day-level date precision, plus the app's own 2 already-seeded real events (Kedarnath 2013, Reni 2021) — 41 attempted, 36 succeeded (5 pre-1981 events failed honestly: NASA POWER's MERRA-2 reanalysis starts in 1981, so those windows genuinely have no data, and the script skips them rather than fabricating a value). Every rainfall figure is a live call to **NASA POWER** (`power.larc.nasa.gov`, free, no API key, MERRA-2 reanalysis) — real satellite/reanalysis data, not synthetic. 108 real-weather negative samples (3 per positive) were drawn at the same real coordinates on real dates absent from the source inventories, honestly labelled as "not recorded," not "confirmed absent" — see the caveat in `ml/backfill_real_weather.py`'s docstring and `docs/Limitations.md`.
- Result: **144 real rows (36 positive, 108 negative)** in `ml/data/real_flood_training_features.csv`, spanning real dates 1982-2023 — up from the single real Kedarnath event Phase 5 had to work with.

**`ml/train_real.py` — real training run, real honest metrics** (reproducible: `python ml/train_real.py`, `ml/artifacts/real_data_metrics.json`):

| Metric | Value |
|---|---|
| Test rows (temporal split, last 25%) | 36 (12 positive) |
| Precision | 0.385 |
| Recall | 0.417 |
| F1 | 0.400 |
| ROC-AUC | 0.649 |
| False-alarm rate | 0.333 |
| False-negative rate | 0.583 |

**Honest reading**: ROC-AUC of 0.649 is meaningfully above random (0.5) — there is real, if weak, signal in real rainfall data predicting real recorded GLOF events, which is itself a genuine (if modest) finding. It is nowhere near strong enough for deployment: a 58.3% false-negative rate means this model would miss more than half of real events in the test set, which is not an acceptable miss rate for a life-safety warning system. Three real, structural reasons this isn't a validated model, not just "needs more data" hand-waving:

1. **144 rows is still small** for a rare-event classifier — the 36 real positive events are a genuine improvement over 1, but still far short of what comparable published studies use.
2. **The 36 events are geographically scattered** across four countries and glacial-lake elevations (2,100-5,000m) very different from either pilot valley's village elevations (900-3,600m) — this model captures general "does heavy rain precede a GLOF" signal, not anything specific to the Mandakini or Chamoli catchments.
3. **No real soil-moisture or upstream-catchment-rainfall features exist for this dataset** (unlike the Phase 4 baseline, which has both) — only rainfall and elevation are real and available here, so this can't yet be compared apples-to-apples against the baseline's 4-component formula.

`GET /api/v1/version`'s `ml_layer` status is **unchanged by this work** — it still correctly reports `not_deployed`. This training run is a genuine step (single real event → 36 real events, "cannot evaluate" → "weak-but-real 0.649 AUC"), not the threshold for putting a model behind live risk scores. See `docs/Limitations.md` for the full caveat list carried alongside every real figure above.

**What would close the gap further**: backfilling weather for the 5 GLOF events with only year-level date precision (needs a wider search window and more careful handling of which year's rainfall actually caused the flood); geocoding a meaningful subset of the 404 real IFI candidate events (would need real district-centroid coordinates, honestly tagged `approximate` the same way village coordinates already are — see `docs/Data_Sources.md`); and, longer-term, a real per-catchment soil-moisture proxy so this dataset's features actually match the baseline's.

## Real training-data assembly, follow-up #2 (user-requested — geocoding the 404 uncoordinated candidates)

The section above flagged geocoding the 404 uncoordinated IFI candidate events as the next real step. This is that work, done, with the same honest accounting.

**What was assembled:**

- `ml/geocode_ifi_candidates.py` makes real, live calls to **OpenStreetMap Nominatim** (free, no API key) to resolve each IFI candidate event's `(state, district)` to a real, OSM-administrative-boundary-derived district centroid. Deliberately geocodes only the **332 single-district events** — the other 72 span 2-27 districts each, and collapsing a multi-district event to one point would misrepresent the source data's own precision, so those stay honestly uncoordinated, same as before. Real rate-limiting (429s — this build environment's outbound network is shared, so the real request volume exceeded even a compliant 1 req/sec) required real retry/backoff logic, not a synthetic delay tweak. Result: **311 of the 332 real events successfully geocoded** (21 districts genuinely had no Nominatim match) to `ml/data/real_india_hillstate_events_geocoded.csv`, tagged `coordinate_precision: district_centroid_geocoded`.
- `ml/backfill_ifi_weather.py` attaches real NASA POWER rainfall to all 311, the same live-call methodology as before, plus 2 real-weather negatives per positive (622 negatives) — **927 real rows (309 positive, 618 negative)** in `ml/data/real_ifi_training_features.csv`. This genuinely takes 10+ minutes of real network I/O; the script checkpoints every 10 events and safely resumes an interrupted run rather than re-fetching already-real data.
- `ml/merge_real_training_data.py` combines this with the original 144-row point-precision dataset into **`ml/data/real_flood_training_features_combined.csv` — 1,071 real rows, 345 positive** (up from 144/36) — with every row tagged `coordinate_precision: point_source` (144 rows — the actual GLOF lake or seeded village) or `district_centroid` (927 rows — a real, but coarser, Nominatim geocode; the true event site could be tens of km from the district centroid used to pull rainfall for a large district).

**`ml/train_real.py` — now compares two real models, two real evaluation methodologies, and surfaces a real methodological finding along the way** (reproducible: `python ml/train_real.py`, `ml/artifacts/real_data_metrics.json`):

A single 75/25 temporal split (the same methodology as follow-up #1) gave a suspiciously strong-looking result — ROC-AUC 0.78-0.82, false-negative rate 0.12-0.14. **This was investigated, not reported at face value.** The cause: the IFI source documents recent years far more thoroughly than older ones (2022-2023 alone contribute ~19% of all combined rows, almost all positive), so a "last 25% by date" split lands mostly in that recent, positive-heavy tail — the resulting test set was ~77% positive, nothing like the full dataset's ~32% positive rate, which flattered recall/precision in a way that isn't representative of real performance across the dataset's actual time range.

Because of this, `train_real.py` now also runs a **4-fold expanding-window temporal cross-validation** (each fold trains only on data strictly before its own test window) and treats the **CV aggregate as the headline result**, not the single split:

| Metric (4-fold CV, mean ± std) | LogisticRegression | XGBoost |
|---|---|---|
| Precision | 0.595 ± 0.269 | 0.569 ± 0.276 |
| Recall | 0.728 ± 0.116 | 0.657 ± 0.183 |
| F1 | 0.634 ± 0.207 | 0.599 ± 0.237 |
| ROC-AUC | 0.768 ± 0.052 | 0.747 ± 0.062 |
| False-alarm rate | 0.319 ± 0.063 | 0.336 ± 0.094 |
| **False-negative rate** | **0.273 ± 0.116** | 0.343 ± 0.183 |

**Honest pick: LogisticRegression**, by lowest mean false-negative rate — not XGBoost, despite XGBoost now being large-enough-N to responsibly try (unlike follow-up #1's 144-row run, where it was skipped outright). This matters as a finding in itself: more model sophistication did not automatically buy a better safety-relevant metric at this data volume and this much fold-to-fold variance (std of 0.116-0.183 on false-negative rate is large — read every mean here as a rough estimate, not a precise number).

**Honest reading of the headline (CV) numbers**: ROC-AUC ~0.77 is a real, meaningful improvement over follow-up #1's 0.649 — genuinely more real signal found with ~7x the data. A ~27% mean false-negative rate is still not deployment-safe for a life-safety system (missing roughly 1 in 4 real events, with real fold-to-fold variance meaning some periods would miss noticeably more), but it is a real, substantial improvement over follow-up #1's 58.3%. Structural reasons this still isn't validated, beyond "needs more data":

1. **The single-split-vs-CV disagreement is itself evidence of real non-stationarity** in this combined dataset (driven by the IFI source's own recency-reporting bias, not a flaw in the flooding phenomenon itself) — a reminder that dataset-level artifacts can silently inflate a single flattering split, which is exactly why this project reports the CV aggregate as headline rather than cherry-picking the better-looking number.
2. **927 of the 1,071 rows carry district-centroid, not point, precision** — `real_data_metrics.json`'s `single_split_by_coordinate_precision` breaks this down per model, though the point-precision stratum only has 12 rows in the single split (too few to read confidently on its own; reported for transparency, not as a validated comparison).
3. **No real soil-moisture or upstream-catchment-rainfall features exist for this dataset** — same limitation as follow-up #1, still not comparable apples-to-apples against the Phase 4 baseline's 4-component formula.
4. **XGBoost's hyperparameters are a conservative, documented default** (shallow trees, few estimators, subsampling), not tuned against a held-out validation fold — there isn't enough real data to spare a third split without shrinking the test set past a trustworthy read.

`GET /api/v1/version`'s `ml_layer` status is **still unchanged** — `not_deployed`. A real, meaningfully better false-negative rate (58.3% → ~27%) is genuine progress on the data problem, not a deployment threshold crossed; a system that would still miss roughly 1 in 4 real flash-flood/landslide events is not ready to sit behind a life-safety warning. See `docs/Limitations.md` for the full caveat list.

## Planned approach once real data exists (target design, per `docs/Architecture.md`)

- **Done (Phase 9), for the model that's actually live:** `GET /model/explanation/{village_id}` ranks and narrates the baseline's own real components in plain language (`backend/app/services/explanation.py`) — the model-agnostic "why" feature, built against Layer A since that's what's deployed. If/when Layer B (the ML model documented in this file) is ever deployed, a real SHAP explainer belongs behind this same endpoint instead — that swap is explicitly flagged in the module's docstring, not silently pretended to already exist.
- Cross-validation once data volume supports it.
- Revisiting the normalization caps and weight priors in `risk_engine.py` with real data instead of the documented-but-unfitted starting values used today.
