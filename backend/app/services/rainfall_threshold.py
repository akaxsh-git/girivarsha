"""
Rainfall intensity-duration (I-D) landslide-threshold indicator — a THIRD
independent indicator shown alongside the Phase 4 weighted score and the
SCS-CN runoff estimate (app/services/scs_cn_runoff.py). Closes the first of
the two remaining recommendations from this project's own
competitive-landscape research pass (docs/Future_Work.md, "Competitive-
landscape research"): "Rainfall-intensity-duration threshold rules ... as a
third independent indicator alongside the weighted score and SCS-CN
runoff."

## Real, cited source

Kanungo, D. P. & Sharma, Shaifaly (2014), "Rainfall thresholds for
prediction of shallow landslides around Chamoli-Joshimath region, Garhwal
Himalayas, India," Landslides, Vol. 11, pp. 629-638,
DOI: 10.1007/s10346-013-0438-9 — a real, peer-reviewed, REGION-SPECIFIC
study. Unusually well-matched to this project: the study area is literally
this app's own Chamoli Disaster Valley pilot region (Reni, Tapovan,
Vishnuprayag, Joshimath sit within/adjacent to the Chamoli-Joshimath
region the paper studied).

The paper's derived intensity-duration threshold for triggering shallow
landslides in this region, for events up to 24 hours:

    I = 1.82 * D^(-0.23)      (I in mm/hr, D in hours)

...with a stated critical/minimum intensity of 0.87 mm/hr, below which the
paper's own dataset found no association between rainfall and a triggered
landslide at any duration up to 24h. Used here as a floor — never
extrapolated below it.

## What this module actually computes

Given a village's current, live (or What-If-overridden) rainfall rate,
this finds the duration D* at which that rate, held CONSTANT, would cross
the published threshold curve — i.e. solving I(D*) = current rate. In
plain language: "if rainfall continued at today's rate, roughly how many
hours before it matches the historically-associated shallow-landslide-
triggering intensity for a storm of that length." This is the same idiom
real Flash Flood Guidance systems use ("how much rain in X hours would
cause flooding") — applied here to a real, cited regional curve rather
than an invented one.

Because I(D) is monotonically DECREASING in D, a HIGH current rate crosses
the curve at a SHORT duration (already at/above the trigger intensity even
for a brief event); a LOW-but-above-floor current rate crosses it only at
a LONG duration (would need many hours of sustained rain at that rate).

## Two disclosed simplifications — stated here, not hidden

1. **Applicability is honestly two-tier.** The Chamoli Disaster Valley
   region genuinely IS the Chamoli-Joshimath region the paper studied — a
   direct fit (`applicability="direct_fit"`). The Mandakini valley
   (Kedarnath-Rudraprayag) is a DIFFERENT catchment in the same broader
   Garhwal Himalaya climatic/geological zone, not the study's own
   catchment — applying the same curve there is a disclosed REGIONAL PROXY
   (`applicability="regional_proxy"`), the same "real proxy, honestly
   labelled" idiom already used elsewhere in this app for the elevation-
   order upstream proxy and the straight-line lead-time estimate. Every
   result's `note` states plainly which case applied and why.
2. **A constant-rate assumption, not a real hyetograph.** Like
   scs_cn_runoff.py's own storm-depth assumption, this treats "the current
   instantaneous rate held steady for D hours" as the model input. A real
   storm accelerates and decelerates — this computes what a SUSTAINED
   continuation of right-now's rate would imply, not a forecast of what
   will actually happen.

Deliberately NOT folded into `risk_score`/`risk_level` — a third,
independent, transparently-derived figure shown alongside the weighted
score and the SCS-CN estimate, matching the restraint already applied to
`glacial_lake_distance_km`, `glof_contribution_pct`, and
`scs_cn_runoff_depth_mm`.
"""
from __future__ import annotations

from dataclasses import dataclass

# I(D) = ID_THRESHOLD_COEFFICIENT * D ** (-ID_THRESHOLD_EXPONENT)
# (I in mm/hr, D in hours) — Kanungo & Sharma (2014), eq. for the
# Chamoli-Joshimath region's shallow-landslide-triggering I-D threshold.
ID_THRESHOLD_COEFFICIENT = 1.82
ID_THRESHOLD_EXPONENT = 0.23

# Below this rate, the study's own dataset found no association with a
# triggered landslide at any duration up to MAX_STUDIED_DURATION_HOURS —
# a real, cited floor, not an extrapolation.
CRITICAL_INTENSITY_FLOOR_MM_HR = 0.87

