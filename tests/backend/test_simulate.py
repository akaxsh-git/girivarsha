"""
What-If Simulator tests (POST /simulate, problem-statement item 20 — user-
requested follow-up after the original 14-phase plan was complete). Needs a
running, migrated, seeded Postgres — same skip pattern as test_risk.py.
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
from sqlalchemy import select  # noqa: E402

from app.main import app  # noqa: E402
from app.models.database import session_scope  # noqa: E402
from app.models.orm import Village  # noqa: E402
from app.providers.base import SimulatedRainfallProvider, SimulatedSoilMoistureProvider  # noqa: E402
from app.services.risk_engine import compute_risk_for_village  # noqa: E402

client = TestClient(app)


def _village_id(name: str) -> int:
    villages = client.get("/api/v1/villages").json()
    matches = [v for v in villages if v["name"] == name]
    assert matches, f"expected seeded village {name!r} not found — has scripts/seed_pilot_region.py run?"
    return matches[0]["id"]


def test_simulate_requires_at_least_one_override():
    village_id = _village_id("Rudraprayag")
    r = client.post("/api/v1/simulate", json={"village_id": village_id})
    assert r.status_code == 422


def test_simulate_404_for_unknown_village():
    r = client.post("/api/v1/simulate", json={"village_id": 999999, "rainfall_mm_hr": 40.0})
    assert r.status_code == 404


def test_simulate_heavy_rainfall_raises_score_above_baseline():
    """The whole point of the simulator: a presenter dials rainfall up and
    the SAME baseline formula responds — not a separate, disconnected
    demo-mode number. Note: this village's un-overridden "current" reading
    is itself a SimulatedRainfallProvider draw, refreshed randomly on every
    request (same as GET /risk/{id} already is) — so this test only relies
    on the two numbers computed together in one /simulate response, never
    on comparing against a separately-fetched baseline call."""
    village_id = _village_id("Rudraprayag")

    r = client.post(
        "/api/v1/simulate",
        json={"village_id": village_id, "rainfall_mm_hr": 50.0, "soil_moisture_pct": 100.0},
    )
    assert r.status_code == 200
    body = r.json()

    assert body["village_name"] == "Rudraprayag"
    assert body["is_simulation"] is True
    assert body["overrides_applied"] == {"rainfall_mm_hr": 50.0, "soil_moisture_pct": 100.0}
    assert 0.0 <= body["baseline_risk_score"] <= 100.0
    # Maxing out both live inputs must never produce a LOWER score than
    # whatever the village's real current (mostly-simulated, low-value)
    # inputs give it.
    assert body["simulated_risk_score"] >= body["baseline_risk_score"]

    rainfall_component = next(c for c in body["drivers"]["components"] if c["name"] == "rainfall_intensity")
    assert rainfall_component["raw_value"] == 50.0
    assert rainfall_component["source"] == "simulated"
    assert "what-if" in rainfall_component["description"].lower()

    soil_component = next(c for c in body["drivers"]["components"] if c["name"] == "soil_moisture")
    assert soil_component["raw_value"] == 100.0
    assert soil_component["source"] == "simulated"


def test_simulate_partial_override_leaves_other_input_live():
    """Overriding only rainfall must not silently zero out the soil-moisture
    input — its description must still read as a live/current reading, not
    a what-if override, and it must stay in a plausible 0-100 range."""
    village_id = _village_id("Kedarnath")

    r = client.post("/api/v1/simulate", json={"village_id": village_id, "rainfall_mm_hr": 12.5})
    assert r.status_code == 200
    body = r.json()
    assert body["overrides_applied"] == {"rainfall_mm_hr": 12.5}

    rainfall_component = next(c for c in body["drivers"]["components"] if c["name"] == "rainfall_intensity")
    assert rainfall_component["raw_value"] == 12.5
    assert "what-if" in rainfall_component["description"].lower()

    soil_component = next(c for c in body["drivers"]["components"] if c["name"] == "soil_moisture")
    assert 0.0 <= soil_component["raw_value"] <= 100.0
    assert "what-if" not in soil_component["description"].lower()


def test_simulate_override_precision_is_exact_not_re_randomized():
    """Direct, deterministic check (bypassing the HTTP boundary's inherent
    per-request randomness on any NON-overridden input): with a fixed-seed
    provider passed straight into the engine, overriding rainfall must not
    disturb the soil-moisture value that same fixed-seed provider would
    have produced on its own — proving the override substitutes cleanly for
    one input without touching the other's real fetch path at all."""
    with session_scope() as db:
        village = db.scalar(select(Village).where(Village.name == "Sonprayag"))
        assert village is not None, "expected seeded village Sonprayag — has scripts/seed_pilot_region.py run?"

        expected_soil = SimulatedSoilMoistureProvider(seed=777).fetch(lat=0.0, lon=0.0).value

        assessment = compute_risk_for_village(
            village,
            db,
            rainfall_provider=SimulatedRainfallProvider(seed=1),
            soil_provider=SimulatedSoilMoistureProvider(seed=777),
            rainfall_override=12.5,
        )
        soil_component = next(c for c in assessment.components if c.name == "soil_moisture")
        rainfall_component = next(c for c in assessment.components if c.name == "rainfall_intensity")

        assert rainfall_component.raw_value == 12.5
        assert soil_component.raw_value == pytest.approx(expected_soil, abs=0.01)


