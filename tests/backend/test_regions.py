"""
Phase 11 tests: the Region registry (GET /regions) and `?region_id=`
scoping on /villages, /catchments, /risk/map — plus, from the
server-side-region-filtering follow-up (user-requested), the same real
scoping on /sensors and /alerts (previously client-side-only — see
docs/Limitations.md). Needs a running, migrated, seeded Postgres with BOTH
scripts/seed_pilot_region.py and scripts/seed_chamoli_valley.py +
scripts/seed_regions.py already run — same skip-if-no-db pattern as
test_villages.py. The /sensors tests additionally need
scripts/seed_iot_nodes.py to have provisioned the Chamoli fleet — they
skip cleanly (not fail) if it hasn't, same tolerance already used by
test_sensors.py::test_chamoli_sensor_nodes_are_correctly_linked_to_chamoli_villages.
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
except Exception as exc:  # pragma: no cover - e.g. DB configured but not reachable
    _db_available = False
    _skip_reason = f"Database configured but unreachable: {exc}"

pytestmark = pytest.mark.skipif(not _db_available, reason=_skip_reason)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def _regions_by_name():
    r = client.get("/api/v1/regions")
    assert r.status_code == 200
    regions = r.json()
    assert len(regions) >= 2, "region registry must at least hold Mandakini + Chamoli"
    return {reg["name"]: reg for reg in regions}


def test_regions_are_real_and_distinguish_active_from_planned():
    by_name = _regions_by_name()

    assert "Mandakini Valley" in by_name
    assert "Chamoli Disaster Valley" in by_name

    for name in ("Mandakini Valley", "Chamoli Disaster Valley"):
        region = by_name[name]
        assert region["status"] == "active"
        assert region["village_count"] >= 1, f"{name} is marked active but has no villages"
        assert region["catchment_count"] >= 1
        assert region["provenance"], f"{name} is missing its source citation"

    # at least one honestly-unpopulated 'planned' region must exist and must
    # NOT claim village-level coverage it doesn't have
    planned = [reg for reg in by_name.values() if reg["status"] == "planned"]
    assert planned, "registry should list at least one real but not-yet-sourced valley"
    for region in planned:
        assert region["village_count"] == 0
        assert region["provenance"]


def test_region_ids_are_stable_and_distinct():
    by_name = _regions_by_name()
    mandakini_id = by_name["Mandakini Valley"]["id"]
    chamoli_id = by_name["Chamoli Disaster Valley"]["id"]
    assert mandakini_id != chamoli_id


def test_villages_scoped_by_region_id():
    by_name = _regions_by_name()
    chamoli_id = by_name["Chamoli Disaster Valley"]["id"]

    r = client.get(f"/api/v1/villages?region_id={chamoli_id}")
    assert r.status_code == 200
    villages = r.json()
    assert len(villages) >= 1
    names = {v["name"] for v in villages}
    assert "Joshimath" in names
    assert "Kedarnath" not in names, "region filter leaked a Mandakini village into Chamoli"
    for v in villages:
        assert v["region_id"] == chamoli_id
        assert v["region_name"] == "Chamoli Disaster Valley"
        assert v["source"] == "real"


def test_villages_unfiltered_still_returns_everything():
    """No `region_id` query param must keep working exactly as before
    regions existed — every caller written pre-Phase-11 must see no change."""
    all_villages = client.get("/api/v1/villages").json()
    by_name = _regions_by_name()
    mandakini_count = client.get(
        f"/api/v1/villages?region_id={by_name['Mandakini Valley']['id']}"
    ).json()
    chamoli_count = client.get(
        f"/api/v1/villages?region_id={by_name['Chamoli Disaster Valley']['id']}"
    ).json()
    assert len(all_villages) >= len(mandakini_count) + len(chamoli_count)


def test_catchments_scoped_by_region_id():
    by_name = _regions_by_name()
    chamoli_id = by_name["Chamoli Disaster Valley"]["id"]

    r = client.get(f"/api/v1/catchments?region_id={chamoli_id}")
    assert r.status_code == 200
    catchments = r.json()
    assert len(catchments) == 1
    assert catchments[0]["region_id"] == chamoli_id
    assert catchments[0]["region_name"] == "Chamoli Disaster Valley"
    assert "Rishiganga" in catchments[0]["name"]


def test_risk_map_scoped_by_region_id():
    by_name = _regions_by_name()
    chamoli_id = by_name["Chamoli Disaster Valley"]["id"]

    r = client.get(f"/api/v1/risk/map?region_id={chamoli_id}")
    assert r.status_code == 200
    entries = r.json()
    assert len(entries) >= 1
    village_names = {
        v["name"] for v in client.get(f"/api/v1/villages?region_id={chamoli_id}").json()
    }
    assert {e["village_name"] for e in entries} == village_names
    for e in entries:
        assert 0 <= e["risk_score"] <= 100
        assert e["risk_level"].lower() in ("low", "moderate", "high", "critical")


def test_chamoli_historical_event_is_real_and_cited():
    r = client.get("/api/v1/historical-events")
    assert r.status_code == 200
    events = r.json()
    chamoli_events = [e for e in events if "2021" in e["source_citation"] or e.get("severity") == "catastrophic"]
    matches = [e for e in events if "2021_Uttarakhand_flood" in e["source_citation"]]
    assert matches, "the real 7 Feb 2021 Chamoli disaster event must be present with its Wikipedia citation"
    assert any(e["severity"] == "catastrophic" for e in matches)


# ---------------------------------------------------------------------------
# Server-side region filtering follow-up (user-requested): GET /sensors and
# GET /alerts previously had no `?region_id=` of their own — the Authority
# dashboard scoped them client-side against whichever villages the selected
# region's own (already region-scoped) /villages call returned. That worked,
# but left the actual region boundary enforced only in frontend code. Same
# real Sensor/Alert -> Village -> MicroCatchment -> Region join /villages
# and /risk/map already use above.
# ---------------------------------------------------------------------------
def test_sensors_scoped_by_region_id():
    by_name = _regions_by_name()
    chamoli_id = by_name["Chamoli Disaster Valley"]["id"]
    mandakini_id = by_name["Mandakini Valley"]["id"]

    chamoli_sensors = client.get(f"/api/v1/sensors?region_id={chamoli_id}").json()
    if not chamoli_sensors:
        pytest.skip("scripts/seed_iot_nodes.py has not provisioned Chamoli nodes in this checkout")

    chamoli_device_ids = {s["external_device_id"] for s in chamoli_sensors}
    assert all(d.startswith(("esp32-reni-", "esp32-tapovan-", "esp32-vishnuprayag-")) for d in chamoli_device_ids), (
        "region filter must only return real Chamoli devices"
    )
    assert not any(d.startswith("esp32-kedarnath-") for d in chamoli_device_ids), (
        "region filter leaked a Mandakini sensor into Chamoli"
    )

    mandakini_sensors = client.get(f"/api/v1/sensors?region_id={mandakini_id}").json()
    mandakini_device_ids = {s["external_device_id"] for s in mandakini_sensors}
    assert not (chamoli_device_ids & mandakini_device_ids), "a device id appeared in both region-scoped results"
    assert mandakini_device_ids, "expected at least one real Mandakini sensor node"


def test_sensors_unfiltered_still_returns_everything():
    """No `region_id` query param must keep working exactly as before this
    filter existed — every caller written before this follow-up must see
    no change."""
    all_sensors = client.get("/api/v1/sensors").json()
    by_name = _regions_by_name()
    chamoli_count = len(client.get(f"/api/v1/sensors?region_id={by_name['Chamoli Disaster Valley']['id']}").json())
    mandakini_count = len(client.get(f"/api/v1/sensors?region_id={by_name['Mandakini Valley']['id']}").json())
    assert len(all_sensors) >= chamoli_count + mandakini_count


def test_alerts_scoped_by_region_id():
    by_name = _regions_by_name()
    chamoli_id = by_name["Chamoli Disaster Valley"]["id"]
    mandakini_id = by_name["Mandakini Valley"]["id"]

    # GET /risk/map is what actually computes+persists risk and syncs
    # alerts from it — there's no background scheduler — so run it (for
    # every region) before checking scoping, same as test_risk.py's own
    # alert tests do.
    client.get("/api/v1/risk/map")

    chamoli_villages = {v["name"] for v in client.get(f"/api/v1/villages?region_id={chamoli_id}").json()}
    mandakini_villages = {v["name"] for v in client.get(f"/api/v1/villages?region_id={mandakini_id}").json()}

    chamoli_alerts = client.get(f"/api/v1/alerts?region_id={chamoli_id}").json()
    mandakini_alerts = client.get(f"/api/v1/alerts?region_id={mandakini_id}").json()

    # However many alerts happen to be open right now (depends on the
    # current, possibly-simulated, rainfall/soil readings — not something
    # this test controls or should assume a fixed count for), every single
    # one returned under a region filter must belong to a village that is
    # ACTUALLY in that region, and never to a village in the other one.
    for a in chamoli_alerts:
        assert a["village_name"] in chamoli_villages
        assert a["village_name"] not in mandakini_villages
    for a in mandakini_alerts:
        assert a["village_name"] in mandakini_villages
        assert a["village_name"] not in chamoli_villages


def test_alerts_unfiltered_still_returns_everything():
    """No `region_id` query param must keep working exactly as before this
    filter existed — every caller written before this follow-up must see
    no change."""
    client.get("/api/v1/risk/map")
    all_alerts = client.get("/api/v1/alerts").json()
    by_name = _regions_by_name()
    chamoli_count = len(client.get(f"/api/v1/alerts?region_id={by_name['Chamoli Disaster Valley']['id']}").json())
    mandakini_count = len(client.get(f"/api/v1/alerts?region_id={by_name['Mandakini Valley']['id']}").json())
    assert len(all_alerts) >= chamoli_count + mandakini_count
