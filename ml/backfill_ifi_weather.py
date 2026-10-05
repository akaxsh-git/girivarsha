"""
Real weather feature backfill for the 311 real, district-centroid-geocoded
India Flood Inventory (IFI) events written by ml/geocode_ifi_candidates.py.

Same honest discipline as ml/backfill_real_weather.py (the GLOF-inventory
counterpart), plus one extra caveat specific to this source:

  **These positives carry DISTRICT-CENTROID coordinates, not exact event
  sites.** A real Nominatim geocode of "<district>, <state>, India" (see
  ml/geocode_ifi_candidates.py) — genuinely real, but coarser than the GLOF
  inventory's lake-level coordinates. Some of these districts are large
  (e.g. Lohit, Arunachal Pradesh, spans thousands of km²), so the real
  rainfall pulled here is for the district's administrative centroid, which
  may be tens of kilometres from where the actual flood/landslide/cloud-
  burst happened. This is disclosed per-row via `coordinate_precision` and
  in every downstream metrics/caveat block — never silently upgraded to
  look as precise as a point-sourced GLOF event.

Resumable by design: this script makes ~900 real, rate-limited NASA POWER
calls (311 positives + up to 2 real negatives each), which does not
reliably finish inside one shell invocation's time budget. Every batch of
rows fetched is checkpointed to the output CSV immediately, and a re-run
skips event_ids already present in that file — safe to interrupt and
re-run to pick up where it left off, never re-fetching what's already real
data on disk.

Usage: python ml/backfill_ifi_weather.py
Writes/appends ml/data/real_ifi_training_features.csv.
"""
from __future__ import annotations

import random
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).parent / "data"
IN_PATH = DATA_DIR / "real_india_hillstate_events_geocoded.csv"
OUT_PATH = DATA_DIR / "real_ifi_training_features.csv"

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
WINDOW_DAYS_BEFORE = 10
NEGATIVES_PER_POSITIVE = 2  # lower than the GLOF backfill's 3 — this batch
# is ~4.5x larger (311 vs 70 positives), so this keeps total real API calls
# in a similar ballpark rather than ballooning past ~900.
REQUEST_DELAY_SECONDS = 0.35
RANDOM_SEED = 42
CHECKPOINT_EVERY = 10  # positives processed between disk writes


