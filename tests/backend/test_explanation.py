"""
Phase 9 tests: GET /model/explanation/{village_id} — the real model-agnostic
"why is this village at risk" endpoint. Needs a running, migrated, seeded
Postgres — see test_villages.py's skip pattern.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.models.database import DatabaseNotConfiguredError, get_engine  # noqa: E402

try:
    _engine = get_engine()
    with _engine.connect():
        pass
    _db_available = True
    _skip_reason = ""
except DatabaseNotConfiguredError as exc:
    _db_available = False
    _skip_reason = str(exc)
except Exception as exc:  # pragma: no cover
    _db_available = False
    _skip_reason = f"Database configured but unreachable: {exc}"

pytestmark = pytest.mark.skipif(not _db_available, reason=_skip_reason)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _village_id(name: str) -> int:
    villages = client.get("/api/v1/villages").json()
    matches = [v for v in villages if v["name"] == name]
    assert matches, f"expected seeded village {name!r} not found — has scripts/seed_pilot_region.py run?"
    return matches[0]["id"]


def test_explanation_ranks_real_components_and_sums_shares_to_100():
    village_id = _village_id("Rudraprayag")
    r = client.get(f"/api/v1/model/explanation/{village_id}")
    assert r.status_code == 200
    body = r.json()

    assert body["village_name"] == "Rudraprayag"
    assert "baseline" in body["model_explained"].lower()
    assert "not deployed" in body["caveat"].lower() or "not deployed" in body["caveat"], (
        "the caveat must be explicit that this isn't a SHAP explanation of the undeployed ML layer"
    )

    drivers = body["ranked_drivers"]
    assert len(drivers) == 5
    names = {d["name"] for d in drivers}
    assert names == {
        "rainfall_intensity",
        "soil_moisture",
        "upstream_rainfall",
        "historical_susceptibility",
        "glacial_melt_rate",
    }

    # Ranked descending by contribution.
    contributions = [d["score_contribution"] for d in drivers]
    assert contributions == sorted(contributions, reverse=True)

    total_share = sum(d["share_of_score_pct"] for d in drivers)
    assert abs(total_share - 100.0) < 1.0 or all(c == 0 for c in contributions), (
        "shares should sum to ~100% unless every component contributed zero"
    )

    assert village_id  # summary references the real village name, not a placeholder
    assert "Rudraprayag" in body["summary"]


def test_explanation_404_for_unknown_village():
    r = client.get("/api/v1/model/explanation/999999")
    assert r.status_code == 404
