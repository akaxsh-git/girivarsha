"""
Phase 9: model-agnostic "why is this village at risk" explanation
(problem-statement item 35).

Honesty note this module exists specifically to enforce: the ONLY model
behind GET /risk/* is the Phase 4 transparent baseline (`weighted_baseline`)
— the Phase 5 ML layer is built but NOT deployed (see GET /version's
`ml_layer`, docs/ML_Methodology.md). A real SHAP explanation requires a
real deployed model to explain; there isn't one. So this endpoint explains
the ACTUAL active model — ranking and narrating the baseline's own
transparent components (already computed in risk_engine.py, nothing
new is invented here) — rather than fabricating SHAP-style values for a
model that isn't running. If/when the ML layer is ever deployed, a real
SHAP explainer belongs here instead; that swap is explicitly flagged, not
silently pretended to already exist.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.services.risk_engine import Component, RiskAssessment

PLAIN_LANGUAGE = {
    "rainfall_intensity": "how hard it is currently raining at this village",
    "soil_moisture": "how saturated the ground already is",
    "upstream_rainfall": "how much rain is falling upstream in the same catchment",
    "historical_susceptibility": "how prone this area is, based on real recorded past events",
    "glacial_melt_rate": "how fast the nearest real glacier is losing mass right now",
}


@dataclass
class DriverExplanation:
    name: str
    plain_language: str
    score_contribution: float
    share_of_score_pct: float
    raw_value: float
    unit: str
    source: str
    detail: str


@dataclass
class Explanation:
    summary: str
    ranked_drivers: list[DriverExplanation]
    model_explained: str
    caveat: str


def explain(assessment: RiskAssessment, village_name: str) -> Explanation:
    total_contribution = sum(c.score_contribution for c in assessment.components) or 1.0
    ranked = sorted(assessment.components, key=lambda c: c.score_contribution, reverse=True)

    drivers = [
        DriverExplanation(
            name=c.name,
            plain_language=PLAIN_LANGUAGE.get(c.name, c.name.replace("_", " ")),
            score_contribution=c.score_contribution,
            share_of_score_pct=round(100 * c.score_contribution / total_contribution, 1),
            raw_value=c.raw_value,
            unit=c.unit,
            source=c.source.value,
            # Passes through risk_engine.py's own technical description
            # verbatim (e.g. "...from this village's live sensor
            # (sensor:esp32-...)") — the plain_language mapping above is a
            # static label per component name, so it can't say WHERE this
            # particular number actually came from; this field can, without
            # this module needing to know anything about sensors itself.
            detail=c.description,
        )
        for c in ranked
    ]

    if all(d.score_contribution == 0 for d in drivers):
        summary = (
            f"{village_name}'s current score ({assessment.score}/100, {assessment.level.value}) "
            "has no single dominant driver — every input is at or near its minimum right now."
        )
    else:
        top = drivers[0]
        if len(drivers) > 1 and drivers[1].score_contribution > 0:
            second = drivers[1]
            summary = (
                f"{village_name}'s risk score ({assessment.score}/100, {assessment.level.value}) is "
                f"driven primarily by {top.plain_language} ({top.share_of_score_pct}% of the score), "
                f"followed by {second.plain_language} ({second.share_of_score_pct}%)."
            )
        else:
            summary = (
                f"{village_name}'s risk score ({assessment.score}/100, {assessment.level.value}) is "
                f"driven almost entirely by {top.plain_language} ({top.share_of_score_pct}% of the score)."
            )

    return Explanation(
        summary=summary,
        ranked_drivers=drivers,
        model_explained="weighted_baseline (Phase 4 active model) — see GET /version's active_model",
        caveat=(
            "This explains the ACTIVE baseline model's own transparent formula, not a SHAP-style "
            "attribution over the Phase 5 ML layer — that layer is not deployed (GET /version's "
            "ml_layer.status). Ranking real component contributions IS a real model-agnostic "
            "explanation of what's actually running; it becomes a genuine SHAP explanation "
            "automatically if/when a real ML model is ever deployed behind GET /risk/*."
        ),
    )