def _fetch_power_daily_precip(lat: float, lon: float, start: date, end: date) -> dict[str, float] | None:
    params = {
        "parameters": "PRECTOTCORR",
        "community": "AG",
        "longitude": lon,
        "latitude": lat,
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
    }
    try:
        resp = requests.get(POWER_URL, params=params, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        series = payload["properties"]["parameter"]["PRECTOTCORR"]
        elevation_m = payload.get("geometry", {}).get("coordinates", [None, None, None])[2]
        clean = {k: v for k, v in series.items() if v is not None and v > -900}
        if not clean:
            return None
        return {"daily_mm": clean, "elevation_m": elevation_m}
    except (requests.RequestException, KeyError, ValueError) as exc:
        print(f"  [skip] NASA POWER call failed for ({lat},{lon}) {start}-{end}: {exc}")
        return None


def _derive_features(daily_mm: dict[str, float]) -> dict:
    values = sorted(daily_mm.items())
    amounts = [v for _, v in values]
    max_daily = max(amounts) if amounts else None
    cum3 = sum(amounts[-3:]) if len(amounts) >= 3 else sum(amounts)
    cum7 = sum(amounts[-7:]) if len(amounts) >= 7 else sum(amounts)
    return {
        "max_daily_rainfall_mm": round(max_daily, 2) if max_daily is not None else None,
        "rainfall_intensity_mm_hr_proxy": round(max_daily / 24, 3) if max_daily is not None else None,
        "rainfall_cumulative_3day_mm": round(cum3, 2),
        "rainfall_cumulative_7day_mm": round(cum7, 2),
    }


def _random_negative_date(rng: random.Random, avoid: set[str]) -> date:
    while True:
        d = date(1985, 1, 1) + timedelta(days=rng.randint(0, (date(2023, 12, 31) - date(1985, 1, 1)).days))
        if d.isoformat() not in avoid:
            avoid.add(d.isoformat())
            return d


def backfill() -> pd.DataFrame:
    src = pd.read_csv(IN_PATH)

    done_ids: set[str] = set()
    existing_rows: list[dict] = []
    if OUT_PATH.exists():
        prev = pd.read_csv(OUT_PATH)
        existing_rows = prev.to_dict("records")
        # A positive's negatives are keyed off its own event_id prefix — if
        # the positive row exists, treat that whole group as done so a
        # resume never re-fetches a partially-completed group inconsistently.
        done_ids = {r["event_id"].split("-neg")[0] for r in existing_rows if r.get("label") == 1}
        print(f"Resuming: {len(done_ids)} positive events already backfilled in {OUT_PATH}, skipping those.")

    todo = src[~src["event_id"].isin(done_ids)].reset_index(drop=True)
    print(f"{len(todo)} of {len(src)} district-centroid-geocoded events remain to backfill.")

    rng = random.Random(RANDOM_SEED)
    rows: list[dict] = list(existing_rows)

    for i, ev in todo.iterrows():
        try:
            event_date = datetime.strptime(str(ev["start_date"])[:16], "%d-%m-%Y %H:%M").date()
        except ValueError:
            print(f"  [skip] unparseable start_date {ev['start_date']!r} for {ev['event_id']}")
            continue

        lat, lon = float(ev["lat"]), float(ev["lon"])
        start = event_date - timedelta(days=WINDOW_DAYS_BEFORE)
        result = _fetch_power_daily_precip(lat, lon, start, event_date)
        time.sleep(REQUEST_DELAY_SECONDS)
        if result is None:
            continue
        feats = _derive_features(result["daily_mm"])
        rows.append(
            {
                "event_id": ev["event_id"],
                "label": 1,
                "lat": lat,
                "lon": lon,
                "elevation_m": result["elevation_m"],
                "date": event_date.isoformat(),
                "date_precision": "district_centroid_geocoded",
                "source_dataset": ev["dataset"],
                "source_citation": ev["dataset_citation"],
                "geocoding_citation": ev["geocoding_citation"],
                "weather_source": "real (NASA POWER MERRA-2 reanalysis)",
                "state": ev["state"],
                "district": ev["districts"],
                **feats,
            }
        )
        print(f"  [{i+1}/{len(todo)}] {ev['event_id']} ({ev['districts']}, {ev['state']}): max_daily={feats['max_daily_rainfall_mm']}mm")

        avoid = {event_date.isoformat()}
        for j in range(NEGATIVES_PER_POSITIVE):
            neg_date = _random_negative_date(rng, avoid)
            neg_start = neg_date - timedelta(days=WINDOW_DAYS_BEFORE)
            neg_result = _fetch_power_daily_precip(lat, lon, neg_start, neg_date)
            time.sleep(REQUEST_DELAY_SECONDS)
            if neg_result is None:
                continue
            neg_feats = _derive_features(neg_result["daily_mm"])
            rows.append(
                {
                    "event_id": f"{ev['event_id']}-neg{j}",
                    "label": 0,
                    "lat": lat,
                    "lon": lon,
                    "elevation_m": neg_result["elevation_m"],
                    "date": neg_date.isoformat(),
                    "date_precision": "sampled_negative",
                    "source_dataset": "sampled_negative_no_recorded_ifi_event",
                    "source_citation": (
                        f"No IFI-recorded flood/landslide event at this district centroid on this "
                        f"date in {ev['dataset']} — does not prove no event occurred; see docs/Limitations.md."
                    ),
                    "geocoding_citation": ev["geocoding_citation"],
                    "weather_source": "real (NASA POWER MERRA-2 reanalysis)",
                    "state": ev["state"],
                    "district": ev["districts"],
                    **neg_feats,
                }
            )

        if (i + 1) % CHECKPOINT_EVERY == 0:
            pd.DataFrame(rows).to_csv(OUT_PATH, index=False)
            print(f"    [checkpoint] {len(rows)} rows written to {OUT_PATH}")

    df = pd.DataFrame(rows)
    df.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {len(df)} total rows ({(df['label']==1).sum()} positive, {(df['label']==0).sum()} negative) -> {OUT_PATH}")
    return df


if __name__ == "__main__":
    backfill()
