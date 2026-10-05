"""
Unit tests for app/services/glacial_melt_hazard.py — the real glacier
melt-rate risk-engine component + the disclosed, non-calibrated GLOF
contribution indicator (user-requested follow-up: "incorporate the melting
rate of nearby glaciers into the risk score and how probable a flash flood
is based on nearby glacial data"). Like test_glacial_lake_proximity.py,
these exercise the module directly against a small, controlled fixture CSV
— never the real 1,967-row regional dataset — so results are deterministic
and don't depend on scripts/prepare_glacier_mass_balance_data.py having
been re-run.
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services import glacial_lake_proximity as glp  # noqa: E402
from app.services import glacial_melt_hazard as gmh  # noqa: E402

FIELDNAMES = [
    "glacier_id",
    "lat",
    "lon",
    "area_km2",
    "region",
    "recent_mean_mwe_per_yr",
    "recent_years",
    "prior_mean_mwe_per_yr",
    "prior_years",
    "mass_balance_trend_mwe_per_yr",
    "source_dataset",
    "dataset_citation",
]


def _write_fixture_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _reset_cache():
    gmh._load_glaciers.cache_clear()
    gmh._normalization_bounds.cache_clear()


def _row(glacier_id, lat, lon, recent_mwe, prior_mwe=None, area="0.5", region="South Asia East (RGI region 15)"):
    trend = round(recent_mwe - prior_mwe, 4) if prior_mwe is not None else ""
    return {
        "glacier_id": glacier_id,
        "lat": str(lat),
        "lon": str(lon),
        "area_km2": area,
        "region": region,
        "recent_mean_mwe_per_yr": str(recent_mwe),
        "recent_years": "2021-2025",
        "prior_mean_mwe_per_yr": str(prior_mwe) if prior_mwe is not None else "",
        "prior_years": "2016-2020",
        "mass_balance_trend_mwe_per_yr": str(trend) if trend != "" else "",
        "source_dataset": "test",
        "dataset_citation": "test",
    }


def test_missing_data_file_returns_honest_zero_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(gmh, "DATA_PATH", tmp_path / "does_not_exist.csv")
    _reset_cache()
    try:
        result = gmh.nearest_glacier_melt(30.0, 79.0)
        assert result.distance_km is None
        assert result.nearest_glacier is None
        assert result.normalized_0_1 == 0.0
        assert "not available" in result.note.lower()
    finally:
        _reset_cache()


def test_finds_real_nearest_glacier_and_normalizes_against_the_loaded_range(tmp_path, monkeypatch):
    csv_path = tmp_path / "glaciers.csv"
    # 25 rows so _normalization_bounds() (needs >= 20) computes real percentile
    # bounds rather than falling back to the fixed default range.
    rows = [_row(f"RGI60-15.{i:05d}", 32.0 + i * 0.1, 77.0, -0.3 - i * 0.02, prior_mwe=-0.2) for i in range(23)]
    rows.append(_row("RGI60-15.00100", 30.74, 79.01, -1.5, prior_mwe=-0.5))  # heaviest melt, near Kedarnath
    rows.append(_row("RGI60-15.00200", 30.80, 79.10, -0.05, prior_mwe=-0.05))  # near-stable, also near Kedarnath
    _write_fixture_csv(csv_path, rows)
    monkeypatch.setattr(gmh, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        result = gmh.nearest_glacier_melt(30.7346, 79.0669)  # Kedarnath
        assert result.nearest_glacier is not None
        assert result.nearest_glacier.glacier_id == "RGI60-15.00100"
        assert result.distance_km is not None
        assert 0.0 < result.distance_km < 50.0
        # Heaviest melt in the fixture -> normalized should sit high (closer to 1).
        assert result.normalized_0_1 > 0.7
        assert "accelerating" in result.note.lower()
        assert "not an arbitrary hand-picked cap" in result.note.lower()
    finally:
        _reset_cache()


def test_glacier_beyond_relevant_range_contributes_zero_with_honest_note(tmp_path, monkeypatch):
    csv_path = tmp_path / "glaciers.csv"
    _write_fixture_csv(csv_path, [_row("RGI60-14.99999", 35.0, 76.0, -0.4, prior_mwe=-0.3)])
    monkeypatch.setattr(gmh, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        # Somewhere in the Bay of Bengal, nowhere near the fixture glacier.
        result = gmh.nearest_glacier_melt(15.0, 88.0)
        assert result.distance_km is not None
        assert result.distance_km > gmh.MAX_RELEVANT_DISTANCE_KM
        assert result.normalized_0_1 == 0.0
        assert "beyond" in result.note.lower()
    finally:
        _reset_cache()


def test_malformed_row_is_skipped_not_guessed_at(tmp_path, monkeypatch):
    csv_path = tmp_path / "glaciers.csv"
    csv_path.write_text(
        ",".join(FIELDNAMES) + "\n"
        "RGI60-15.00001,not-a-number,79.0,0.1,South Asia East (RGI region 15),-0.5,2021-2025,-0.4,2016-2020,-0.1,test,test\n"
        "RGI60-15.00002,30.74,79.01,0.1,South Asia East (RGI region 15),-0.5,2021-2025,-0.4,2016-2020,-0.1,test,test\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gmh, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        result = gmh.nearest_glacier_melt(30.7346, 79.0669)
        assert result.nearest_glacier is not None
        assert result.nearest_glacier.glacier_id == "RGI60-15.00002"
    finally:
        _reset_cache()


def test_positive_mass_balance_normalizes_low_not_negative(tmp_path, monkeypatch):
    """A rare growing/surging glacier (positive m w.e./yr) should normalize
    toward 0 (no melt-hazard contribution), never a negative or >1 value."""
    csv_path = tmp_path / "glaciers.csv"
    rows = [_row(f"RGI60-15.{i:05d}", 32.0 + i * 0.1, 77.0, -0.5 - i * 0.05, prior_mwe=-0.3) for i in range(24)]
    rows.append(_row("RGI60-15.00300", 30.74, 79.01, 1.2, prior_mwe=1.0))
    _write_fixture_csv(csv_path, rows)
    monkeypatch.setattr(gmh, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        result = gmh.nearest_glacier_melt(30.7346, 79.0669)
        assert result.nearest_glacier.glacier_id == "RGI60-15.00300"
        assert 0.0 <= result.normalized_0_1 <= 1.0
        assert result.normalized_0_1 < 0.3
    finally:
        _reset_cache()


def test_glof_contribution_indicator_blends_lake_and_melt_data():
    lake = glp.GlacialLakeProximity(
        distance_km=10.0,
        nearest_lake=glp.GlacialLakeRecord(
            lake_id="lake-x", lat=30.7, lon=79.0, area_km2=0.1, elevation_m=4700,
            lake_type="Moraine-dammed lakes", region="Central Himalaya",
        ),
        note="test lake note",
    )
    melt = gmh.GlacierMeltAssessment(
        distance_km=5.0,
        nearest_glacier=gmh.GlacierRecord(
            glacier_id="RGI60-15.00001", lat=30.7, lon=79.0, area_km2=0.5,
            region="South Asia East (RGI region 15)", recent_mean_mwe_per_yr=-1.0,
            recent_years="2021-2025", prior_mean_mwe_per_yr=-0.5, trend_mwe_per_yr=-0.5,
        ),
        normalized_0_1=0.8,
        note="test melt note",
    )
    result = gmh.glof_contribution_indicator(lake, melt)
    assert result.pct is not None
    assert 0.0 <= result.pct <= 100.0
    assert result.tier in ("LOW", "MODERATE", "HIGH")
    assert "not a calibrated statistical probability" in result.note.lower()


def test_glof_contribution_indicator_honestly_none_when_data_missing():
    result = gmh.glof_contribution_indicator(None, None)
    assert result.pct is None
    assert result.tier is None
    assert "not enough real" in result.note.lower()
