"""Static checks on the sourced data in scripts/seed_new_regions.py (no DB):
real citations everywhere, valid precision tags, events tied to seeded
villages, and elevations that strictly decrease downstream (the app's
upstream/downstream proxy depends on it)."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

spec = importlib.util.spec_from_file_location("seed_new_regions", ROOT / "scripts" / "seed_new_regions.py")
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

from app.services.rainfall_threshold import assess_rainfall_threshold  # noqa: E402


@pytest.mark.parametrize("c", seed.CATCHMENTS, ids=lambda c: c["name"])
def test_catchment_is_sourced_and_ordered(c):
    villages = c["villages"]
    assert len(villages) >= 4, "Region_Onboarding.md: roughly 3-4+ real villages before 'active'"
    elevations = [v["elevation_m"] for v in villages]
    assert elevations == sorted(elevations, reverse=True) and len(set(elevations)) == len(elevations)
    for v in villages:
        assert "wikipedia.org/wiki/" in v["provenance"]
        assert v["precision"] in {"surveyed", "approximate"}
        assert -90 <= v["lat"] <= 90 and -180 <= v["lon"] <= 180
    names = {v["name"] for v in villages}
    assert c["events"], "each new region has a real cited event"
    for e in c["events"]:
        assert e["village_name"] in names
        assert "wikipedia.org/wiki/" in e["source_citation"]


def test_regions_file_marks_them_active_and_links_catchments():
    spec2 = importlib.util.spec_from_file_location("seed_regions", ROOT / "scripts" / "seed_regions.py")
    regions = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(regions)
    by_catchment = {r["catchment_name"]: r for r in regions.REGIONS if r["catchment_name"]}
    for c in seed.CATCHMENTS:
        assert c["name"] in by_catchment and by_catchment[c["name"]]["status"] == "active"


@pytest.mark.parametrize("region", ["South Lhonak / Teesta Valley", "Jhelum Basin / Kashmir Valley",
                                    "Beas River Basin (Kullu-Manali)"])
def test_garhwal_threshold_is_not_applied_outside_garhwal(region):
    r = assess_rainfall_threshold(25.0, region)
    assert r.status == "not_applicable" and r.applicability == "not_applicable" and r.hours_to_threshold is None


def test_garhwal_regions_unchanged():
    assert assess_rainfall_threshold(0.0, "Chamoli Disaster Valley").applicability == "direct_fit"
    assert assess_rainfall_threshold(0.0, "Mandakini Valley").applicability == "regional_proxy"
    assert assess_rainfall_threshold(0.0, None).applicability == "regional_proxy"
