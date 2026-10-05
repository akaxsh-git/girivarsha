# ml/

Phase 5 ML pipeline, plus two Phase 12 follow-ups that assembled and expanded real training data. Read `docs/ML_Methodology.md` first.

**Synthetic pipeline (Phase 5)** — proves the pipeline mechanics work, not real-world skill:
- `generate_synthetic_training_data.py` — generates a labelled synthetic dataset (real village elevations, synthetic everything else). Ground-truth labels come from a known function of the features, not from anything that happened in the real world.
- `train.py` — trains the model-comparison ladder (rainfall-only → +soil → +terrain → all sources) with XGBoost, a real temporal train/test split, and honest metrics.

**Real data pipeline (Phase 12 follow-up #1)** — genuine real events, genuine (if weak) real metrics, still not deployment-grade:
- `assemble_real_events.py` — pulls two real, published, cited datasets (`data/raw/`, see `data/raw/README.md`) into `data/real_glof_events.csv` (70 real, POINT-precision, coordinate-located Himalayan-arc GLOF events) and `data/real_india_hillstate_candidate_events.csv` (404 real, cited, but uncoordinated India hill-state flood events).
- `backfill_real_weather.py` — makes **live calls to NASA POWER** (no API key, but real network I/O — not run automatically by tests) to attach real rainfall features to the GLOF subset, writing `data/real_flood_training_features.csv` (144 real rows: 36 positive, 108 negative).

**Real data pipeline (Phase 12 follow-up #2, user-requested) — geocoding the previously-uncoordinated candidates:**
- `geocode_ifi_candidates.py` — makes **live calls to OpenStreetMap Nominatim** (free, no API key, 1 req/sec, real retry/backoff on rate limits) to resolve each single-district IFI candidate event's `(state, district)` to a real district-centroid coordinate. Deliberately skips multi-district events (2+ districts recorded for one event — no single honest point exists for those). Writes `data/real_india_hillstate_events_geocoded.csv` (311 of the 404 candidates, `coordinate_precision: district_centroid_geocoded`).
- `backfill_ifi_weather.py` — makes **live calls to NASA POWER** for the 311 geocoded events (checkpointed/resumable — this genuinely takes several minutes and multiple runs may be needed to finish), writing `data/real_ifi_training_features.csv` (927 real rows: 309 positive, 618 negative).
- `merge_real_training_data.py` — combines the two real pipelines' outputs into `data/real_flood_training_features_combined.csv` (**1,071 real rows, 345 positive**), tagging every row `coordinate_precision: point_source` or `district_centroid` so the precision difference is never blended away silently.
- `train_real.py` — trains/evaluates **two** real models (LogisticRegression and, now that N is large enough to responsibly consider it, XGBoost) on the combined data, with **both** a single temporal split and a 4-fold expanding-window temporal cross-validation — the CV aggregate is the honest headline result, not the single split, because the single split's test window turned out to be skewed by the IFI source's own recency-reporting bias (see the script's own module docstring for the full explanation). See `docs/ML_Methodology.md` for the actual numbers and what they don't show.

- `requirements.txt` — `pip install -r ml/requirements.txt` (xgboost, scikit-learn, pandas, plus openpyxl/requests for the real-data pipelines — kept separate from `backend/requirements.txt` since the running API never imports this code).
- `artifacts/` — `python train.py` regenerates `artifacts/metrics.json`; `python train_real.py` regenerates `artifacts/real_data_metrics.json`.

Run the synthetic pipeline:
```bash
cd backend && source .venv/bin/activate
pip install -r ../ml/requirements.txt
cd ../ml
python train.py
```

Run the real pipeline (the CSVs under `data/` are already committed — you only need to regenerate them if you want fresher live pulls):
```bash
cd backend && source .venv/bin/activate
pip install -r ../ml/requirements.txt
cd ../ml
python assemble_real_events.py       # re-derives data/real_glof_events.csv + data/real_india_hillstate_candidate_events.csv from the raw sources
python backfill_real_weather.py      # live calls to NASA POWER (GLOF subset) — takes ~2-3 min
python geocode_ifi_candidates.py     # live calls to OpenStreetMap Nominatim — takes ~3-4 min
python backfill_ifi_weather.py       # live calls to NASA POWER (geocoded IFI subset) — takes 10+ min; safe to interrupt and re-run, it resumes from where it left off
python merge_real_training_data.py   # combines both real pipelines into the 1,071-row combined dataset
python train_real.py                 # trains + reports honest metrics (both models, both split methodologies) on the combined real data
```

Test it (pipeline mechanics only — no network calls in tests):
```bash
cd backend && source .venv/bin/activate
python -m pytest ../tests/ml -v
```
