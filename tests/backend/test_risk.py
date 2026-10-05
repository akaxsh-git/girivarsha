"""
Phase 4 tests: the real, transparent baseline risk engine and the alerts it
generates. Needs a running, migrated, seeded Postgres — see
test_villages.py's skip pattern (same reasoning: skip cleanly, don't fail
confusingly, if no DB is configured).
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

from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

# Real bug found via the SCS-CN integration pass: this test's confidence
# ceiling assumed every input is always simulated/derived, but this app has
# always supported an opt-in "real" weather provider mode (see README.md
# "Real weather data") that GENUINELY raises confidence toward ~70-90% —
# that's the feature working as documented, not a regression. A machine
# with GIRIVARSHA_ACTIVE_RAINFALL_PROVIDER=real / GIRIVARSHA_ACTIVE_SOIL_
# PROVIDER=real set (as recommended for local verification) would fail this
# assertion every single run without this check, for a reason that has
# nothing to do with whatever else is being tested. Read the actual active
# config instead of hardcoding an assumption that only holds for one of the
# two supported configurations.
_settings = get_settings()
_ANY_REAL_PROVIDER_ACTIVE = "real" in (
    _settings.active_rainfall_provider,
    _settings.active_soil_provider,
)
_CONFIDENCE_CEILING = 95.0 if _ANY_REAL_PROVIDER_ACTIVE else 70.0


def _village_id(name: str) -> int:
    villages = client.get("/api/v1/villages").json()
    matches = [v for v in villages if v["name"] == name]
    assert matches, f"expected seeded village {name!r} not found — has scripts/seed_pilot_region.py run?"
    return matches[0]["id"]


def test_risk_map_scores_every_village_transparently():
    r = client.get("/api/v1/risk/map")
    assert r.status_code == 200
    entries = r.json()
    villages = client.get("/api/v1/villages").json()
    assert len(entries) == len(villages)

    for e in entries:
        assert 0.0 <= e["risk_score"] <= 100.0
        assert e["risk_level"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")
        assert 0.0 <= e["confidence_pct"] <= 100.0
        # Nothing here is a trained/validated model yet — confidence must
        # never claim more certainty than whichever inputs are ACTUALLY
        # active right now support (see _CONFIDENCE_CEILING above).
        assert e["confidence_pct"] < _CONFIDENCE_CEILING, (
            "confidence should stay honestly capped given the currently active provider config "
            f"(real weather provider active: {_ANY_REAL_PROVIDER_ACTIVE})"
        )
        # Phase 10: /risk/map now also carries each village's lead-time
        # estimate (int minutes, or honestly None for a catchment-source
        # village) — no separate per-village call needed to build an
        # aggregate stat from it.
        assert e["lead_time_minutes"] is None or (isinstance(e["lead_time_minutes"], int) and e["lead_time_minutes"] > 0)
        # Glacial-lake-proximity follow-up: a real, advisory-only distance to
        # the nearest mapped glacial lake — never negative, honestly None
        # only if the (committed) lake inventory file is somehow missing.
        assert e["glacial_lake_distance_km"] is None or e["glacial_lake_distance_km"] >= 0.0
        # Glacier-melt-rate follow-up: the advisory GLOF contribution
        # indicator is a 0-100 heuristic, never negative/over 100, honestly
        # None only if the committed glacier dataset is somehow missing.
        assert e["glof_contribution_pct"] is None or 0.0 <= e["glof_contribution_pct"] <= 100.0
        assert e["glof_contribution_tier"] in (None, "LOW", "MODERATE", "HIGH")
        # SCS-CN rainfall-runoff follow-up: a real, independent runoff-depth
        # estimate shown alongside (never folded into) risk_score — honestly
        # None only for a village whose land cover is snow/ice or open water,
        # or if the committed soil/land-cover dataset is somehow missing.
        assert e["scs_cn_runoff_depth_mm"] is None or e["scs_cn_runoff_depth_mm"] >= 0.0
        assert e["scs_cn_curve_number"] is None or 0.0 < e["scs_cn_curve_number"] <= 100.0
        # Rainfall intensity-duration threshold follow-up: a real, formula-
        # based indicator — hours_to_threshold is either None (rainfall below
        # the study's own floor) or a positive number of hours.
        # Rounds to 0.00 for a very high intensity (the crossing duration is
        # a tiny fraction of an hour) — >= 0, not strictly > 0.
        assert e["rainfall_threshold_hours_to_threshold"] is None or e["rainfall_threshold_hours_to_threshold"] >= 0.0
        assert e["rainfall_threshold_status"] in (
            None,
            "below_floor",
            "threshold_exceeded",
            "approaching_within_24h",
            "not_indicated_within_24h",
        )
        # Antecedent-precipitation-index follow-up: always present (real or
        # simulated), never negative.
        assert e["antecedent_rainfall_5day_mm"] is None or e["antecedent_rainfall_5day_mm"] >= 0.0
        assert e["antecedent_rainfall_source"] in (None, "real", "simulated")


def test_risk_detail_gives_a_transparent_component_breakdown():
    village_id = _village_id("Rudraprayag")
    r = client.get(f"/api/v1/risk/{village_id}")
    assert r.status_code == 200
    body = r.json()

    assert body["village_name"] == "Rudraprayag"
    assert body["model_version"] == "baseline-v1"
    # Phase 10: Rudraprayag is the catchment outlet, so it DOES have an
    # upstream village to estimate propagation time from — a real (if
    # prototype-precision) number, not a placeholder. See
    # test_kedarnath_source_village_has_no_lead_time_estimate below for the
    # one seeded village that honestly stays None.
    assert isinstance(body["lead_time_minutes"], int)
    assert body["lead_time_minutes"] > 0
    assert "straight-line distance" in body["lead_time_note"].lower()

    components = body["drivers"]["components"]
    names = {c["name"] for c in components}
    assert names == {
        "rainfall_intensity",
        "soil_moisture",
        "upstream_rainfall",
        "historical_susceptibility",
        "glacial_melt_rate",
    }
    for c in components:
        assert c["source"] in ("real", "simulated", "derived")
        assert "raw_value" in c and "weight" in c and "score_contribution" in c

    weight_sum = sum(c["weight"] for c in components)
    assert abs(weight_sum - 1.0) < 1e-6

    # Glacier-melt-rate follow-up (user-requested): a real, RGI-identified
    # nearby glacier's own weighted component, normalized 0-1, plus the
    # advisory (never score-affecting) GLOF contribution indicator.
    assert body["glof_contribution_pct"] is None or 0.0 <= body["glof_contribution_pct"] <= 100.0
    assert body["glof_contribution_tier"] in (None, "LOW", "MODERATE", "HIGH")

    # SCS-CN rainfall-runoff follow-up (user-requested): a real, independent
    # NRCS TR-55 runoff estimate, never folded into the weighted components
    # above — it's a sibling field, same discipline as the glacial-lake one.
    assert "scs_cn_runoff_depth_mm" not in names and "scs_cn" not in names
    assert body["scs_cn_curve_number"] is None or 0.0 < body["scs_cn_curve_number"] <= 100.0
    assert body["scs_cn_amc_class"] in (None, "I", "II", "III")
    assert body["scs_cn_hydrologic_soil_group"] in (None, "A", "B", "C", "D")
    assert body["scs_cn_runoff_depth_mm"] is None or body["scs_cn_runoff_depth_mm"] >= 0.0
    assert body["scs_cn_runoff_ratio"] is None or 0.0 <= body["scs_cn_runoff_ratio"] <= 1.0

    # Rainfall intensity-duration threshold follow-up (user-requested, from
    # this project's own competitive-landscape research): a real, third
    # independent indicator, never folded into the weighted components above.
    assert "rainfall_threshold" not in names
    assert body["rainfall_threshold_status"] in (
        "below_floor", "threshold_exceeded", "approaching_within_24h", "not_indicated_within_24h",
    )
    assert body["rainfall_threshold_applicability"] in ("direct_fit", "regional_proxy")
    assert "Kanungo" in body["rainfall_threshold_note"]


def test_kedarnath_source_village_has_no_lead_time_estimate():
    """Kedarnath is the catchment's highest-elevation (source) village — see
    test_upstream_village_has_no_upstream_contribution below for the same
    reasoning applied to the risk score's own upstream_rainfall component.
    Phase 10's lead-time estimate must stay honestly None here too, never a
    fabricated number for a village with nothing upstream of it."""
    village_id = _village_id("Kedarnath")
    body = client.get(f"/api/v1/risk/{village_id}").json()
    assert body["lead_time_minutes"] is None
    assert "no upstream" in body["lead_time_note"].lower()


def test_upstream_village_has_no_upstream_contribution():
    """Kedarnath is the highest-elevation seeded village (the catchment's
    real source) — it has nothing upstream of it in this pilot region, and
    the engine must say so rather than inventing a value."""
    village_id = _village_id("Kedarnath")
    body = client.get(f"/api/v1/risk/{village_id}").json()
    upstream = next(c for c in body["drivers"]["components"] if c["name"] == "upstream_rainfall")
    assert upstream["raw_value"] == 0.0
    assert "no upstream" in upstream["description"].lower()


def test_downstream_village_does_consider_upstream_villages():
    """Rudraprayag is the outlet — every other seeded village is upstream of
    it, so the engine's upstream component must actually be looking at
    other villages, not just echoing 'none' for everyone."""
    village_id = _village_id("Rudraprayag")
    body = client.get(f"/api/v1/risk/{village_id}").json()
    upstream = next(c for c in body["drivers"]["components"] if c["name"] == "upstream_rainfall")
    assert "no upstream" not in upstream["description"].lower()


def test_risk_detail_includes_glacial_lake_advisory_field():
    """Glacial-lake-proximity follow-up (docs/Future_Work.md, user-requested):
    a real distance to the nearest satellite-mapped glacial lake, exposed as
    advisory context next to the score — never folded into risk_score/level
    itself. Kedarnath sits close to real, mapped high-altitude lakes in the
    source dataset, so this must resolve to a real number, not None."""
    village_id = _village_id("Kedarnath")
    body = client.get(f"/api/v1/risk/{village_id}").json()
    assert body["glacial_lake_distance_km"] is not None
    assert body["glacial_lake_distance_km"] >= 0.0
    assert "glacial lake" in body["glacial_lake_note"].lower()
    # The note itself must say this is advisory, not a scored component —
    # the whole point of this field per the module's own docstring.
    assert "not" in body["glacial_lake_note"].lower()
    # Must never be folded into the score's own driver breakdown — it's a
    # sibling field on the response, not a 5th weighted component.
    driver_names = {c["name"] for c in body["drivers"]["components"]}
    assert "glacial_lake" not in driver_names and "glacial_lake_proximity" not in driver_names


def test_risk_detail_includes_real_scs_cn_runoff_estimate():
    """SCS-CN follow-up (user-requested, from competitive-landscape research:
    "a real SCS-CN rainfall-runoff layer... would be the highest-value next
    addition"). Kedarnath has real committed soil/land-cover inputs
    (data/derived/real_village_scs_cn_inputs.csv) and its land cover isn't
    snow/ice or open water, so this must resolve to a real, non-None
    NRCS TR-55 estimate — not a placeholder."""
    village_id = _village_id("Kedarnath")
    body = client.get(f"/api/v1/risk/{village_id}").json()
    assert body["scs_cn_curve_number"] is not None
    assert 0.0 < body["scs_cn_curve_number"] <= 100.0
    assert body["scs_cn_amc_class"] in ("I", "II", "III")
    assert body["scs_cn_hydrologic_soil_group"] in ("A", "B", "C", "D")
    assert body["scs_cn_runoff_depth_mm"] is not None
    assert body["scs_cn_runoff_depth_mm"] >= 0.0
    assert "NRCS TR-55" in body["scs_cn_note"]
    # Must never be folded into the score's own driver breakdown — same
    # "sibling field, not a 6th weighted component" discipline as the
    # glacial-lake advisory field above.
    driver_names = {c["name"] for c in body["drivers"]["components"]}
    assert not any("scs_cn" in n or n == "runoff" for n in driver_names)


def test_risk_detail_includes_antecedent_rainfall_index():
    """Antecedent-precipitation-index follow-up (user-requested, from this
    project's own competitive-landscape research): a real/simulated
    5/10/20-day antecedent rainfall figure now feeds the SCS-CN AMC
    classification. In this test environment GIRIVARSHA_ACTIVE_ANTECEDENT_
    PROVIDER is left at its default 'simulated', so the field must be
    present and self-consistent but never claim to be real."""
    village_id = _village_id("Kedarnath")
    body = client.get(f"/api/v1/risk/{village_id}").json()
    assert body["antecedent_rainfall_5day_mm"] is not None
    assert body["antecedent_rainfall_5day_mm"] >= 0.0
    assert body["antecedent_rainfall_source"] == "simulated"
    assert "simulated" in body["antecedent_rainfall_note"].lower()
    # A simulated antecedent result must NOT silently change the pre-
    # existing soil-moisture-proxy AMC behavior — see scs_cn_runoff.py.
    assert "soil-moisture reading" in body["scs_cn_note"]


def test_rainfall_threshold_is_a_direct_fit_for_chamoli_villages():
    """The real source study (Kanungo & Sharma 2014) IS the Chamoli-
    Joshimath region — a Chamoli Disaster Valley village must be disclosed
    as a direct fit, not a regional proxy."""
    village_id = _village_id("Reni")
    body = client.get(f"/api/v1/risk/{village_id}").json()
    assert body["rainfall_threshold_applicability"] == "direct_fit"
    assert "direct fit" in body["rainfall_threshold_note"]


def test_rainfall_threshold_is_a_regional_proxy_for_mandakini_villages():
    """The Mandakini valley is a different catchment from the study's own
    Chamoli-Joshimath area — must be honestly disclosed as a proxy, never
    silently presented as if the study covered it directly."""
    village_id = _village_id("Kedarnath")
    body = client.get(f"/api/v1/risk/{village_id}").json()
    assert body["rainfall_threshold_applicability"] == "regional_proxy"
    assert "regional proxy" in body["rainfall_threshold_note"]
    assert "not the study's own" in body["rainfall_threshold_note"]


def test_risk_404_for_unknown_village():
    r = client.get("/api/v1/risk/999999")
    assert r.status_code == 404


def test_alerts_only_lists_open_yellow_and_above_never_green():
    # Populate risk_predictions/alerts first — there's no background
    # scheduler yet (Phase 8+), so alerts only exist after a /risk call.
    client.get("/api/v1/risk/map")
    r = client.get("/api/v1/alerts")
    assert r.status_code == 200
    for a in r.json():
        assert a["level"] in ("YELLOW", "ORANGE", "RED"), "GREEN/no-risk villages must never appear as an alert"
        assert a["resolved_at"] is None
        assert "prototype" in a["message"].lower(), "every alert must carry the non-official-warning disclaimer"
