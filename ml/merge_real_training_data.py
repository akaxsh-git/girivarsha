"""
Merges the two real training-data pipelines into one combined dataset:

  1. ml/data/real_flood_training_features.csv — 144 rows (36 positive GLOF
     events + the app's own 2 seeded events, plus real-weather negatives),
     POINT-precision coordinates (each positive's lat/lon is the actual
     glacial lake / seeded village, from ml/backfill_real_weather.py).
  2. ml/data/real_ifi_training_features.csv — 927 rows (309 positive India
     Flood Inventory events + real-weather negatives), DISTRICT-CENTROID-
     precision coordinates (each positive's lat/lon is a real Nominatim
     geocode of its district, from ml/geocode_ifi_candidates.py +
     ml/backfill_ifi_weather.py — coarser than #1's point precision).

Both are genuinely real (real events, real NASA POWER rainfall) — this
script does not blur that distinction, it tags it. Every merged row keeps
a `coordinate_precision` column (`point_source` for #1, `district_centroid`
for #2) so training/evaluation code — and anyone reading the combined CSV —
can always tell which rows carry coarser location precision, and so a
precision-stratified metrics breakdown (see ml/train_real.py) is possible
rather than reporting one blended number that hides the difference.

Usage: python ml/merge_real_training_data.py
Writes ml/data/real_flood_training_features_combined.csv.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
GLOF_PATH = DATA_DIR / "real_flood_training_features.csv"
IFI_PATH = DATA_DIR / "real_ifi_training_features.csv"
OUT_PATH = DATA_DIR / "real_flood_training_features_combined.csv"

COMMON_COLS = [
    "event_id",
    "label",
    "lat",
    "lon",
    "elevation_m",
    "date",
    "date_precision",
    "coordinate_precision",
    "source_dataset",
    "source_citation",
    "weather_source",
    "max_daily_rainfall_mm",
    "rainfall_intensity_mm_hr_proxy",
    "rainfall_cumulative_3day_mm",
    "rainfall_cumulative_7day_mm",
]


def merge() -> pd.DataFrame:
    glof = pd.read_csv(GLOF_PATH)
    glof["coordinate_precision"] = "point_source"

    ifi = pd.read_csv(IFI_PATH)
    ifi["coordinate_precision"] = "district_centroid"

    combined = pd.concat([glof[COMMON_COLS], ifi[COMMON_COLS]], ignore_index=True)
    combined = combined.sort_values("date").reset_index(drop=True)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUT_PATH, index=False)

    print(f"Merged {len(glof)} point-source rows + {len(ifi)} district-centroid rows -> {len(combined)} total rows.")
    print(f"  label counts: {combined['label'].value_counts().to_dict()}")
    print(f"  coordinate_precision counts: {combined['coordinate_precision'].value_counts().to_dict()}")
    print(f"Wrote {OUT_PATH}")
    return combined


if __name__ == "__main__":
    merge()
