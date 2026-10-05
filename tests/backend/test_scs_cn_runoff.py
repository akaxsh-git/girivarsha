"""
Unit tests for app/services/scs_cn_runoff.py — the real SCS-CN (Soil
Conservation Service Curve Number) rainfall-runoff estimate (user-requested
follow-up: "a real SCS-CN rainfall-runoff layer... would be the highest-
value next addition"). Like test_glacial_melt_hazard.py, these exercise the
module directly against a small, controlled fixture CSV — never the real
10-village committed dataset — so results are deterministic and don't
depend on scripts/prepare_scs_cn_inputs.py having been re-run.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services import scs_cn_runoff as scr  # noqa: E402
from app.services.antecedent_rainfall import AntecedentRainfallResult  # noqa: E402

FIELDNAMES = [
    "village_name",
    "lat",
    "lon",
    "clay_pct",
    "sand_pct",
    "silt_pct",
    "usda_texture_class",
    "hydrologic_soil_group",
    "worldcover_class_code",
    "worldcover_class_name",
    "land_cover_source_note",
    "soil_citation",
    "land_cover_citation",
]


def _write_fixture_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _reset_cache():
    scr._load_inputs.cache_clear()


def _row(name, lat, lon, hsg="B", wc_code=10, wc_name="Tree cover"):
    return {
        "village_name": name,
        "lat": str(lat),
        "lon": str(lon),
        "clay_pct": "20.0",
        "sand_pct": "40.0",
        "silt_pct": "40.0",
        "usda_texture_class": "Loam",
        "hydrologic_soil_group": hsg,
        "worldcover_class_code": str(wc_code),
        "worldcover_class_name": wc_name,
        "land_cover_source_note": "sampled directly at the village's coordinate",
        "soil_citation": "test",
        "land_cover_citation": "test",
    }


def test_missing_data_file_returns_honest_none_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(scr, "DATA_PATH", tmp_path / "does_not_exist.csv")
    _reset_cache()
    try:
        result = scr.estimate_runoff(30.0, 79.0, rainfall_mm_hr=20.0, soil_moisture_pct=50.0)
        assert result.runoff_depth_mm is None
        assert result.curve_number_used is None
        assert "not available" in result.note.lower()
    finally:
        _reset_cache()


def test_village_beyond_relevant_range_returns_honest_none(tmp_path, monkeypatch):
    csv_path = tmp_path / "inputs.csv"
    _write_fixture_csv(csv_path, [_row("Kedarnath", 30.7346, 79.0669)])
    monkeypatch.setattr(scr, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        # Somewhere in the Bay of Bengal, nowhere near the fixture village.
        result = scr.estimate_runoff(15.0, 88.0, rainfall_mm_hr=20.0, soil_moisture_pct=50.0)
        assert result.runoff_depth_mm is None
        assert result.curve_number_used is None
        assert "not available" in result.note.lower()
    finally:
        _reset_cache()


def test_malformed_row_is_skipped_not_guessed_at(tmp_path, monkeypatch):
    csv_path = tmp_path / "inputs.csv"
    csv_path.write_text(
        ",".join(FIELDNAMES) + "\n"
        "Bad,not-a-number,79.0,20,40,40,Loam,B,10,Tree cover,note,cite,cite\n"
        "Good,30.7346,79.0669,20,40,40,Loam,B,10,Tree cover,note,cite,cite\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(scr, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        result = scr.estimate_runoff(30.7346, 79.0669, rainfall_mm_hr=20.0, soil_moisture_pct=50.0)
        assert result.curve_number_used is not None  # matched "Good", not skipped entirely
    finally:
        _reset_cache()


def test_snow_or_water_land_cover_returns_honest_not_applicable(tmp_path, monkeypatch):
    csv_path = tmp_path / "inputs.csv"
    _write_fixture_csv(
        csv_path,
        [_row("Vishnuprayag", 30.5, 79.5, hsg="B", wc_code=80, wc_name="Permanent water bodies")],
    )
    monkeypatch.setattr(scr, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        result = scr.estimate_runoff(30.5, 79.5, rainfall_mm_hr=20.0, soil_moisture_pct=50.0)
        assert result.runoff_depth_mm is None
        assert result.curve_number_used is None
        assert result.land_cover == "Permanent water bodies"
        assert "doesn't meaningfully apply" in result.note.lower()
    finally:
        _reset_cache()


def test_amc_class_thresholds():
    assert scr._amc_class_from_soil_moisture(10.0) == "I"
    assert scr._amc_class_from_soil_moisture(29.9) == "I"
    assert scr._amc_class_from_soil_moisture(30.0) == "II"
    assert scr._amc_class_from_soil_moisture(70.0) == "II"
    assert scr._amc_class_from_soil_moisture(70.1) == "III"
    assert scr._amc_class_from_soil_moisture(95.0) == "III"


def test_amc_adjustment_dry_lowers_cn_and_wet_raises_it():
    cn_ii = 70.0
    cn_dry = scr._adjust_cn_for_amc(cn_ii, "I")
    cn_normal = scr._adjust_cn_for_amc(cn_ii, "II")
    cn_wet = scr._adjust_cn_for_amc(cn_ii, "III")
    assert cn_normal == cn_ii
    assert cn_dry < cn_ii < cn_wet


def test_low_rainfall_below_initial_abstraction_gives_zero_runoff(tmp_path, monkeypatch):
    csv_path = tmp_path / "inputs.csv"
    _write_fixture_csv(csv_path, [_row("Kedarnath", 30.7346, 79.0669, hsg="B", wc_code=10)])
    monkeypatch.setattr(scr, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        # CN(B)=60 for Tree cover -> S = 25400/60 - 254 = 169.3mm, Ia = 0.2*S = 33.9mm.
        # A trivial 1mm/hr rainfall for 1 hour is far below Ia.
        result = scr.estimate_runoff(30.7346, 79.0669, rainfall_mm_hr=1.0, soil_moisture_pct=50.0)
        assert result.runoff_depth_mm == 0.0
        assert result.runoff_ratio == 0.0
    finally:
        _reset_cache()


def test_happy_path_heavy_rain_produces_real_positive_runoff(tmp_path, monkeypatch):
    csv_path = tmp_path / "inputs.csv"
    _write_fixture_csv(
        csv_path,
        [_row("Kedarnath", 30.7346, 79.0669, hsg="D", wc_code=60, wc_name="Bare / sparse vegetation")],
    )
    monkeypatch.setattr(scr, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        result = scr.estimate_runoff(30.7346, 79.0669, rainfall_mm_hr=80.0, soil_moisture_pct=85.0)
        assert result.hydrologic_soil_group == "D"
        assert result.land_cover == "Bare / sparse vegetation"
        assert result.amc_class == "III"
        assert result.curve_number_amc2 == 94.0  # bare soil, HSG D
        assert result.curve_number_used is not None and result.curve_number_used >= result.curve_number_amc2
        assert result.rainfall_depth_mm == 80.0  # 1-hour assumed duration
        assert result.runoff_depth_mm is not None and result.runoff_depth_mm > 0.0
        assert 0.0 < result.runoff_ratio <= 1.0
        assert "NRCS TR-55" in result.note
    finally:
        _reset_cache()


def test_real_antecedent_rainfall_drives_amc_instead_of_soil_moisture(tmp_path, monkeypatch):
    """Antecedent-precipitation-index follow-up (user-requested): a REAL
    antecedent-rainfall result must override the soil-moisture-based AMC
    proxy, even when the soil-moisture reading would itself imply a
    different class."""
    csv_path = tmp_path / "inputs.csv"
    _write_fixture_csv(csv_path, [_row("Kedarnath", 30.7346, 79.0669, hsg="D", wc_code=60, wc_name="Bare / sparse vegetation")])
    monkeypatch.setattr(scr, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        real_antecedent = AntecedentRainfallResult(
            p5_mm=5.0, p10_mm=10.0, p20_mm=20.0, as_of_date="2026-08-30",
            amc_class="I", source="real", note="real antecedent test note",
        )
        # soil_moisture_pct=85 would normally classify AMC-III on its own —
        # the real antecedent result (AMC-I) must win instead.
        result = scr.estimate_runoff(30.7346, 79.0669, rainfall_mm_hr=80.0, soil_moisture_pct=85.0, antecedent=real_antecedent)
        assert result.amc_class == "I"
        assert "real antecedent rainfall" in result.note
        assert "5.0mm" in result.note
    finally:
        _reset_cache()


def test_simulated_antecedent_rainfall_does_not_override_soil_moisture_proxy(tmp_path, monkeypatch):
    """A SIMULATED antecedent result (the default when
    GIRIVARSHA_ACTIVE_ANTECEDENT_PROVIDER is left unset) must NOT change
    this module's default output — only a real result is trusted to
    actually improve on the soil-moisture proxy."""
    csv_path = tmp_path / "inputs.csv"
    _write_fixture_csv(csv_path, [_row("Kedarnath", 30.7346, 79.0669, hsg="D", wc_code=60, wc_name="Bare / sparse vegetation")])
    monkeypatch.setattr(scr, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        simulated_antecedent = AntecedentRainfallResult(
            p5_mm=1.0, p10_mm=2.0, p20_mm=3.0, as_of_date="2026-09-07",
            amc_class="I", source="simulated", note="simulated antecedent test note",
        )
        with_antecedent = scr.estimate_runoff(
            30.7346, 79.0669, rainfall_mm_hr=80.0, soil_moisture_pct=85.0, antecedent=simulated_antecedent
        )
        without_antecedent = scr.estimate_runoff(30.7346, 79.0669, rainfall_mm_hr=80.0, soil_moisture_pct=85.0)
        assert with_antecedent.amc_class == without_antecedent.amc_class == "III"
        assert "soil-moisture reading" in with_antecedent.note
    finally:
        _reset_cache()


def test_runoff_never_exceeds_rainfall():
    """Sanity bound on the closed-form SCS-CN equation itself, independent
    of any fixture: Q must never exceed P for any valid CN in (0, 100]."""
    for cn in (30, 50, 70, 90, 98):
        s_mm = (25400 / cn) - 254
        ia_mm = 0.20 * s_mm
        for p_mm in (5.0, 25.0, 100.0, 300.0):
            q_mm = 0.0 if p_mm <= ia_mm else ((p_mm - ia_mm) ** 2) / (p_mm - ia_mm + s_mm)
            assert 0.0 <= q_mm <= p_mm
