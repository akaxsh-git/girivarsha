"""
Unit tests for the real rainfall intensity-duration (I-D) landslide-
threshold indicator (app/services/rainfall_threshold.py) — the third
independent indicator from this project's own competitive-landscape
research pass. Pure-function tests, no database or live network needed
(same offline-unit-test discipline as test_road_network.py's loader/
snapper/router tests).
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services.rainfall_threshold import (  # noqa: E402
    CRITICAL_INTENSITY_FLOOR_MM_HR,
    ID_THRESHOLD_COEFFICIENT,
    ID_THRESHOLD_EXPONENT,
    MAX_STUDIED_DURATION_HOURS,
    assess_rainfall_threshold,
)


def test_below_floor_intensity_is_not_assessed_as_a_crossing():
    result = assess_rainfall_threshold(0.3, "Chamoli Disaster Valley")
    assert result.status == "below_floor"
    assert result.hours_to_threshold is None
    assert f"{CRITICAL_INTENSITY_FLOOR_MM_HR:.2f}" in result.note


def test_zero_and_negative_intensity_degrade_honestly_not_crash():
    for bad_value in (0.0, -5.0, float("nan")):
        result = assess_rainfall_threshold(bad_value, None)
        assert result.status == "below_floor"
        assert result.current_intensity_mm_hr == 0.0


def test_high_intensity_already_exceeds_threshold_within_an_hour():
    # I(1hr) = 1.82mm/hr exactly — well above that means the crossing
    # duration is comfortably under 1 hour.
    result = assess_rainfall_threshold(10.0, "Mandakini Valley")
    assert result.status == "threshold_exceeded"
    assert result.hours_to_threshold is not None
    assert result.hours_to_threshold <= 1.0


def test_moderate_intensity_crosses_within_the_studied_24h_window():
    # Pick an intensity whose crossing duration is known to land inside
    # (1h, 24h] by construction, using the module's own formula.
    target_hours = 10.0
    intensity = ID_THRESHOLD_COEFFICIENT / (target_hours ** ID_THRESHOLD_EXPONENT)
    result = assess_rainfall_threshold(intensity, "Chamoli Disaster Valley")
    assert result.status == "approaching_within_24h"
    assert result.hours_to_threshold is not None
    assert math.isclose(result.hours_to_threshold, target_hours, rel_tol=1e-6)


def test_low_intensity_above_floor_is_not_indicated_within_24h():
    # Exactly at the floor (not below it, so the formula path runs, not the
    # below_floor short-circuit) — the crossing duration lands just beyond
    # the study's own validated 24h window at this exact rate.
    result = assess_rainfall_threshold(CRITICAL_INTENSITY_FLOOR_MM_HR, "Mandakini Valley")
    assert result.status == "not_indicated_within_24h"
    assert result.hours_to_threshold is not None
    assert result.hours_to_threshold > MAX_STUDIED_DURATION_HOURS


def test_chamoli_region_is_disclosed_as_a_direct_fit():
    result = assess_rainfall_threshold(5.0, "Chamoli Disaster Valley")
    assert result.applicability == "direct_fit"
    assert "direct fit" in result.note


def test_mandakini_region_is_disclosed_as_a_regional_proxy():
    result = assess_rainfall_threshold(5.0, "Mandakini Valley")
    assert result.applicability == "regional_proxy"
    assert "regional proxy" in result.note
    assert "not the study's own" in result.note


def test_unknown_region_still_degrades_honestly_as_a_proxy():
    result = assess_rainfall_threshold(5.0, None)
    assert result.applicability == "regional_proxy"
    assert result.region_name is None
    assert "this village's region" in result.note


def test_every_result_cites_the_real_source_study():
    for intensity in (0.1, 2.0, 20.0):
        result = assess_rainfall_threshold(intensity, "Chamoli Disaster Valley")
        assert "Kanungo" in result.note
        assert "10.1007/s10346-013-0438-9" in result.note