# The paper's own validated event-duration range. A computed crossing
# duration beyond this is reported as "not indicated within that range"
# rather than extrapolated past what the study actually covered.
MAX_STUDIED_DURATION_HOURS = 24.0

SOURCE_CITATION = (
    "Kanungo, D. P. & Sharma, Shaifaly (2014), \"Rainfall thresholds for prediction of "
    "shallow landslides around Chamoli-Joshimath region, Garhwal Himalayas, India,\" "
    "Landslides, Vol. 11, pp. 629-638, DOI: 10.1007/s10346-013-0438-9."
)


@dataclass
class RainfallThresholdResult:
    current_intensity_mm_hr: float
    hours_to_threshold: float | None
    status: str  # "below_floor" | "threshold_exceeded" | "approaching_within_24h" | "not_indicated_within_24h"
    applicability: str  # "direct_fit" | "regional_proxy"
    region_name: str | None
    note: str


def _region_applicability(region_name: str | None) -> tuple[str, str]:
    """Returns (applicability_tag, human-readable clause for the note)."""
    region_label = region_name or "this village's region"
    if region_name and "chamoli" in region_name.lower():
        return (
            "direct_fit",
            f"a direct fit for {region_label}, the exact region this study covers",
        )
    return (
        "regional_proxy",
        f"applied to {region_label} as a disclosed regional proxy (same Garhwal Himalaya "
        "climatic/geological zone, not the study's own Chamoli-Joshimath catchment)",
    )


def _hours_to_threshold(intensity_mm_hr: float) -> float:
    """Solves I(D) = intensity for D, given I(D) = C * D^-k. Only called
    for intensity >= CRITICAL_INTENSITY_FLOOR_MM_HR (caller's guard), so
    intensity is always > 0 here."""
    return (ID_THRESHOLD_COEFFICIENT / intensity_mm_hr) ** (1 / ID_THRESHOLD_EXPONENT)


def assess_rainfall_threshold(intensity_mm_hr: float, region_name: str | None) -> RainfallThresholdResult:
    """Real, formula-based I-D threshold assessment for one village right
    now, given its current (possibly What-If-overridden) rainfall rate.
    Never raises — a non-finite/negative intensity is treated as 0, same
    "degrade honestly, never crash" discipline as every other advisory
    indicator in this app."""
    intensity = max(0.0, intensity_mm_hr) if intensity_mm_hr == intensity_mm_hr else 0.0  # NaN guard
    applicability, applicability_clause = _region_applicability(region_name)

    if intensity < CRITICAL_INTENSITY_FLOOR_MM_HR:
        return RainfallThresholdResult(
            current_intensity_mm_hr=round(intensity, 3),
            hours_to_threshold=None,
            status="below_floor",
            applicability=applicability,
            region_name=region_name,
            note=(
                f"Current rainfall rate ({intensity:.2f}mm/hr) is below the study's own "
                f"{CRITICAL_INTENSITY_FLOOR_MM_HR:.2f}mm/hr floor, below which its real dataset found no "
                f"association with triggering a shallow landslide at any duration up to "
                f"{MAX_STUDIED_DURATION_HOURS:.0f}h — {applicability_clause}. {SOURCE_CITATION}"
            ),
        )

    hours = _hours_to_threshold(intensity)

    if hours <= 1.0:
        status = "threshold_exceeded"
        note = (
            f"Current rainfall rate ({intensity:.2f}mm/hr) already meets or exceeds the published "
            f"intensity-duration threshold (I = {ID_THRESHOLD_COEFFICIENT} x D^-{ID_THRESHOLD_EXPONENT}) even for "
            f"a short (~1h) event — {applicability_clause}. {SOURCE_CITATION}"
        )
    elif hours <= MAX_STUDIED_DURATION_HOURS:
        status = "approaching_within_24h"
        note = (
            f"At the current rate ({intensity:.2f}mm/hr), sustained rainfall would cross the published "
            f"intensity-duration threshold after roughly {hours:.1f}h — {applicability_clause}. {SOURCE_CITATION}"
        )
    else:
        status = "not_indicated_within_24h"
        note = (
            f"At the current rate ({intensity:.2f}mm/hr), it would take longer than the study's own validated "
            f"{MAX_STUDIED_DURATION_HOURS:.0f}h event window to cross the published threshold — not indicated "
            f"within that range — {applicability_clause}. {SOURCE_CITATION}"
        )

    return RainfallThresholdResult(
        current_intensity_mm_hr=round(intensity, 3),
        hours_to_threshold=round(hours, 2),
        status=status,
        applicability=applicability,
        region_name=region_name,
        note=note,
    )
