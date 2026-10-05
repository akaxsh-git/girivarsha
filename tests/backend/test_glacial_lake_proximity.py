"""
Unit tests for app/services/glacial_lake_proximity.py — the real
glacial-lake-proximity advisory indicator (docs/Future_Work.md follow-up,
user-requested). These do NOT need a database: they exercise the module
directly against a small, controlled fixture CSV (never the real 4,881-row
inventory, so results are deterministic and don't depend on the data prep
script having been re-run).
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services import glacial_lake_proximity as glp  # noqa: E402


def _write_fixture_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = ["lake_id", "lat", "lon", "area_km2", "elevation_m", "lake_type", "region", "source_dataset", "dataset_citation"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _reset_cache():
    glp._load_lakes.cache_clear()


def test_missing_data_file_returns_honest_none_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(glp, "DATA_PATH", tmp_path / "does_not_exist.csv")
    _reset_cache()
    try:
        result = glp.nearest_glacial_lake(30.0, 79.0)
        assert result.distance_km is None
        assert result.nearest_lake is None
        assert "not available" in result.note.lower()
    finally:
        _reset_cache()


def test_finds_real_nearest_lake_among_several(tmp_path, monkeypatch):
    csv_path = tmp_path / "lakes.csv"
    _write_fixture_csv(
        csv_path,
        [
            {
                "lake_id": "lake-near",
                "lat": "30.74",
                "lon": "79.01",
                "area_km2": "0.05",
                "elevation_m": "4700",
                "lake_type": "Unconnected glacial lakes",
                "region": "Central Himalaya",
                "source_dataset": "test",
                "dataset_citation": "test",
            },
            {
                "lake_id": "lake-far",
                "lat": "32.5",
                "lon": "77.0",
                "area_km2": "0.2",
                "elevation_m": "5000",
                "lake_type": "Moraine-dammed lakes",
                "region": "Western Himalaya",
                "source_dataset": "test",
                "dataset_citation": "test",
            },
        ],
    )
    monkeypatch.setattr(glp, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        result = glp.nearest_glacial_lake(30.7346, 79.0669)
        assert result.nearest_lake is not None
        assert result.nearest_lake.lake_id == "lake-near"
        assert result.distance_km is not None
        assert 0.0 < result.distance_km < 50.0
        assert "not a validated glof hazard score" in result.note.lower()
    finally:
        _reset_cache()


def test_lake_beyond_relevant_range_gets_honest_far_away_note(tmp_path, monkeypatch):
    csv_path = tmp_path / "lakes.csv"
    _write_fixture_csv(
        csv_path,
        [
            {
                "lake_id": "lake-distant",
                "lat": "35.0",
                "lon": "76.0",
                "area_km2": "0.1",
                "elevation_m": "5200",
                "lake_type": "Moraine-dammed lakes",
                "region": "Western Himalaya",
                "source_dataset": "test",
                "dataset_citation": "test",
            },
        ],
    )
    monkeypatch.setattr(glp, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        # Somewhere in the Bay of Bengal, nowhere near the fixture lake.
        result = glp.nearest_glacial_lake(15.0, 88.0)
        assert result.distance_km is not None
        assert result.distance_km > glp.MAX_RELEVANT_DISTANCE_KM
        assert "beyond" in result.note.lower()
    finally:
        _reset_cache()


def test_malformed_row_is_skipped_not_guessed_at(tmp_path, monkeypatch):
    csv_path = tmp_path / "lakes.csv"
    csv_path.write_text(
        "lake_id,lat,lon,area_km2,elevation_m,lake_type,region,source_dataset,dataset_citation\n"
        "lake-bad,not-a-number,79.0,0.1,4700,Unconnected glacial lakes,Central Himalaya,test,test\n"
        "lake-good,30.74,79.01,0.05,4700,Unconnected glacial lakes,Central Himalaya,test,test\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(glp, "DATA_PATH", csv_path)
    _reset_cache()
    try:
        result = glp.nearest_glacial_lake(30.7346, 79.0669)
        assert result.nearest_lake is not None
        assert result.nearest_lake.lake_id == "lake-good"
    finally:
        _reset_cache()
