"""
Real SCS-CN (Soil Conservation Service Curve Number) rainfall-runoff
estimate — a SEPARATE, physically-grounded second score shown ALONGSIDE the
Phase 4 weighted baseline, not folded into it and not replacing it.
User-requested follow-up, from a competitive-landscape research pass
comparing this project against real flash-flood systems worldwide: every
operational/research system found (GLOFAS/EFAS's LISFLOOD, Google Flood
Hub's LSTM, even the simplest rule-based Flash Flood Guidance systems) is
anchored in an actual hydrological or ML model; this project's baseline
score is a transparent weighted-average heuristic, not a hydrological
model. The SCS-CN method is the standard answer for "the smallest amount of
real hydrology you can add with almost no data" — a decades-old (USDA-SCS,
1972; still the basis of TR-55), low-data, GIS-computable method with
multiple published applications to Indian Himalayan hill catchments (see
docs/Data_Sources.md for citations, including from this project's own
research pass).

## What's real here, and what's a disclosed simplification

Real: each village's soil texture (ISRIC SoilGrids, live-queried, real
measured-and-modelled soil property data) and land cover (ESA WorldCover
10m, a real satellite-derived global land-cover product) — both fetched by
`scripts/prepare_glacier_mass_balance_data.py`'s sibling script,
`scripts/prepare_scs_cn_inputs.py`, and committed as
`data/derived/real_village_scs_cn_inputs.csv`. The resulting Curve Number
(CN) for each village is a real application of the standard NRCS
soil-texture -> Hydrologic Soil Group correspondence and the standard
published TR-55 land-use -> CN lookup tables (`CURVE_NUMBER_TABLE` below) —
not an invented number.

Disclosed simplifications, stated here rather than hidden:
  - **TR-55's CN tables are indexed by land use AND "hydrologic condition"
    (good/fair/poor ground cover) — WorldCover gives only the land-use
    class, not condition.** This module defaults every class to a single,
    stated representative condition (documented per-class in
    `CURVE_NUMBER_TABLE`'s comments) rather than guessing at ground
    condition from satellite land cover alone.
  - **Antecedent Moisture Condition (AMC) uses REAL 5-day antecedent
    rainfall when available, falling back to a soil-moisture proxy
    otherwise.** User-requested follow-up, from this project's own
    competitive-landscape research: `app/services/antecedent_rainfall.py`
    fetches real historical daily rainfall (NASA POWER, opt-in via
    `GIRIVARSHA_ACTIVE_ANTECEDENT_PROVIDER=real`) and computes the genuine
    standard 5-day antecedent total the SCS method actually calls for. When
    that real data isn't available (the provider is left at its default
    "simulated" setting, or a real fetch fails), this module falls back to
    the village's own CURRENT soil-moisture reading as an honest stand-in
    for antecedent wetness, with round, disclosed threshold cuts (see
    `_amc_class_from_soil_moisture`) — same "real proxy, honestly labelled"
    idiom already used for upstream-catchment (elevation order) and
    lead-time (straight-line distance) elsewhere in this app. Which path
    actually produced `amc_class` for a given call is stated plainly in
    `note`. See `antecedent_rainfall.py`'s own module docstring for a real,
    disclosed limitation of the real path itself: NASA POWER's own
    processing latency means its most recent ~1-2 weeks aren't yet
    available, so the real antecedent figure reflects roughly a week or two
    ago, not literally today.
  - **Rainfall depth is "current rate held for 1 hour," not a real
    hyetograph.** SCS-CN needs a storm DEPTH (mm), not a rate (mm/hr); this
    app only has a live instantaneous rate. Multiplying by 1 hour is a
    deliberately modest, stated assumption (not, say, 24 hours, which would
    produce implausibly large depths for a sustained heavy-rain rate) — see
    `ASSUMED_STORM_DURATION_HOURS`.
  - **Initial abstraction ratio (lambda) = 0.20**, the method's own
    original, most widely-used default (NRCS/TR-55) — a real, cited,
    standard choice, not a fitted one. More recent literature suggests
    lambda=0.05 fits some regions better; using the classic default is a
    documented, defensible starting point, not a claim that 0.20 is
    validated for these specific catchments.

This estimate is deliberately NOT folded into `risk_score`/`risk_level` —
same restraint already applied to `glacial_lake_distance_km` and (partly)
to `glacial_melt_rate`: it's a second, independent, transparently-derived
number a village's real conditions produce, useful to compare against the
baseline score, not a replacement for it or an input into it.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services.antecedent_rainfall import AntecedentRainfallResult
from app.services.lead_time import haversine_meters

DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "derived" / "real_village_scs_cn_inputs.csv"

# A village more than this far from any precomputed real input isn't
# meaningfully covered by this script's fetch — same "honest cutoff, not a
# silently-reused distant proxy" discipline as glacial_lake_proximity.py /
# glacial_melt_hazard.py's own MAX_RELEVANT_DISTANCE_KM, though set much
# tighter here since soil/land-cover inputs are fetched per-village, not
# looked up in a large regional inventory — a genuinely new village more
# than a few km away needs scripts/prepare_scs_cn_inputs.py re-run for it,
# not a distant neighbor's soil/land-cover borrowed silently.
MAX_RELEVANT_DISTANCE_KM = 15.0

ASSUMED_STORM_DURATION_HOURS = 1.0
INITIAL_ABSTRACTION_RATIO = 0.20  # lambda, the classic NRCS/TR-55 default

# Standard, published TR-55-style Curve Numbers (AMC-II) by Hydrologic Soil
# Group (A/B/C/D), one row per ESA WorldCover land-cover class. Each row
# picks ONE representative "hydrologic condition" (documented in its own
# comment) since WorldCover has no condition field of its own — see this
# module's docstring for why that's a disclosed simplification, not a
# hidden one.
CURVE_NUMBER_TABLE: dict[int, dict[str, float | str]] = {
    10: {"category": "Woods, fair condition", "A": 36, "B": 60, "C": 73, "D": 79},  # Tree cover
    20: {"category": "Brush-weed-grass mixture, fair condition", "A": 35, "B": 56, "C": 70, "D": 77},  # Shrubland
    30: {"category": "Pasture/grassland/range, fair condition", "A": 49, "B": 69, "C": 79, "D": 84},  # Grassland
    40: {"category": "Cultivated, with conservation treatment (terraced — common in Himalayan hill agriculture)", "A": 62, "B": 71, "C": 78, "D": 81},  # Cropland
    50: {"category": "Residential, ~1/3-acre-lot proxy for small hill settlements (~30% impervious)", "A": 57, "B": 72, "C": 81, "D": 86},  # Built-up
    60: {"category": "Fallow, bare soil", "A": 77, "B": 86, "C": 91, "D": 94},  # Bare / sparse vegetation
    90: {"category": "Pasture, poor condition (saturated-ground proxy)", "A": 68, "B": 79, "C": 86, "D": 89},  # Herbaceous wetland
    95: {"category": "Pasture, poor condition (saturated-ground proxy)", "A": 68, "B": 79, "C": 86, "D": 89},  # Mangroves (not expected in this pilot; included so a future coastal region doesn't crash)
    100: {"category": "Brush, poor condition (sparse alpine-cover proxy)", "A": 48, "B": 67, "C": 77, "D": 83},  # Moss and lichen
}
# 70 (Snow/ice) and 80 (Permanent water) deliberately have NO entry —
# SCS-CN doesn't meaningfully apply to a snow/ice or open-water surface;
# scripts/prepare_scs_cn_inputs.py already resolves a village whose exact
# point falls on one of these to the nearest real dry-land class within a
# ~110m window, so reaching this module with 70/80 here should be rare —
# if it ever happens, this returns an honest "not applicable" result rather
# than guessing.


@dataclass
class ScsCnInputs:
    village_name: str
    lat: float
    lon: float
    hydrologic_soil_group: str
    worldcover_class_code: int
    worldcover_class_name: str
    land_cover_source_note: str


@dataclass
class ScsCnResult:
    curve_number_amc2: float | None
    curve_number_used: float | None
    amc_class: str | None
    hydrologic_soil_group: str | None
    land_cover: str | None
    rainfall_depth_mm: float | None
    potential_retention_mm: float | None
    initial_abstraction_mm: float | None
    runoff_depth_mm: float | None
    runoff_ratio: float | None
    note: str


@lru_cache(maxsize=1)
def _load_inputs() -> tuple[ScsCnInputs, ...]:
    """Loads the real, pre-fetched per-village soil/land-cover inputs once
    per process. Same "degrade honestly, never crash" discipline as the
    glacial-lake/glacier-melt modules: a missing data file (e.g. a checkout
    that hasn't run scripts/prepare_scs_cn_inputs.py) returns an empty
    tuple, not an exception."""
    if not DATA_PATH.exists():
        return ()
    with DATA_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        records = []
        for row in reader:
            try:
                records.append(
                    ScsCnInputs(
                        village_name=row["village_name"],
                        lat=float(row["lat"]),
                        lon=float(row["lon"]),
                        hydrologic_soil_group=row["hydrologic_soil_group"],
                        worldcover_class_code=int(row["worldcover_class_code"]),
                        worldcover_class_name=row.get("worldcover_class_name", ""),
                        land_cover_source_note=row.get("land_cover_source_note", ""),
                    )
                )
            except (KeyError, ValueError):
                continue  # a malformed row is skipped, never guessed at
        return tuple(records)


def _nearest_inputs(lat: float, lon: float) -> ScsCnInputs | None:
    records = _load_inputs()
    if not records:
        return None
    best: tuple[float, ScsCnInputs] | None = None
    for rec in records:
        dist_km = haversine_meters(lat, lon, rec.lat, rec.lon) / 1000
        if best is None or dist_km < best[0]:
            best = (dist_km, rec)
    assert best is not None
    dist_km, rec = best
    if dist_km > MAX_RELEVANT_DISTANCE_KM:
        return None
    return rec


def _amc_class_from_soil_moisture(soil_moisture_pct: float) -> str:
    """Proxy for the standard SCS Antecedent Moisture Condition
    classification — see this module's docstring for why this uses current
    soil moisture rather than 5-day antecedent rainfall. Round, disclosed
    thresholds, not fitted ones."""
    if soil_moisture_pct < 30:
        return "I"  # dry
    if soil_moisture_pct <= 70:
        return "II"  # normal
    return "III"  # wet


def _adjust_cn_for_amc(cn_ii: float, amc_class: str) -> float:
    """Standard CN adjustment formulas (Hawkins et al., widely reproduced in
    NRCS guidance and hydrology textbooks — e.g. Chow, Maidment & Mays,
    'Applied Hydrology') converting a Curve Number derived for AMC-II
    (normal) conditions to its AMC-I (dry) or AMC-III (wet) equivalent."""
    if amc_class == "I":
        return round(cn_ii / (2.281 - 0.01281 * cn_ii), 2)
    if amc_class == "III":
        return round(cn_ii / (0.427 + 0.00573 * cn_ii), 2)
    return cn_ii


def estimate_runoff(
    lat: float,
    lon: float,
    rainfall_mm_hr: float,
    soil_moisture_pct: float,
    antecedent: AntecedentRainfallResult | None = None,
) -> ScsCnResult:
    """Real SCS-CN direct-runoff-depth estimate for one village right now,
    using its precomputed real soil/land-cover inputs plus this village's
    current (possibly What-If-overridden) rainfall rate and soil moisture.
    Degrades honestly (all fields None, explanatory note) if the input
    dataset is missing, this location isn't covered by it, or its land
    cover is a class SCS-CN doesn't apply to (snow/ice, open water).

    `antecedent` (optional, user-requested follow-up): a real or simulated
    AntecedentRainfallResult from app/services/antecedent_rainfall.py. When
    its `amc_class` is available, it's used directly instead of the
    soil-moisture proxy below — see this module's own docstring for the
    real/simulated/fallback contract. Left as None (the default) preserves
    the exact pre-existing soil-moisture-proxy behavior for any caller that
    doesn't pass it."""
    inputs = _nearest_inputs(lat, lon)
    if inputs is None:
        return ScsCnResult(
            curve_number_amc2=None, curve_number_used=None, amc_class=None,
            hydrologic_soil_group=None, land_cover=None, rainfall_depth_mm=None,
            potential_retention_mm=None, initial_abstraction_mm=None,
            runoff_depth_mm=None, runoff_ratio=None,
            note=(
                "Real soil/land-cover inputs not available for this location — run "
                "scripts/prepare_scs_cn_inputs.py (needs a village within "
                f"{MAX_RELEVANT_DISTANCE_KM:.0f}km of a precomputed one)."
            ),
        )

    cn_row = CURVE_NUMBER_TABLE.get(inputs.worldcover_class_code)
    if cn_row is None:
        return ScsCnResult(
            curve_number_amc2=None, curve_number_used=None, amc_class=None,
            hydrologic_soil_group=inputs.hydrologic_soil_group, land_cover=inputs.worldcover_class_name,
            rainfall_depth_mm=None, potential_retention_mm=None, initial_abstraction_mm=None,
            runoff_depth_mm=None, runoff_ratio=None,
            note=(
                f"This village's mapped land cover ({inputs.worldcover_class_name}) is snow/ice or open water — "
                "the SCS-CN method doesn't meaningfully apply to that surface, so no runoff estimate is computed "
                "rather than a fabricated one."
            ),
        )

    cn_ii = float(cn_row[inputs.hydrologic_soil_group])
    # Only a REAL antecedent-rainfall result is allowed to change AMC
    # classification from the pre-existing soil-moisture proxy — a
    # simulated antecedent figure is shown on the API for transparency (see
    # risk_engine.py) but is not treated as a genuine accuracy improvement
    # over the equally-simulated soil-moisture reading it would otherwise
    # replace, so it never silently changes this module's default output.
    # This keeps every existing caller's behavior byte-for-byte unchanged
    # unless GIRIVARSHA_ACTIVE_ANTECEDENT_PROVIDER=real is explicitly set
    # AND the live fetch actually succeeds.
    if antecedent is not None and antecedent.source == "real" and antecedent.amc_class is not None:
        amc_class = antecedent.amc_class
        amc_source_note = (
            f"AMC from real antecedent rainfall (5-day sum {antecedent.p5_mm:.1f}mm as of "
            f"{antecedent.as_of_date})"
        )
    else:
        amc_class = _amc_class_from_soil_moisture(soil_moisture_pct)
        amc_source_note = (
            f"AMC proxied from current soil-moisture reading ({soil_moisture_pct:.0f}%) — no real "
            "antecedent-rainfall data available"
        )
    cn_used = _adjust_cn_for_amc(cn_ii, amc_class)

    s_mm = (25400 / cn_used) - 254  # potential maximum retention
    ia_mm = INITIAL_ABSTRACTION_RATIO * s_mm
    p_mm = rainfall_mm_hr * ASSUMED_STORM_DURATION_HOURS

    if p_mm <= ia_mm:
        q_mm = 0.0
    else:
        q_mm = ((p_mm - ia_mm) ** 2) / (p_mm - ia_mm + s_mm)
    runoff_ratio = round(q_mm / p_mm, 3) if p_mm > 0 else 0.0

    return ScsCnResult(
        curve_number_amc2=round(cn_ii, 2),
        curve_number_used=round(cn_used, 2),
        amc_class=amc_class,
        hydrologic_soil_group=inputs.hydrologic_soil_group,
        land_cover=inputs.worldcover_class_name,
        rainfall_depth_mm=round(p_mm, 2),
        potential_retention_mm=round(s_mm, 2),
        initial_abstraction_mm=round(ia_mm, 2),
        runoff_depth_mm=round(q_mm, 2),
        runoff_ratio=runoff_ratio,
        note=(
            f"SCS-CN estimate: {inputs.worldcover_class_name} ({cn_row['category']}) on real Hydrologic Soil Group "
            f"{inputs.hydrologic_soil_group} soil -> CN(AMC-II)={cn_ii:.0f}, adjusted to CN={cn_used:.1f} for "
            f"AMC-{amc_class} ({amc_source_note}). Rainfall depth assumes the current {rainfall_mm_hr:.1f}mm/hr rate "
            f"held for {ASSUMED_STORM_DURATION_HOURS:.0f} hour — a real hyetograph would differ. Real, standard "
            "method (NRCS TR-55); a second, independent estimate shown alongside the baseline score, not folded "
            "into it — see app/services/scs_cn_runoff.py's module docstring for every simplification made."
        ),
    )
