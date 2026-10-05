"""
Real antecedent-precipitation-index (API) module — closes the second of the
two remaining recommendations from this project's own competitive-landscape
research pass (docs/Future_Work.md, "Competitive-landscape research"): "A
simple, real antecedent-precipitation-index (API) calculation from actual
historical daily rainfall (rather than the current single-reading
soil-moisture-as-AMC-proxy) would make the SCS-CN AMC classification less
of an approximation."

## What this replaces

`app/services/scs_cn_runoff.py` needs to classify a village's Antecedent
Moisture Condition (AMC I/II/III — how wet the ground already was before
today's storm) as an input to the standard SCS-CN method. The genuine SCS
definition classifies AMC from the REAL 5-day antecedent rainfall total,
not a single current reading — but until now this app had no rainfall
HISTORY to compute that from, so it used the village's current
soil-moisture percentage as an honest, disclosed stand-in.

This module fetches real historical daily rainfall (NASA POWER, the same
free, no-API-key MERRA-2 reanalysis source already proven in this
project's `ml/backfill_real_weather.py`) and computes the actual, standard
5-day antecedent rainfall total — replacing the soil-moisture proxy with
the real thing wherever real data is available.

## A real, disclosed limitation this surfaced: reporting latency

NASA POWER's daily product is not available in near-real-time — testing
this integration found its most recent roughly 1-2 weeks consistently
return the fill value (-999), meaning "not yet processed," not "zero
rain." This module never guesses at those days: it uses the most recent
window of REAL, actually-available daily values, and honestly reports how
many days old that window is (`as_of_date`, with the lag baked into every
`note`). This means the antecedent figure here reflects "the ground's
recent-past wetness as of roughly a week or two ago," not "right now" —
a genuine, disclosed difference from something like SCS-CN's rainfall
input, which does use today's live rate. It is still real, useful signal
for a soil-wetness baseline (soil doesn't dry out in a week), just not a
live nowcast — same "real proxy, honestly labelled" idiom used throughout
this app.

## Two-tier real/simulated, same adapter philosophy as app/providers/base.py

`GIRIVARSHA_ACTIVE_ANTECEDENT_PROVIDER` (default "simulated") controls
this — "simulated" makes zero live network calls (a deterministic,
clearly-labelled synthetic estimate, seeded per village+day so it doesn't
jitter on every request); "real" fetches genuine NASA POWER history,
falling back to the simulated estimate (with the failure disclosed in the
note) if the live fetch fails. This doesn't use the `DataProvider` ABC in
app/providers/base.py directly — that interface returns one scalar
`Reading`, and antecedent classification needs several related numbers
(5/10/20-day sums, the real as-of date, the derived AMC class) — but it
follows the exact same real/simulated/degrade-honestly contract.

## Cached once per village per calendar day, not once per request

NASA POWER's daily data doesn't change within a day at the resolution this
needs, so both the real fetch and the simulated estimate are cached by
`(rounded lat, rounded lon, today's date)` — a village's antecedent window
is computed at most once per calendar day, however many `/risk/map` or
`/risk/{id}` requests come in that day. Unlike the pre-existing
`upstream_rainfall` performance bug (fixed in an earlier follow-up), this
has no N² fan-out — each village looks up only its own coordinate — so no
per-request thread-pool integration was added for it; the accepted
trade-off (disclosed here) is that the FIRST request of a new day, with
the real provider active, pays one live NASA POWER call per distinct
village coordinate not yet cached that day, run sequentially.

## Bonus, using data already fetched: Kanungo & Sharma (2014)'s own real
## antecedent-rainfall thresholds

The same real, peer-reviewed source already cited in
`app/services/rainfall_threshold.py` for its intensity-duration curve also
publishes real 10-day (>=55mm) and 20-day (>=185mm) antecedent-rainfall
thresholds associated with landslide triggering in the Chamoli-Joshimath
region. Since the 10/20-day sums are already computed from the same
fetched daily series, whether each real threshold is met is folded into
this module's `note` as free, disclosed bonus context — not a separate
API field, and (like everything else here) never folded into
`risk_score`/`risk_level`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import httpx

from app.services.rainfall_threshold import SOURCE_CITATION as KANUNGO_SHARMA_CITATION

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_TIMEOUT_SECONDS = 20.0

# Fetch a wide window — NASA POWER's own processing latency (see module
# docstring) means the most recent ~1-2 weeks routinely come back as fill
# values, filtered out below rather than guessed at, so a wide window is
# needed to still find 20 real days of data.
FETCH_WINDOW_DAYS = 35
POWER_FILL_VALUE_THRESHOLD = -900.0  # POWER's own "-999 = no data" convention

# Classic SCS/NRCS 5-day-antecedent-rainfall AMC classification thresholds
# (Chow, Maidment & Mays, "Applied Hydrology" — the same standard hydrology
# textbook already cited in scs_cn_runoff.py's own CN-adjustment formulas),
# in mm, split by season since the real thresholds differ between them.
GROWING_SEASON_MONTHS = frozenset({4, 5, 6, 7, 8, 9, 10})  # April-October
AMC_THRESHOLDS_MM = {
    "growing": (35.6, 53.3),  # AMC I < 35.6mm <= AMC II <= 53.3mm < AMC III
    "dormant": (12.7, 27.9),  # AMC I < 12.7mm <= AMC II <= 27.9mm < AMC III
}
# Disclosed simplification: "growing season" is approximated by calendar
# month (roughly the Indian monsoon + pre/post-monsoon window) rather than
# a real per-region phenological definition — a genuinely defensible
# approximation for this monsoon-driven Himalayan pilot region, not a
# claim of agronomic precision.

KANUNGO_10DAY_THRESHOLD_MM = 55.0
KANUNGO_20DAY_THRESHOLD_MM = 185.0


@dataclass
class AntecedentRainfallResult:
    p5_mm: float | None
    p10_mm: float | None
    p20_mm: float | None
    as_of_date: str | None  # ISO date of the most recent REAL day of data actually used
    amc_class: str | None  # "I" | "II" | "III"
    source: str  # "real" | "simulated"
    note: str


def _amc_class_from_p5(p5_mm: float, on_date: date) -> str:
    season = "growing" if on_date.month in GROWING_SEASON_MONTHS else "dormant"
    low, high = AMC_THRESHOLDS_MM[season]
    if p5_mm < low:
        return "I"
    if p5_mm <= high:
        return "II"
    return "III"


def _season_label(on_date: date) -> str:
    return "growing" if on_date.month in GROWING_SEASON_MONTHS else "dormant"


@lru_cache(maxsize=512)
def _fetch_real_power_daily(lat_r: float, lon_r: float, today_iso: str) -> tuple[tuple[str, float], ...] | None:
    """Real call to NASA POWER, cached per (rounded coordinate, calendar
    day) — see module docstring for why once-per-day is sufficient. Returns
    an ascending-by-date tuple of (iso_date, mm) for every day the API
    actually had real data for (fill values filtered out), or None if the
    request failed outright. `today_iso` is part of the cache key purely to
    invalidate the cache once a new day starts — it is not otherwise used."""
    del today_iso  # cache-key-only, see docstring
    end = date.today()
    start = end - timedelta(days=FETCH_WINDOW_DAYS)
    try:
        resp = httpx.get(
            POWER_URL,
            params={
                "parameters": "PRECTOTCORR",
                "community": "AG",
                "longitude": lon_r,
                "latitude": lat_r,
                "start": start.strftime("%Y%m%d"),
                "end": end.strftime("%Y%m%d"),
                "format": "JSON",
            },
            timeout=POWER_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        payload = resp.json()
        series = payload["properties"]["parameter"]["PRECTOTCORR"]
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None

    clean = sorted(
        (f"{k[:4]}-{k[4:6]}-{k[6:]}", float(v))
        for k, v in series.items()
        if v is not None and v > POWER_FILL_VALUE_THRESHOLD
    )
    if not clean:
        return None
    return tuple(clean)


def _kanungo_note(p10_mm: float, p20_mm: float) -> str:
    meets_10 = p10_mm >= KANUNGO_10DAY_THRESHOLD_MM
    meets_20 = p20_mm >= KANUNGO_20DAY_THRESHOLD_MM
    return (
        f"10-day sum {p10_mm:.1f}mm {'meets or exceeds' if meets_10 else 'is below'} Kanungo & Sharma "
        f"(2014)'s real 10-day antecedent-rainfall threshold ({KANUNGO_10DAY_THRESHOLD_MM:.0f}mm) associated "
        f"with landslide triggering in the Chamoli-Joshimath region; 20-day sum {p20_mm:.1f}mm "
        f"{'meets or exceeds' if meets_20 else 'is below'} its 20-day threshold ({KANUNGO_20DAY_THRESHOLD_MM:.0f}mm)."
    )


def get_real_antecedent_rainfall(lat: float, lon: float) -> AntecedentRainfallResult | None:
    """Real antecedent-rainfall result from live NASA POWER history, or
    None if the live fetch failed or returned no usable real data at all
    (caller degrades to the simulated estimate — see
    get_antecedent_rainfall below)."""
    lat_r, lon_r = round(lat, 3), round(lon, 3)
    daily = _fetch_real_power_daily(lat_r, lon_r, date.today().isoformat())
    if not daily:
        return None

    amounts = [v for _, v in daily]
    as_of = daily[-1][0]
    as_of_date = date.fromisoformat(as_of)
    p5 = sum(amounts[-5:])
    p10 = sum(amounts[-10:])
    p20 = sum(amounts[-20:])
    amc = _amc_class_from_p5(p5, as_of_date)
    lag_days = (date.today() - as_of_date).days
    season = _season_label(as_of_date)

    return AntecedentRainfallResult(
        p5_mm=round(p5, 2),
        p10_mm=round(p10, 2),
        p20_mm=round(p20, 2),
        as_of_date=as_of,
        amc_class=amc,
        source="real",
        note=(
            f"Real NASA POWER (MERRA-2 reanalysis) daily rainfall — most recent real day actually available: "
            f"{as_of} ({lag_days}d ago, due to this source's own processing latency, not today's live rainfall). "
            f"5-day sum {p5:.1f}mm classifies Antecedent Moisture Condition as {amc} ({season}-season thresholds, "
            f"Chow, Maidment & Mays 'Applied Hydrology'). {_kanungo_note(p10, p20)} {KANUNGO_SHARMA_CITATION}"
        ),
    )


@lru_cache(maxsize=512)
def _simulated_antecedent_rainfall_cached(lat_r: float, lon_r: float, today_iso: str) -> AntecedentRainfallResult:
    rng = random.Random(f"{lat_r}:{lon_r}:{today_iso}")
    p5 = round(rng.uniform(0.0, 60.0), 2)
    p10 = round(p5 + rng.uniform(0.0, 60.0), 2)
    p20 = round(p10 + rng.uniform(0.0, 80.0), 2)
    on_date = date.fromisoformat(today_iso)
    amc = _amc_class_from_p5(p5, on_date)
    season = _season_label(on_date)

    return AntecedentRainfallResult(
        p5_mm=p5,
        p10_mm=p10,
        p20_mm=p20,
        as_of_date=today_iso,
        amc_class=amc,
        source="simulated",
        note=(
            f"Simulated antecedent rainfall (no real historical fetch active — set "
            f"GIRIVARSHA_ACTIVE_ANTECEDENT_PROVIDER=real for real NASA POWER history). 5-day sum {p5:.1f}mm "
            f"classifies Antecedent Moisture Condition as {amc} ({season}-season thresholds, simulated input)."
        ),
    )


def get_antecedent_rainfall(lat: float, lon: float, active_provider: str) -> AntecedentRainfallResult:
    """Public entry point — same fallback philosophy as
    app/providers/base.py's get_rainfall_provider/get_soil_provider: an
    unrecognized or "simulated" setting never touches the network; "real"
    tries the live NASA POWER fetch first and degrades honestly (with the
    failure disclosed in the note, not hidden) to the simulated estimate if
    it fails. Never raises — callers get a usable result either way."""
    if active_provider == "real":
        real = get_real_antecedent_rainfall(lat, lon)
        if real is not None:
            return real
        sim = _simulated_antecedent_rainfall_cached(round(lat, 3), round(lon, 3), date.today().isoformat())
        return AntecedentRainfallResult(
            p5_mm=sim.p5_mm,
            p10_mm=sim.p10_mm,
            p20_mm=sim.p20_mm,
            as_of_date=sim.as_of_date,
            amc_class=sim.amc_class,
            source="simulated",
            note=(
                "Real NASA POWER antecedent-rainfall fetch failed or returned no usable real data for this "
                "location — falling back to a clearly-labelled simulated estimate. " + sim.note
            ),
        )
    return _simulated_antecedent_rainfall_cached(round(lat, 3), round(lon, 3), date.today().isoformat())
