"""
Tests for the real ML training-data assembly pipeline (ml/assemble_real_events.py,
ml/backfill_real_weather.py, ml/train_real.py) — the real counterpart to
tests/ml/test_pipeline.py's synthetic-pipeline tests.

These tests do NOT make live network calls (ml/backfill_real_weather.py
hits NASA POWER over HTTP — never invoked here). They instead check:
1. The assembly logic against the actual committed raw source files
   (small, real, third-party datasets under ml/data/raw/) — proving no
   row is fabricated and every row carries a real citation.
2. The date-parsing logic against representative fixture strings taken
   from the real source data's own formatting quirks.
3. The training-pipeline mechanics (temporal split, honest metrics) using
   a small hand-built DataFrame — mirroring test_pipeline.py's approach
   for the synthetic pipeline, i.e. this proves the CODE is correct, not
   that the already-committed real_flood_training_features.csv's numbers
   represent validated flood-prediction skill (they don't — see
   ml/train_real.py's own docstring).

Needs ml/requirements.txt installed, same as test_pipeline.py.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml"))

from assemble_real_events import (  # noqa: E402
    HIMALAYA_GLOF_COUNTRIES,
    HIMALAYA_HILL_STATES,
    _parse_glof_date,
    assemble_glof_events,
    assemble_ifi_candidate_events,
)
from train_real import FEATURES, honest_metrics, temporal_split  # noqa: E402

RAW_DIR = Path(__file__).resolve().parents[2] / "ml" / "data" / "raw"


@pytest.mark.skipif(
    not (RAW_DIR / "glof_moraine_dammed_v_zenodo15825574.xlsx").exists(),
    reason="raw GLOF source file not present in this checkout",
)
def test_glof_events_are_all_real_coordinate_located_and_cited():
    df = assemble_glof_events()
    assert len(df) > 0
    assert df["lat"].notna().all() and df["lon"].notna().all(), (
        "every row must have real coordinates — a row with none should have been dropped, not fabricated"
    )
    assert (df["country"].isin(HIMALAYA_GLOF_COUNTRIES)).all()
    assert (df["dataset_citation"].str.len() > 20).all(), "every row must carry a real, non-empty citation"
    # No duplicated source rows silently doubled by the filter/merge logic.
    assert df["source_id"].is_unique


@pytest.mark.skipif(
    not (RAW_DIR / "india_flood_inventory_v3_zenodo16994648.csv").exists(),
    reason="raw IFI source file not present in this checkout",
)
def test_ifi_candidate_events_are_hill_state_only_and_honestly_uncoordinated():
    df = assemble_ifi_candidate_events()
    assert len(df) > 0
    assert (df["state"].isin(HIMALAYA_HILL_STATES)).all()
    # This source dataset has no coordinates — the assembly step must not
    # invent any rather than honestly saying so.
    assert (df["has_coordinates"] == False).all()  # noqa: E712
    assert (df["dataset_citation"].str.len() > 20).all()


@pytest.mark.parametrize(
    "raw,expected_date,expected_precision",
    [
        ("1998", "1998-01-01", "year_only"),
        ("Before 1966", "1966-01-01", "year_only_upper_bound"),
        ("2019/11/14-2020/8/28", "2019-11-14", "approximate"),
        ("1966-1974", "1966-01-01", "year_range_lower_bound"),
    ],
)
def test_glof_date_parsing_never_invents_precision_the_source_lacks(raw, expected_date, expected_precision):
    parsed_date, precision = _parse_glof_date(raw)
    assert parsed_date == expected_date
    assert precision == expected_precision


def test_glof_date_parsing_handles_real_datetime_objects():
    import datetime

    parsed_date, precision = _parse_glof_date(datetime.datetime(2013, 6, 7))
    assert parsed_date == "2013-06-07"
    assert precision == "exact_date"


def test_glof_date_parsing_is_honest_about_missing_data():
    parsed_date, precision = _parse_glof_date(None)
    assert parsed_date is None
    assert precision == "unknown"


def _fixture_training_frame() -> pd.DataFrame:
    # Small hand-built frame — NOT claimed as real, used only to test the
    # split/metric mechanics in isolation from ml/backfill_real_weather.py's
    # live network calls.
    rows = []
    for i in range(20):
        rows.append(
            {
                "date": f"2010-01-{i+1:02d}",
                "label": 1 if i % 4 == 0 else 0,
                "max_daily_rainfall_mm": 10.0 + i,
                "rainfall_intensity_mm_hr_proxy": (10.0 + i) / 24,
                "rainfall_cumulative_3day_mm": 20.0 + i,
                "rainfall_cumulative_7day_mm": 40.0 + i,
                "elevation_m": 3000.0,
            }
        )
    return pd.DataFrame(rows)


def test_temporal_split_never_leaks_future_rows_into_training():
    df = _fixture_training_frame()
    train, test = temporal_split(df, test_frac=0.3)
    assert len(train) + len(test) == len(df)
    assert train["date"].max() <= test["date"].min()


def test_honest_metrics_reports_confusion_matrix_and_never_crashes_on_single_class():
    # Regression guard: roc_auc_score raises if y_true has only one class —
    # honest_metrics must degrade to None, not crash the whole training run.
    metrics = honest_metrics([0, 0, 0], [0, 0, 1], [0.1, 0.2, 0.6])
    assert metrics["roc_auc"] is None
    assert metrics["confusion_matrix"]["fp"] == 1


def test_features_list_has_no_fabricated_soil_or_upstream_columns():
    # The real dataset genuinely has no soil-moisture or upstream-rainfall
    # signal (unlike the synthetic pipeline / Phase 4 baseline) — this
    # guards against someone quietly adding a feature that isn't real.
    assert "soil_moisture" not in FEATURES
    assert "upstream_rainfall" not in FEATURES
    assert set(FEATURES) == {
        "max_daily_rainfall_mm",
        "rainfall_intensity_mm_hr_proxy",
        "rainfall_cumulative_3day_mm",
        "rainfall_cumulative_7day_mm",
        "elevation_m",
    }
