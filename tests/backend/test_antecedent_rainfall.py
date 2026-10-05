"""
Unit tests for app/services/antecedent_rainfall.py — the real
antecedent-precipitation-index (API) module (user-requested follow-up,
from this project's own competitive-landscape research). Mocks
`httpx.get` rather than making live network calls, so these run offline
and deterministically, same discipline as test_road_network.py.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services import antecedent_rainfall as ar  # noqa: E402


def _clear_caches():
    ar._fetch_real_power_daily.cache_clear()
    ar._simulated_antecedent_rainfall_cached.cache_clear()


@pytest.fixture(autouse=True)
def _reset():
    _clear_caches()
    yield
    _clear_caches()


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._payload


def _power_payload(daily_mm: dict[str, float]) -> dict:
    return {"properties": {"parameter": {"PRECTOTCORR": daily_mm}}}


def _synthetic_series(as_of: date, values: list[float]) -> dict[str, float]:
    """Builds a POWER-shaped daily series ending at `as_of`, with the given
    real values (most recent last), plus a run of -999 fill-value days
    after it (simulating the source's own reporting latency) up through
    today — matching the real shape observed from the live API."""
    series: dict[str, float] = {}
    start = as_of - timedelta(days=len(values) - 1)
    for i, v in enumerate(values):
        d = start + timedelta(days=i)
        series[d.strftime("%Y%m%d")] = v
    gap_day = as_of + timedelta(days=1)
    while gap_day <= date.today():
        series[gap_day.strftime("%Y%m%d")] = -999.0
        gap_day += timedelta(days=1)
    return series


def test_real_fetch_computes_5_10_20_day_sums_from_the_most_recent_real_data(monkeypatch):
    as_of = date.today() - timedelta(days=8)
    # 20 real days of data ending 8 days ago (simulating NASA POWER's own
    # real reporting lag), each 2.0mm — so P5=10, P10=20, P20=40.
    values = [2.0] * 20
    payload = _power_payload(_synthetic_series(as_of, values))

    monkeypatch.setattr(ar.httpx, "get", lambda *a, **k: _FakeResponse(payload))

    result = ar.get_real_antecedent_rainfall(30.7346, 79.0669)
    assert result is not None
    assert result.source == "real"
    assert result.as_of_date == as_of.isoformat()
    assert result.p5_mm == pytest.approx(10.0)
    assert result.p10_mm == pytest.approx(20.0)
    assert result.p20_mm == pytest.approx(40.0)
    assert f"{(date.today() - as_of).days}d ago" in result.note
    assert "Kanungo" in result.note


def test_real_fetch_reports_the_true_reporting_lag_honestly(monkeypatch):
    """The most recent real day must be reported plainly, including how
    many days old it is — never presented as if it were today's rainfall."""
    as_of = date.today() - timedelta(days=10)
    payload = _power_payload(_synthetic_series(as_of, [1.0] * 5))
    monkeypatch.setattr(ar.httpx, "get", lambda *a, **k: _FakeResponse(payload))

    result = ar.get_real_antecedent_rainfall(30.0, 79.0)
    assert result is not None
    assert result.as_of_date != date.today().isoformat()
    assert "processing latency" in result.note


def test_amc_classification_thresholds_growing_season():
    growing_date = date(2026, 7, 15)  # July -> growing season
    assert ar._amc_class_from_p5(10.0, growing_date) == "I"
    assert ar._amc_class_from_p5(40.0, growing_date) == "II"
    assert ar._amc_class_from_p5(60.0, growing_date) == "III"


def test_amc_classification_thresholds_dormant_season():
    dormant_date = date(2026, 1, 15)  # January -> dormant season
    assert ar._amc_class_from_p5(5.0, dormant_date) == "I"
    assert ar._amc_class_from_p5(20.0, dormant_date) == "II"
    assert ar._amc_class_from_p5(30.0, dormant_date) == "III"


def test_kanungo_sharma_thresholds_are_disclosed_in_the_note(monkeypatch):
    as_of = date.today() - timedelta(days=8)
    # 20 real days at 10mm each: P10=100 (>=55 threshold), P20=200 (>=185 threshold).
    payload = _power_payload(_synthetic_series(as_of, [10.0] * 20))
    monkeypatch.setattr(ar.httpx, "get", lambda *a, **k: _FakeResponse(payload))

    result = ar.get_real_antecedent_rainfall(30.7346, 79.0669)
    assert result is not None
    assert "meets or exceeds Kanungo" in result.note
    assert "10.1007/s10346-013-0438-9" in result.note


def test_real_fetch_returns_none_on_http_error(monkeypatch):
    def _raise(*a, **k):
        raise ar.httpx.ConnectError("connection refused")

    monkeypatch.setattr(ar.httpx, "get", _raise)
    assert ar.get_real_antecedent_rainfall(30.0, 79.0) is None


def test_real_fetch_returns_none_when_every_day_is_a_fill_value(monkeypatch):
    payload = _power_payload({"20260901": -999.0, "20260902": -999.0})
    monkeypatch.setattr(ar.httpx, "get", lambda *a, **k: _FakeResponse(payload))
    assert ar.get_real_antecedent_rainfall(30.0, 79.0) is None


def test_get_antecedent_rainfall_defaults_to_simulated_with_no_network_call(monkeypatch):
    def _fail(*a, **k):
        raise AssertionError("simulated mode must never call the network")

    monkeypatch.setattr(ar.httpx, "get", _fail)
    result = ar.get_antecedent_rainfall(30.7346, 79.0669, "simulated")
    assert result.source == "simulated"
    assert result.amc_class in ("I", "II", "III")
    assert "GIRIVARSHA_ACTIVE_ANTECEDENT_PROVIDER=real" in result.note


def test_get_antecedent_rainfall_simulated_estimate_is_stable_within_a_day():
    a = ar.get_antecedent_rainfall(30.7346, 79.0669, "simulated")
    b = ar.get_antecedent_rainfall(30.7346, 79.0669, "simulated")
    assert a.p5_mm == b.p5_mm
    assert a.p10_mm == b.p10_mm
    assert a.p20_mm == b.p20_mm


def test_get_antecedent_rainfall_real_mode_falls_back_honestly_on_failure(monkeypatch):
    def _raise(*a, **k):
        raise ar.httpx.ConnectError("connection refused")

    monkeypatch.setattr(ar.httpx, "get", _raise)
    result = ar.get_antecedent_rainfall(30.7346, 79.0669, "real")
    assert result.source == "simulated"
    assert "fetch failed or returned no usable real data" in result.note


def test_get_antecedent_rainfall_real_mode_uses_real_data_on_success(monkeypatch):
    as_of = date.today() - timedelta(days=8)
    payload = _power_payload(_synthetic_series(as_of, [3.0] * 20))
    monkeypatch.setattr(ar.httpx, "get", lambda *a, **k: _FakeResponse(payload))

    result = ar.get_antecedent_rainfall(30.7346, 79.0669, "real")
    assert result.source == "real"
    assert result.p5_mm == pytest.approx(15.0)


def test_real_fetch_is_cached_once_per_coordinate_per_day(monkeypatch):
    as_of = date.today() - timedelta(days=8)
    payload = _power_payload(_synthetic_series(as_of, [2.0] * 20))
    call_count = {"n": 0}

    def _get(*a, **k):
        call_count["n"] += 1
        return _FakeResponse(payload)

    monkeypatch.setattr(ar.httpx, "get", _get)
    ar.get_real_antecedent_rainfall(30.7346, 79.0669)
    ar.get_real_antecedent_rainfall(30.7346, 79.0669)
    ar.get_real_antecedent_rainfall(30.7346, 79.0669)
    assert call_count["n"] == 1
