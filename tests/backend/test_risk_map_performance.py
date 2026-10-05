"""
Performance follow-up (user-requested, diagnosed live on the user's own
machine): GET /risk/map was measured via `time curl` taking ~48s end-to-end
with real providers active. Root-caused to app/services/risk_engine.py's
upstream-rainfall lookup independently re-fetching every upstream sibling
village's rainfall on EVERY village's own computation (no caching), with
every provider call running strictly sequentially. See
risk_engine.prefetch_readings's module-level docstring for the full story
and app/api/routes/risk.py's risk_map() for how it's wired in.

This suite proves, with a fake counting provider (no real network, no
timing assertions — those are inherently flaky in CI), that:
  1. prefetch_readings + the rainfall_cache/soil_cache plumbing actually
     stop the same village from being asked for the same reading twice
     within one request, however many other villages have it as upstream.
  2. Using the cache does not change any computed value versus the
     original uncached path — this is a pure performance/dedup fix, not a
     behavior change.
  3. A real, adjacent bug this investigation also turned up — the upstream
     -village filter not actually restricting to the SAME catchment when a
     pre-fetched village list spanning multiple catchments/regions is
     passed in (exactly what GET /risk/map does since Phase 11's Chamoli
     region) — is fixed: a higher-elevation village from a different
     catchment must never count as "upstream."

Needs a running, migrated, seeded Postgres — same skip pattern as
test_villages.py.
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

from sqlalchemy import select  # noqa: E402

from app.models.database import session_scope  # noqa: E402
from app.models.orm import Village  # noqa: E402
from app.providers.base import DataProvider, DataSource, Reading  # noqa: E402
from app.services.risk_engine import compute_risk_for_village, prefetch_readings  # noqa: E402


class _CountingProvider(DataProvider):
    """A fake, real-shaped provider (never simulated-tagged, so this exactly
    exercises the same code path RealRainfallProvider/RealSoilMoistureProvider
    would) that records every (lat, lon) it's ever asked for, so a test can
    assert exactly how many times fetch() was actually called."""

    name = "counting_test_provider"
    thread_safe = True

    def __init__(self, base_value: float = 10.0) -> None:
        self.calls: list[tuple[float, float]] = []
        self._base_value = base_value

    def fetch(self, *, lat: float, lon: float) -> Reading:
        self.calls.append((lat, lon))
        return Reading(value=self._base_value, unit="mm/hr", source=DataSource.REAL, provider_name=self.name)


def _mandakini_villages():
    with session_scope() as db:
        villages = db.scalars(
            select(Village).where(Village.catchment_id.is_not(None))
        ).all()
        assert len(villages) >= 5, "expected the seeded pilot region's villages"
        db.expunge_all()
        return villages


def test_prefetch_readings_fetches_each_village_at_most_once():
    """The actual bug: without prefetch_readings, a 6-village catchment did
    ~27 rainfall provider calls (each upstream lookup re-fetching every
    upstream sibling independently). With it, each village is asked for its
    reading at most once, however many downstream villages need it. Uses
    two SEPARATE counting providers (rainfall vs. soil) so each one's call
    count can be checked against the village count on its own — a single
    shared provider's combined count would double-book both reading kinds
    together and hide a regression in either one."""
    villages = _mandakini_villages()
    rainfall_provider = _CountingProvider(base_value=10.0)
    soil_provider = _CountingProvider(base_value=40.0)

    with session_scope() as db:
        rainfall_cache, soil_cache = prefetch_readings(rainfall_provider, soil_provider, villages, db)

    assert len(rainfall_provider.calls) <= len(villages), (
        f"expected at most one rainfall provider call per village ({len(villages)}), "
        f"got {len(rainfall_provider.calls)} — prefetch_readings should dedupe, not just "
        "parallelize, the redundant upstream re-fetches"
    )
    assert len(soil_provider.calls) <= len(villages), (
        f"expected at most one soil provider call per village ({len(villages)}), got {len(soil_provider.calls)}"
    )
    # every village must have resolved to SOMETHING (a real sensor override
    # for a village that has one, this fake provider's reading otherwise)
    assert all(v.id in rainfall_cache for v in villages)
    assert all(v.id in soil_cache for v in villages)


def test_cached_and_uncached_paths_agree_on_the_computed_score():
    """Using rainfall_cache/soil_cache must be a pure performance change —
    the computed risk score, level, and confidence must be identical to the
    original uncached path for the same inputs."""
    villages = _mandakini_villages()
    target = next(v for v in villages if v.name == "Rudraprayag")

    provider = _CountingProvider(base_value=12.5)

    with session_scope() as db:
        uncached = compute_risk_for_village(
            target, db, rainfall_provider=provider, soil_provider=provider, all_villages_in_catchment=villages
        )

    with session_scope() as db:
        rainfall_cache, soil_cache = prefetch_readings(provider, provider, villages, db)
        cached = compute_risk_for_village(
            target,
            db,
            rainfall_provider=provider,
            soil_provider=provider,
            all_villages_in_catchment=villages,
            rainfall_cache=rainfall_cache,
            soil_cache=soil_cache,
        )

    assert cached.score == uncached.score
    assert cached.level == uncached.level
    assert cached.confidence_pct == uncached.confidence_pct


def test_upstream_lookup_ignores_villages_from_a_different_catchment():
    """Real bug found via this investigation: passing a village list that
    spans MULTIPLE catchments (exactly what GET /risk/map does) must never
    let a higher-elevation village from a different river system count as
    'upstream' of this one."""
    with session_scope() as db:
        all_villages = db.scalars(select(Village).where(Village.catchment_id.is_not(None))).all()
        catchment_ids = {v.catchment_id for v in all_villages}
        if len(catchment_ids) < 2:
            pytest.skip("needs at least 2 seeded catchments (Mandakini + Chamoli, Phase 11) to exercise this")

        # The lowest-elevation village in ITS OWN catchment, but with at
        # least one higher-elevation village that belongs to a DIFFERENT
        # catchment somewhere in the full list.
        by_catchment: dict[int, list[Village]] = {}
        for v in all_villages:
            by_catchment.setdefault(v.catchment_id, []).append(v)

        target = None
        for cid, vs in by_catchment.items():
            candidate = min(vs, key=lambda v: v.elevation_m or 0)
            other_catchment_has_higher = any(
                (ov.elevation_m or 0) > (candidate.elevation_m or 0)
                for ocid, ovs in by_catchment.items() if ocid != cid
                for ov in ovs
            )
            if other_catchment_has_higher:
                target = candidate
                break
        assert target is not None, "expected some cross-catchment elevation overlap in the seeded regions"

        assessment = compute_risk_for_village(target, db, all_villages_in_catchment=all_villages)
        upstream = next(c for c in assessment.components if c.name == "upstream_rainfall")

        same_catchment_upstream_count = sum(
            1
            for v in by_catchment[target.catchment_id]
            if v.id != target.id and (v.elevation_m or 0) > (target.elevation_m or 0)
        )
        if same_catchment_upstream_count == 0:
            assert "no upstream" in upstream.description.lower()
        else:
            assert str(same_catchment_upstream_count) in upstream.description
