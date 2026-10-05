"""
Phase 12 tests: historical event replay (GET /replay/events,
GET /replay/{event_id}). Needs scripts/seed_event_timelines.py to have
been run alongside the pilot-region seed scripts — same skip-if-no-db
pattern as test_villages.py.
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


def test_replay_events_lists_only_events_with_a_real_seeded_timeline():
    r = client.get("/api/v1/replay/events")
    assert r.status_code == 200
    events = r.json()
    assert len(events) >= 2, "both the 2013 Kedarnath and 2021 Chamoli events should be replayable"
    names = {e["village_name"] for e in events}
    assert {"Kedarnath", "Reni"}.issubset(names)
    for e in events:
        assert e["entry_count"] >= 1


def test_replay_event_returns_ordered_sourced_timeline():
    events = client.get("/api/v1/replay/events").json()
    kedarnath_event = next(e for e in events if e["village_name"] == "Kedarnath")
    r = client.get(f"/api/v1/replay/{kedarnath_event['event_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["village_name"] == "Kedarnath"
    assert len(body["timeline"]) == kedarnath_event["entry_count"]

    # real chronological order (sequence_order strictly increasing)
    orders = [t["sequence_order"] for t in body["timeline"]]
    assert orders == sorted(orders)

    for entry in body["timeline"]:
        assert entry["time_precision"] in ("exact_time", "approximate", "date_only")
        assert entry["source_citation"], "every replay entry must cite a real source — no fabricated timeline"
        assert entry["headline"]


def test_replay_time_precision_is_honest_about_sparse_real_records():
    """The real historical record for these disasters is genuinely sparse
    on exact clock times — this must show up as a mix of precision levels,
    not every entry silently claiming 'exact_time' it doesn't have."""
    events = client.get("/api/v1/replay/events").json()
    chamoli_event = next(e for e in events if e["village_name"] == "Reni")
    body = client.get(f"/api/v1/replay/{chamoli_event['event_id']}").json()
    precisions = {t["time_precision"] for t in body["timeline"]}
    assert "exact_time" in precisions
    assert precisions != {"exact_time"}, "a real disaster with a sparse public record should not claim every moment is exactly timed"


def test_replay_404_for_unknown_event():
    r = client.get("/api/v1/replay/999999")
    assert r.status_code == 404
    assert r.json()["detail"]


def test_replay_ist_sourced_times_are_stored_as_the_correct_utc_instant():
    """Regression check for a real bug caught during this build: Chamoli's
    documented 10:30 IST timestamp must be stored/returned as 05:00 UTC,
    not silently mislabelled as 10:30 UTC (which would misrepresent the
    actual moment by 5.5 hours)."""
    events = client.get("/api/v1/replay/events").json()
    chamoli_event = next(e for e in events if e["village_name"] == "Reni")
    body = client.get(f"/api/v1/replay/{chamoli_event['event_id']}").json()
    tapovan_entry = next(t for t in body["timeline"] if "Tapovan" in t["headline"])
    assert tapovan_entry["time_precision"] == "exact_time"
    assert tapovan_entry["occurred_at"].startswith("2021-02-07T05:00:00")
