"""
Real glacier melt-rate risk-engine component + a disclosed, non-calibrated
"glacial flood contribution indicator" (user-requested follow-up:
"incorporate the melting rate of nearby glaciers into the risk score and
how probable a flash flood is based on nearby glacial data").

Real, coordinate-located data: Dussaillant, I. et al. (2025), "Annual mass
changes for each glacier in the world from 1976 to 2023" (Earth System
Science Data), published via the World Glacier Monitoring Service (WGMS)
as the Annual Mass-Change Estimates product — an update of the widely-
cited Hugonnet et al. (2021, Nature) global glacier elevation-change
methodology. Pre-processed by `scripts/prepare_glacier_mass_balance_data.py`
into `data/derived/real_himalaya_glacier_mass_balance.csv`: 1,967 real,
individually RGI-identified glaciers within 100km of this pilot's seeded
villages, each with a real annual mass-balance time series (1957-2025, in
metres water equivalent/year — negative = ice/snow mass LOSS, i.e.
melting). See docs/Data_Sources.md for the full citation.

## Two deliberately different things this module produces

1. **`glacial_melt_rate` — a genuine 5th weighted risk-engine component**
   (unlike glacial_lake_proximity.py's proximity field, which stays
   advisory-only). This IS folded into `risk_score`, at the user's explicit
   request. The justification is narrower and more defensible than folding
   in raw lake distance would be: a glacier's own recent mass-balance rate
   (how fast it is losing mass RIGHT NOW, averaged over the most recent 5
   real observed years) is a genuine physical indicator of meltwater
   volume available to feed the catchment and of moraine/ice-dam
   instability risk near that glacier — not a proxy on someone else's
   behalf the way raw distance-to-a-lake-of-unknown-attributes is. It is
   still NOT a calibrated, outcome-validated weight (no labelled
   flash-flood dataset exists to fit against — the same honesty gap
   documented throughout this app, e.g. docs/ML_Methodology.md) — the
   weight chosen (see app/core/config.py RiskWeights.glacial_melt_rate) is
   a small, documented, reasoned starting point, not a fitted result.
   Normalization bounds are DERIVED from the actual observed distribution
   of recent mass-balance rates across this loaded regional dataset (5th/
   95th percentile), not an arbitrary hand-picked constant — see
   `_normalization_bounds()`.

2. **A "glacial flood contribution indicator"** (`glof_contribution_pct` /
   `glof_contribution_note`) — a transparent, equally-weighted blend of
   real glacial-lake proximity (glacial_lake_proximity.py) and real glacier
   melt rate (this module), surfaced as an ADVISORY field alongside the
   risk score, same as glacial_lake_distance_km already is. **This is
   deliberately NOT presented as a calibrated statistical probability of a
   flash flood occurring** — there is no real outcome/calibration dataset
   to justify one (same reason glacial_lake_proximity.py itself gives for
   staying advisory), and inventing a precise-looking percentage chance
   would be exactly the kind of fabricated confidence this whole project
   is built to avoid (see docs/ML_Methodology.md's honest false-negative-
   rate framing, and the standing "never overclaim accuracy" rule in
   docs/Limitations.md). It answers the underlying question ("how much of
   the real glacial hazard picture is present near this village") honestly
   as a relative 0-100 indicator, with the calibration gap stated in its
   own note text every time it's returned — never silently as a bare
   number that looks like a probability.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services.glacial_lake_proximity import MAX_RELEVANT_DISTANCE_KM as LAKE_MAX_RELEVANT_DISTANCE_KM
from app.services.glacial_lake_proximity import GlacialLakeProximity, nearest_glacial_lake
from app.services.lead_time import haversine_meters

DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "derived" / "real_himalaya_glacier_mass_balance.csv"

# Matches glacial_lake_proximity.py's own cutoff, for consistency — a
# glacier 300km away isn't a meaningfully "nearby" melt-hazard concern for
# a village-level indicator.
MAX_RELEVANT_DISTANCE_KM = 100.0


@dataclass
class GlacierRecord:
    glacier_id: str
    lat: float
    lon: float
    area_km2: float | None
    region: str
    recent_mean_mwe_per_yr: float
    recent_years: str
    prior_mean_mwe_per_yr: float | None
    trend_mwe_per_yr: float | None


@dataclass
class GlacierMeltAssessment:
    distance_km: float | None
    nearest_glacier: GlacierRecord | None
    normalized_0_1: float
    note: str


@lru_cache(maxsize=1)
def _load_glaciers() -> tuple[GlacierRecord, ...]:
    """Loads the real, pre-processed regional glacier mass-balance dataset
    once per process. Same "degrade honestly, never crash" discipline as
    glacial_lake_proximity._load_lakes(): a missing data file (e.g. a
    checkout that hasn't run scripts/prepare_glacier_mass_balance_data.py)
    returns an empty tuple, not an exception."""
    if not DATA_PATH.exists():
        return ()
    with DATA_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        records = []
        for row in reader:
            try:
                records.append(
                    GlacierRecord(
                        glacier_id=row["glacier_id"],
                        lat=float(row["lat"]),
                        lon=float(row["lon"]),
                        area_km2=float(row["area_km2"]) if row.get("area_km2") else None,
                        region=row.get("region", ""),
                        recent_mean_mwe_per_yr=float(row["recent_mean_mwe_per_yr"]),
                        recent_years=row.get("recent_years", ""),
                        prior_mean_mwe_per_yr=(
                            float(row["prior_mean_mwe_per_yr"]) if row.get("prior_mean_mwe_per_yr") else None
                        ),
                        trend_mwe_per_yr=(
                            float(row["mass_balance_trend_mwe_per_yr"])
                            if row.get("mass_balance_trend_mwe_per_yr")
                            else None
                        ),
                    )
                )
            except (KeyError, ValueError):
                continue  # a malformed row is skipped, never guessed at
        return tuple(records)


@lru_cache(maxsize=1)
def _normalization_bounds() -> tuple[float, float] | None:
    """Real, DERIVED (not hand-picked) normalization bounds: the 5th/95th
    percentile of `recent_mean_mwe_per_yr` across every glacier actually
    loaded from the regional dataset. Returns (floor, ceiling) where floor
    is the more-negative (heavier melt) end. Returns None if too few
    glaciers are loaded to make a percentile meaningful."""
    glaciers = _load_glaciers()
    if len(glaciers) < 20:
        return None
    values = sorted(g.recent_mean_mwe_per_yr for g in glaciers)
    n = len(values)

    def _pct(p: float) -> float:
        idx = min(n - 1, max(0, int(round(p * (n - 1)))))
        return values[idx]

    floor = _pct(0.05)  # most negative 5% — heaviest observed regional melt
    ceiling = _pct(0.95)  # least negative 5% — closest to stable/growing
    return floor, ceiling


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _normalize_melt_rate(mwe_per_yr: float) -> float:
    """More negative (more mass loss) -> closer to 1.0 (higher hazard
    contribution). Bounds come from _normalization_bounds() — the actual
    observed regional distribution, not an arbitrary constant. Falls back
    to a fixed, documented, conservative range if too few glaciers were
    loaded to compute real bounds from."""
    bounds = _normalization_bounds()
    floor, ceiling = bounds if bounds else (-2.0, 0.0)
    if ceiling == floor:
        return 0.5  # degenerate dataset (all identical) — honest midpoint, not a divide-by-zero guess
    return _clamp01((ceiling - mwe_per_yr) / (ceiling - floor))


def nearest_glacier_melt(lat: float, lon: float) -> GlacierMeltAssessment:
    """Real nearest-neighbor search (linear scan — ~2,000 rows, well under a
    millisecond) over the real, regional glacier mass-balance dataset.
    Returns normalized_0_1=0.0 with an honest note (never a fabricated
    'no melt' claim dressed up as a real 0) when the data file is missing
    or nothing real is within MAX_RELEVANT_DISTANCE_KM."""
    glaciers = _load_glaciers()
    if not glaciers:
        return GlacierMeltAssessment(
            distance_km=None,
            nearest_glacier=None,
            normalized_0_1=0.0,
            note=(
                "Glacier mass-balance dataset not available in this environment — run "
                "scripts/prepare_glacier_mass_balance_data.py."
            ),
        )

    best: tuple[float, GlacierRecord] | None = None
    for glacier in glaciers:
        dist_km = haversine_meters(lat, lon, glacier.lat, glacier.lon) / 1000
        if best is None or dist_km < best[0]:
            best = (dist_km, glacier)

    assert best is not None
    dist_km, glacier = best

    if dist_km > MAX_RELEVANT_DISTANCE_KM:
        return GlacierMeltAssessment(
            distance_km=round(dist_km, 2),
            nearest_glacier=glacier,
            normalized_0_1=0.0,
            note=(
                f"Nearest real, RGI-identified glacier ({glacier.glacier_id}, {glacier.region}) is "
                f"{dist_km:.1f} km away — beyond the {MAX_RELEVANT_DISTANCE_KM:.0f} km range this app "
                "treats as a meaningfully nearby melt-hazard concern; contributes 0 to this component."
            ),
        )

    normalized = _normalize_melt_rate(glacier.recent_mean_mwe_per_yr)
    trend_note = ""
    if glacier.trend_mwe_per_yr is not None:
        direction = "accelerating" if glacier.trend_mwe_per_yr < 0 else "slowing"
        trend_note = f", mass loss {direction} vs. the prior 5-year period ({glacier.trend_mwe_per_yr:+.2f} m w.e./yr change)"
    return GlacierMeltAssessment(
        distance_km=round(dist_km, 2),
        nearest_glacier=glacier,
        normalized_0_1=normalized,
        note=(
            f"Nearest real glacier ({glacier.glacier_id}, {glacier.region}) is {dist_km:.1f} km away "
            f"(straight-line), losing mass at a real, observed {glacier.recent_mean_mwe_per_yr:+.2f} "
            f"m water-equivalent/year on average over {glacier.recent_years}{trend_note}. Normalized "
            "against the actual observed range across this regional dataset (5th-95th percentile), "
            "not an arbitrary hand-picked cap — see app/services/glacial_melt_hazard.py."
        ),
    )


@dataclass
class GlofContributionIndicator:
    pct: float | None
    tier: str | None
    note: str


def glof_contribution_indicator(
    lake: GlacialLakeProximity | None, melt: GlacierMeltAssessment | None
) -> GlofContributionIndicator:
    """Combines real glacial-lake proximity + real glacier melt rate into a
    single 0-100 ADVISORY indicator (never folded into risk_score/level —
    same restraint glacial_lake_proximity.py applies to lake distance alone,
    for the same reason: no real outcome/calibration data exists). See this
    module's own docstring for why this is explicitly NOT a statistical
    flash-flood probability."""
    if lake is None or melt is None or lake.distance_km is None or melt.nearest_glacier is None:
        return GlofContributionIndicator(
            pct=None,
            tier=None,
            note=(
                "Not enough real, nearby glacial-lake and/or glacier data to compute a glacial "
                "flood contribution indicator for this village."
            ),
        )

    lake_proximity_factor = _clamp01(1 - (lake.distance_km / LAKE_MAX_RELEVANT_DISTANCE_KM))
    melt_factor = melt.normalized_0_1
    combined = 0.5 * lake_proximity_factor + 0.5 * melt_factor
    pct = round(combined * 100, 1)

    if pct < 33:
        tier = "LOW"
    elif pct < 66:
        tier = "MODERATE"
    else:
        tier = "HIGH"

    return GlofContributionIndicator(
        pct=pct,
        tier=tier,
        note=(
            f"Equal-weighted blend of real glacial-lake proximity ({lake.distance_km:.1f} km to nearest "
            f"mapped lake) and real glacier melt rate ({melt.nearest_glacier.recent_mean_mwe_per_yr:+.2f} "
            f"m w.e./yr at the nearest RGI glacier) — a heuristic 0-100 indicator of how much of the real "
            "glacial hazard context is present nearby, NOT a calibrated statistical probability of a "
            "flash flood occurring. No real outcome dataset exists to calibrate a true probability "
            "against (same limitation documented in docs/ML_Methodology.md) — treat this as relative "
            "context, not a percentage chance. See app/services/glacial_melt_hazard.py's module docstring."
        ),
    )
