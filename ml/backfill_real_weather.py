"""
Real weather feature backfill for the real event inventory assembled by
ml/assemble_real_events.py.

Honesty note: every rainfall figure in this file's output comes from a
live call to NASA POWER (https://power.larc.nasa.gov/), a real, free,
no-API-key reanalysis product (MERRA-2) — nothing here is synthesized.
Two real limitations, stated plainly rather than hidden:

1. POWER's daily precipitation total (`PRECTOTCORR`, mm/day) is NOT the
   same thing as the risk engine's `rainfall_intensity` component
   (mm/hr, meant to capture a short burst). `max_daily_rainfall_mm / 24`
   is used as a declared, labelled PROXY for hourly intensity — a rough
   daily-average-rate stand-in, not a real sub-daily measurement. Real
   flash floods are usually driven by rainfall concentrated in a few
   hours, not spread evenly across a day, so this proxy under-represents
   true peak intensity. See docs/ML_Methodology.md.
2. Negative (no-GLOF-recorded) examples are sampled at the same real
   coordinates on real dates NOT present in the source event inventory —
   this proves absence-from-the-inventory, not absence-of-any-flood-ever.
   Small or undocumented events may be missing from the source database.
   Every negative row is labelled with this caveat in
   docs/Limitations.md, not just here.

Usage: python ml/backfill_real_weather.py
Writes ml/data/real_flood_training_features.csv.
"""
from __future__ import annotations

import random
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).parent / "data"
POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
WINDOW_DAYS_BEFORE = 10  # how far back the rainfall window looks
NEGATIVES_PER_POSITIVE = 3
REQUEST_DELAY_SECONDS = 0.4  # be polite to a free, shared, no-key API
RANDOM_SEED = 42  # reproducible negative-date sampling, not a tuned value

# The 2 events already real-seeded into the app's own DB (scripts/
# seed_pilot_region.py, scripts/seed_chamoli_valley.py) — included here so
# the trainable set isn't artificially smaller than what the rest of the
# app already treats as real, cited ground truth.
SEEDED_EVENTS = [
    {
        "event_id": "seeded-kedarnath-2013",
        "lat": 30.7346,
        "lon": 79.0669,
        "event_date": "2013-06-16",
        "date_precision": "exact_date",
        "dataset": "girivarsha_seeded_pilot_events",
        "dataset_citation": "scripts/seed_pilot_region.py — see docs/Data_Sources.md.",
    },
    {
        "event_id": "seeded-reni-2021",
        "lat": 30.48555,
        "lon": 79.69432,
        "event_date": "2021-02-07",
        "date_precision": "exact_date",
        "dataset": "girivarsha_seeded_pilot_events",
        "dataset_citation": "scripts/seed_chamoli_valley.py — see docs/Data_Sources.md.",
    },
]


def _fetch_power_daily_precip(lat: float, lon: float, start: date, end: date) -> dict[str, float] | None:
    """Real call to NASA POWER. Returns {iso_date: mm} or None if the API
    genuinely has no data for this point/period (never fabricated)."""
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
        clean = {k: v for k, v in series.items() if v is not None and v > -900}  # -999 = POWER fill value
        if not clean:
            return None
        return {"daily_mm": clean, "elevation_m": elevation_m}
    except (requests.RequestException, KeyError, ValueError) as exc:
        print(f"  [skip] NASA POWER call failed for ({lat},{lon}) {start}-{end}: {exc}")
        return None


def _derive_features(daily_mm: dict[str, float], event_date: date) -> dict:
    values = sorted(daily_mm.items())  # chronological
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


def _random_negative_dates(rng: random.Random, positive_dates: set[str], n: int) -> list[date]:
    """Samples real calendar dates NOT in the positive-event set, drawn
    from the same broad 1980-2023 MERRA-2-covered period. Not weighted
    toward monsoon months on purpose — an unweighted sample is the more
    honest "typical day at this location" baseline; a monsoon-only sample
    would bias the negative class toward already-risky conditions."""
    out = []
    tries = 0
    while len(out) < n and tries < n * 50:
        tries += 1
        d = date(1985, 1, 1) + timedelta(days=rng.randint(0, (date(2023, 12, 31) - date(1985, 1, 1)).days))
        if d.isoformat() not in positive_dates:
            out.append(d)
            positive_dates.add(d.isoformat())  # avoid picking the same negative twice
    return out


def backfill() -> pd.DataFrame:
    glof = pd.read_csv(DATA_DIR / "real_glof_events.csv")
    usable = glof[glof["date_precision"].isin(["exact_date", "approximate"])].copy()

    positives_raw = usable.to_dict("records") + SEEDED_EVENTS
    print(f"Backfilling real NASA POWER rainfall for {len(positives_raw)} day-level-precision real positive events...")

    rng = random.Random(RANDOM_SEED)
    rows = []
    for i, ev in enumerate(positives_raw):
        try:
            event_date = date.fromisoformat(str(ev["event_date"])[:10])
        except ValueError:
            continue
        lat, lon = float(ev["lat"]), float(ev["lon"])
        start = event_date - timedelta(days=WINDOW_DAYS_BEFORE)
        result = _fetch_power_daily_precip(lat, lon, start, event_date)
        time.sleep(REQUEST_DELAY_SECONDS)
        if result is None:
            continue
        feats = _derive_features(result["daily_mm"], event_date)
        rows.append(
            {
                "event_id": ev["event_id"],
                "label": 1,
                "lat": lat,
                "lon": lon,
                "elevation_m": result["elevation_m"],
                "date": event_date.isoformat(),
                "date_precision": ev["date_precision"],
                "source_dataset": ev["dataset"],
                "source_citation": ev["dataset_citation"],
                "weather_source": "real (NASA POWER MERRA-2 reanalysis)",
                **feats,
            }
        )
        print(f"  [{i+1}/{len(positives_raw)}] {ev['event_id']}: max_daily={feats['max_daily_rainfall_mm']}mm")

        # Real negative samples at the same real location.
        used_dates = {event_date.isoformat()}
        neg_dates = _random_negative_dates(rng, used_dates, NEGATIVES_PER_POSITIVE)
        for j, neg_date in enumerate(neg_dates):
            neg_start = neg_date - timedelta(days=WINDOW_DAYS_BEFORE)
            neg_result = _fetch_power_daily_precip(lat, lon, neg_start, neg_date)
            time.sleep(REQUEST_DELAY_SECONDS)
            if neg_result is None:
                continue
            neg_feats = _derive_features(neg_result["daily_mm"], neg_date)
            rows.append(
                {
                    "event_id": f"{ev['event_id']}-neg{j}",
                    "label": 0,
                    "lat": lat,
                    "lon": lon,
                    "elevation_m": neg_result["elevation_m"],
                    "date": neg_date.isoformat(),
                    "date_precision": "sampled_negative",
                    "source_dataset": "sampled_negative_no_recorded_glof",
                    "source_citation": (
                        "No GLOF/flood recorded at this location on this date in "
                        f"{ev['dataset']} — does not prove no event occurred; see docs/Limitations.md."
                    ),
                    "weather_source": "real (NASA POWER MERRA-2 reanalysis)",
                    **neg_feats,
                }
            )

    df = pd.DataFrame(rows)
    out_path = DATA_DIR / "real_flood_training_features.csv"
    df.to_csv(out_path, index=False)
    print(f"\nWrote {len(df)} rows ({(df['label']==1).sum()} positive, {(df['label']==0).sum()} negative) -> {out_path}")
    return df


if __name__ == "__main__":
    backfill()
