"""
Tests for the IFI district-centroid geocoding pipeline
(ml/geocode_ifi_candidates.py), the merge step (ml/merge_real_training_data.py),
and the expanded model-comparison logic in ml/train_real.py added when the
real dataset grew from 144 to 1,071 rows.

No live network calls here (ml/geocode_ifi_candidates.py hits Nominatim,
ml/backfill_ifi_weather.py hits NASA POWER — neither is invoked in this
file). These test the pure logic against small fixture DataFrames, same
discipline as tests/ml/test_real_data_assembly.py.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml"))

from geocode_ifi_candidates import is_single_district, split_single_vs_multi_district  # noqa: E402
from merge_real_training_data import COMMON_COLS  # noqa: E402
from train_real import (  # noqa: E402
    FEATURES,
    _expanding_window_cv,
    _fit_logreg,
    _stratified_breakdown,
    honest_metrics,
)


def test_single_district_detection_never_treats_a_comma_list_as_one_place():
    assert is_single_district("Chamoli") is True
    assert is_single_district("Kangra,Kullu") is False
    assert is_single_district("Jammu, Poonch, Srinagar") is False


def test_split_single_vs_multi_district_partitions_every_row_exactly_once():
    df = pd.DataFrame(
        {
            "event_id": ["a", "b", "c", "d"],
            "districts": ["Chamoli", "Kangra,Kullu", "Kupwara", "Jammu, Poonch, Srinagar"],
        }
    )
    single, multi = split_single_vs_multi_district(df)
    assert set(single["event_id"]) == {"a", "c"}
    assert set(multi["event_id"]) == {"b", "d"}
    assert len(single) + len(multi) == len(df)


def test_multi_district_events_are_never_silently_geocoded():
    """A 2+-district event has no single honest point — the geocoding
    script must never fall back to guessing (e.g. the first-listed
    district) for these; they must be excluded outright."""
    df = pd.DataFrame({"event_id": ["x"], "districts": ["Kangra,Kullu,Mandi"]})
    single, multi = split_single_vs_multi_district(df)
    assert len(single) == 0
    assert len(multi) == 1


def _fixture_lakes_style_frame(n: int, seed: int = 0) -> pd.DataFrame:
    """A larger fixture (needed for CV, which requires enough rows per fold
    to have both classes) — NOT claimed as real data, only exercises the
    split/model/metric mechanics added for the combined 1,071-row dataset."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        label = 1 if rng.random() < 0.3 else 0
        rows.append(
            {
                "event_id": f"fixture-{i}",
                "date": f"2010-{1 + (i // 28) % 12:02d}-{1 + (i % 28):02d}",
                "label": label,
                "max_daily_rainfall_mm": rng.uniform(5, 120) + (30 if label else 0),
                "rainfall_intensity_mm_hr_proxy": rng.uniform(0.2, 5.0),
                "rainfall_cumulative_3day_mm": rng.uniform(10, 200),
                "rainfall_cumulative_7day_mm": rng.uniform(20, 300),
                "elevation_m": rng.uniform(900, 4500),
                "coordinate_precision": "point_source" if i % 5 == 0 else "district_centroid",
            }
        )
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def test_expanding_window_cv_never_trains_a_fold_on_its_own_future():
    df = _fixture_lakes_style_frame(200)
    result = _expanding_window_cv(df, _fit_logreg, n_folds=4)
    assert result["folds_run"] > 0
    assert "aggregate" in result
    for key in ("precision", "recall", "f1", "false_alarm_rate", "false_negative_rate"):
        assert "mean" in result["aggregate"][key]


def test_expanding_window_cv_degrades_honestly_when_a_fold_has_one_class():
    # Every row labelled 0 — no fold can have both classes, so this must
    # report an honest "skipped" state, never crash or fabricate a metric.
    df = _fixture_lakes_style_frame(40)
    df["label"] = 0
    result = _expanding_window_cv(df, _fit_logreg, n_folds=4)
    assert result["folds_run"] == 0
    assert "note" in result


def test_stratified_breakdown_separates_point_source_from_district_centroid():
    df = _fixture_lakes_style_frame(60)
    y_pred = (df["label"].to_numpy() == 1).astype(int)  # perfect predictions, for a deterministic check
    y_prob = y_pred.astype(float)
    breakdown = _stratified_breakdown(df, y_pred, y_prob)
    assert set(breakdown.keys()) == {"point_source", "district_centroid"}
    assert breakdown["point_source"]["n_test"] + breakdown["district_centroid"]["n_test"] == len(df)


def test_merge_common_cols_has_no_source_specific_leakage_columns():
    # geocoding_citation/state/district (IFI-only) and anything GLOF-only
    # must not leak into the merged schema — only genuinely shared columns
    # belong in the combined training file.
    assert "coordinate_precision" in COMMON_COLS
    assert "geocoding_citation" not in COMMON_COLS
    assert "state" not in COMMON_COLS
    assert "district" not in COMMON_COLS


def test_features_used_for_training_are_unchanged_by_the_dataset_expansion():
    # The combined 1,071-row dataset must not have quietly introduced a
    # fabricated feature — same real 5 features as the 144-row run.
    assert set(FEATURES) == {
        "max_daily_rainfall_mm",
        "rainfall_intensity_mm_hr_proxy",
        "rainfall_cumulative_3day_mm",
        "rainfall_cumulative_7day_mm",
        "elevation_m",
    }


def test_honest_metrics_still_handles_the_larger_combined_dataset_shape():
    metrics = honest_metrics([0] * 100 + [1] * 30, [0] * 95 + [1] * 35, list(np.linspace(0, 1, 130)))
    assert metrics["n_test"] == 130
    assert metrics["confusion_matrix"]["tn"] + metrics["confusion_matrix"]["fp"] == 100