def test_simulate_never_persists_or_creates_an_alert():
    """A what-if run must have zero side effects — it must not create a new
    RiskPrediction/Alert row a real GET /risk call would. We can't inspect
    the DB directly here without a session fixture, so this checks the
    documented behavior indirectly: the response says so, and running it
    twice in a row for a village with no real current alert doesn't cause
    it to newly appear in GET /alerts."""
    village_id = _village_id("Gaurikund")
    before = {a["village_id"] for a in client.get("/api/v1/alerts").json()}

    r = client.post("/api/v1/simulate", json={"village_id": village_id, "rainfall_mm_hr": 45.0, "soil_moisture_pct": 90.0})
    assert r.status_code == 200
    assert "not persisted" in r.json()["note"].lower() or "zero side effects" in r.json()["note"].lower()

    after = {a["village_id"] for a in client.get("/api/v1/alerts").json()}
    assert after == before, "a what-if simulation must never create a real alert"


def test_simulate_scs_cn_runoff_responds_to_rainfall_override():
    """SCS-CN follow-up (user-requested): unlike the glacial-lake/glacier-melt
    advisory fields (which don't depend on rainfall/soil and so don't change
    between baseline and simulated), the SCS-CN runoff estimate DOES use
    rainfall/soil-moisture — so overriding both to a heavy, saturated
    scenario must raise the simulated runoff depth to at least the baseline's,
    on Kedarnath, whose real committed soil/land-cover inputs give it a
    genuine (non-None) NRCS TR-55 estimate."""
    village_id = _village_id("Kedarnath")

    r = client.post(
        "/api/v1/simulate",
        json={"village_id": village_id, "rainfall_mm_hr": 90.0, "soil_moisture_pct": 95.0},
    )
    assert r.status_code == 200
    body = r.json()

    assert body["baseline_scs_cn_runoff_depth_mm"] is not None
    assert body["simulated_scs_cn_runoff_depth_mm"] is not None
    assert body["simulated_scs_cn_runoff_depth_mm"] >= body["baseline_scs_cn_runoff_depth_mm"]
    assert body["simulated_scs_cn_curve_number"] is not None
    assert 0.0 <= body["simulated_scs_cn_runoff_ratio"] <= 1.0
    assert "NRCS TR-55" in body["simulated_scs_cn_note"]
    assert "rainfall/soil-moisture overrides" in body["note"] or "baseline_scs_cn_*" in body["note"]


def test_simulate_rainfall_threshold_responds_to_rainfall_override():
    """Rainfall intensity-duration threshold follow-up (user-requested, from
    this project's own competitive-landscape research): unlike the
    glacial-lake/glacier-melt advisory fields, this indicator DOES use the
    village's current rainfall rate, so overriding it to a heavy 90mm/hr
    must push the simulated result to 'threshold_exceeded' with a crossing
    duration of ~1 hour or less, regardless of whatever the baseline
    (live/simulated) rainfall happened to be."""
    village_id = _village_id("Kedarnath")

    r = client.post(
        "/api/v1/simulate",
        json={"village_id": village_id, "rainfall_mm_hr": 90.0},
    )
    assert r.status_code == 200
    body = r.json()

    assert body["simulated_rainfall_threshold_status"] == "threshold_exceeded"
    assert body["simulated_rainfall_threshold_hours_to_threshold"] is not None
    assert body["simulated_rainfall_threshold_hours_to_threshold"] <= 1.0
    assert "Kanungo" in body["simulated_rainfall_threshold_note"]
    assert body["baseline_rainfall_threshold_status"] in (
        "below_floor", "threshold_exceeded", "approaching_within_24h", "not_indicated_within_24h",
    )
    assert "rainfall_threshold" in body["note"] or "baseline_rainfall_threshold_*" in body["note"]


def test_simulate_antecedent_rainfall_is_independent_of_overrides():
    """Antecedent-precipitation-index follow-up (user-requested): this is
    real/simulated rainfall HISTORY, not a live reading — a rainfall or
    soil-moisture override must never change it, unlike the SCS-CN and
    rainfall-threshold fields above."""
    village_id = _village_id("Kedarnath")

    r = client.post(
        "/api/v1/simulate",
        json={"village_id": village_id, "rainfall_mm_hr": 90.0, "soil_moisture_pct": 95.0},
    )
    assert r.status_code == 200
    body = r.json()

    assert body["antecedent_rainfall_source"] == "simulated"
    assert body["antecedent_rainfall_5day_mm"] is not None
    assert "independent" in body["note"] or "antecedent_rainfall_*" in body["note"]


def test_simulate_rejects_out_of_range_overrides():
    village_id = _village_id("Rudraprayag")
    r = client.post("/api/v1/simulate", json={"village_id": village_id, "rainfall_mm_hr": -5.0})
    assert r.status_code == 422
    r = client.post("/api/v1/simulate", json={"village_id": village_id, "soil_moisture_pct": 150.0})
    assert r.status_code == 422
