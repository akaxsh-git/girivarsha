from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.database import get_db
from app.models.orm import MicroCatchment, Village
from app.models.schemas import (
    ExplanationOut,
    RiskAssessmentOut,
    RiskMapEntryOut,
    SimulationOut,
    SimulationRequest,
)
from app.providers.base import get_rainfall_provider, get_soil_provider
from app.providers.notification import get_notification_provider
from app.services import alert_broadcaster
from app.services.alerts_engine import AlertTransition, sync_alert_for_village
from app.services.explanation import explain
from app.services.notifications import dispatch_transition
from app.services.risk_engine import (
    compute_risk_for_village,
    get_or_create_model_version,
    persist_prediction,
    prefetch_readings,
)

router = APIRouter(tags=["risk"])


def _react_to_transitions(db: Session, settings: Settings, transitions: list[AlertTransition]) -> None:
    """Real-time-push + SMS-reach follow-up (user-requested): called once,
    after the caller's own db.commit(), for every real AlertTransition a
    /risk/map or /risk/{id} call actually produced (never for a no-op — see
    alerts_engine.py). Pushes each one to any connected SSE client
    (GET /alerts/stream) and, for a real ORANGE/RED open/escalation, sends
    (or, by default, only logs — see app/providers/notification.py) an SMS
    to that village's subscribers.

    Deliberately runs AFTER db.commit(), not interleaved with it — so a
    slow/misbehaving SSE subscriber or a slow SMS provider call can never
    block the transaction that actually persists the alert."""
    if not transitions:
        return
    provider = get_notification_provider(
        settings.active_sms_provider,
        account_sid=settings.twilio_account_sid,
        auth_token=settings.twilio_auth_token,
        from_number=settings.twilio_from_number,
    )
    for transition in transitions:
        payload = asdict(transition)
        if payload.get("level") is not None:
            payload["level"] = transition.level.value  # AlertLevel enum -> its wire string
        alert_broadcaster.publish(payload)
        dispatch_transition(db, provider, transition)


@router.get("/risk/map", response_model=list[RiskMapEntryOut])
def risk_map(region_id: int | None = None, db: Session = Depends(get_db)):
    """GET /risk/map — Phase 4 transparent baseline risk score/level per
    village. See app/services/risk_engine.py for the full, documented
    formula — nothing here is a black box or a hard-coded number. Optional
    `?region_id=` (Phase 11) scopes this to one real region — without it,
    every village across every seeded region is scored, same as before
    regions existed."""
    settings = get_settings()
    query = select(Village)
    if region_id is not None:
        query = query.join(MicroCatchment, Village.catchment_id == MicroCatchment.id).where(
            MicroCatchment.region_id == region_id
        )
    villages = db.scalars(query).all()
    model_version = get_or_create_model_version(db, settings)

    # Performance follow-up (user-requested — see risk_engine.prefetch_readings
    # for the full story): resolve every village's rainfall/soil reading
    # ONCE, up front, shared across the whole request — instead of letting
    # each village's own call (and every OTHER village's upstream lookup)
    # independently re-fetch the same village's reading. Same providers,
    # same data, same fallback hierarchy — just done once each and, where
    # safe, concurrently instead of one at a time.
    rainfall_provider = get_rainfall_provider(settings.active_rainfall_provider)
    soil_provider = get_soil_provider(settings.active_soil_provider)
    rainfall_cache, soil_cache = prefetch_readings(rainfall_provider, soil_provider, villages, db)

    transitions: list[AlertTransition] = []
    out = []
    for v in villages:
        assessment = compute_risk_for_village(
            v,
            db,
            settings=settings,
            rainfall_provider=rainfall_provider,
            soil_provider=soil_provider,
            all_villages_in_catchment=villages,
            rainfall_cache=rainfall_cache,
            soil_cache=soil_cache,
        )
        prediction = persist_prediction(db, assessment, model_version)
        alert = sync_alert_for_village(db, v, assessment, transitions=transitions)
        if alert is not None and alert.risk_prediction_id is None:
            alert.risk_prediction_id = prediction.id
        out.append(
            RiskMapEntryOut(
                village_id=v.id,
                village_name=v.name,
                risk_score=assessment.score,
                risk_level=assessment.level.value,
                confidence_pct=assessment.confidence_pct,
                lead_time_minutes=prediction.lead_time_minutes,
                glacial_lake_distance_km=assessment.glacial_lake_distance_km,
                glof_contribution_pct=assessment.glof_contribution_pct,
                glof_contribution_tier=assessment.glof_contribution_tier,
                scs_cn_runoff_depth_mm=assessment.scs_cn_runoff_depth_mm,
                scs_cn_curve_number=assessment.scs_cn_curve_number,
                rainfall_threshold_hours_to_threshold=assessment.rainfall_threshold_hours_to_threshold,
                rainfall_threshold_status=assessment.rainfall_threshold_status,
                antecedent_rainfall_5day_mm=assessment.antecedent_rainfall_5day_mm,
                antecedent_rainfall_source=assessment.antecedent_rainfall_source,
            )
        )
    db.commit()
    _react_to_transitions(db, settings, transitions)
    return out


@router.get("/risk/{village_id}", response_model=RiskAssessmentOut)
def risk_for_village(village_id: int, db: Session = Depends(get_db)):
    """GET /risk/{id} — full transparent driver breakdown for one village
    (problem-statement items 9, 35), including a Phase 10 prototype lead
    -time estimate (see app/services/lead_time.py — a straight-line-distance
    / single-assumed-velocity figure, not a validated hydraulic model;
    `lead_time_note` always explains the reasoning or, for a source
    village with nothing upstream, honestly explains why there is none)."""
    settings = get_settings()
    village = db.get(Village, village_id)
    if village is None:
        raise HTTPException(status_code=404, detail=f"No village with id={village_id}")

    model_version = get_or_create_model_version(db, settings)
    assessment = compute_risk_for_village(village, db, settings=settings)
    prediction = persist_prediction(db, assessment, model_version)
    transitions: list[AlertTransition] = []
    alert = sync_alert_for_village(db, village, assessment, transitions=transitions)
    if alert is not None and alert.risk_prediction_id is None:
        alert.risk_prediction_id = prediction.id
    db.commit()
    _react_to_transitions(db, settings, transitions)

    return RiskAssessmentOut(
        village_id=village.id,
        village_name=village.name,
        risk_score=assessment.score,
        risk_level=assessment.level.value,
        confidence_pct=assessment.confidence_pct,
        lead_time_minutes=prediction.lead_time_minutes,
        lead_time_note=assessment.lead_time_note,
        glacial_lake_distance_km=assessment.glacial_lake_distance_km,
        glacial_lake_note=assessment.glacial_lake_note,
        glof_contribution_pct=assessment.glof_contribution_pct,
        glof_contribution_tier=assessment.glof_contribution_tier,
        glof_contribution_note=assessment.glof_contribution_note,
        scs_cn_curve_number=assessment.scs_cn_curve_number,
        scs_cn_amc_class=assessment.scs_cn_amc_class,
        scs_cn_hydrologic_soil_group=assessment.scs_cn_hydrologic_soil_group,
        scs_cn_land_cover=assessment.scs_cn_land_cover,
        scs_cn_rainfall_depth_mm=assessment.scs_cn_rainfall_depth_mm,
        scs_cn_runoff_depth_mm=assessment.scs_cn_runoff_depth_mm,
        scs_cn_runoff_ratio=assessment.scs_cn_runoff_ratio,
        scs_cn_note=assessment.scs_cn_note,
        rainfall_threshold_hours_to_threshold=assessment.rainfall_threshold_hours_to_threshold,
        rainfall_threshold_status=assessment.rainfall_threshold_status,
        rainfall_threshold_applicability=assessment.rainfall_threshold_applicability,
        rainfall_threshold_note=assessment.rainfall_threshold_note,
        antecedent_rainfall_5day_mm=assessment.antecedent_rainfall_5day_mm,
        antecedent_rainfall_10day_mm=assessment.antecedent_rainfall_10day_mm,
        antecedent_rainfall_20day_mm=assessment.antecedent_rainfall_20day_mm,
        antecedent_rainfall_as_of=assessment.antecedent_rainfall_as_of,
        antecedent_rainfall_source=assessment.antecedent_rainfall_source,
        antecedent_rainfall_note=assessment.antecedent_rainfall_note,
        model_version=assessment.model_version_tag,
        drivers=assessment.drivers_json(),
        computed_at=assessment.computed_at.isoformat(),
    )


@router.get("/model/explanation/{village_id}", response_model=ExplanationOut)
def model_explanation(village_id: int, db: Session = Depends(get_db)):
    """GET /model/explanation/{id} — Phase 9's "why is this village at risk"
    feature (item 35): ranks and narrates the ACTIVE baseline model's own
    real components in plain language. See app/services/explanation.py's
    module docstring for why this is a genuine model-agnostic explanation
    of what's actually running, not a fabricated SHAP explanation of the
    undeployed Phase 5 ML layer."""
    settings = get_settings()
    village = db.get(Village, village_id)
    if village is None:
        raise HTTPException(status_code=404, detail=f"No village with id={village_id}")

    assessment = compute_risk_for_village(village, db, settings=settings)
    explanation = explain(assessment, village.name)

    return ExplanationOut(
        village_id=village.id,
        village_name=village.name,
        summary=explanation.summary,
        ranked_drivers=explanation.ranked_drivers,
        model_explained=explanation.model_explained,
        caveat=explanation.caveat,
    )


@router.post("/simulate", response_model=SimulationOut)
def run_simulation(payload: SimulationRequest, db: Session = Depends(get_db)):
    """POST /simulate — the What-If Simulator (problem-statement item 20).
    Lets a presenter override one village's rainfall and/or soil-moisture
    INPUT and see how the SAME transparent Phase 4 baseline formula
    (app/services/risk_engine.py) responds — there is no separate
    simulation model, and nothing here is persisted or fed into /alerts.
    Returns both the village's real current assessment and the hypothetical
    one so the delta the override caused is visible, not presented as if it
    were the village's actual live risk. Also returns baseline-vs-simulated
    SCS-CN rainfall-runoff figures (user-requested follow-up), since that
    estimate — unlike the glacial-lake/glacier-melt fields — depends on
    rainfall/soil-moisture and therefore responds to these overrides."""
    settings = get_settings()
    village = db.get(Village, payload.village_id)
    if village is None:
        raise HTTPException(status_code=404, detail=f"No village with id={payload.village_id}")

    baseline = compute_risk_for_village(village, db, settings=settings)
    simulated = compute_risk_for_village(
        village,
        db,
        settings=settings,
        rainfall_override=payload.rainfall_mm_hr,
        soil_override=payload.soil_moisture_pct,
    )

    overrides_applied: dict = {}
    if payload.rainfall_mm_hr is not None:
        overrides_applied["rainfall_mm_hr"] = payload.rainfall_mm_hr
    if payload.soil_moisture_pct is not None:
        overrides_applied["soil_moisture_pct"] = payload.soil_moisture_pct

    return SimulationOut(
        village_id=village.id,
        village_name=village.name,
        overrides_applied=overrides_applied,
        baseline_risk_score=baseline.score,
        baseline_risk_level=baseline.level.value,
        baseline_confidence_pct=baseline.confidence_pct,
        simulated_risk_score=simulated.score,
        simulated_risk_level=simulated.level.value,
        simulated_confidence_pct=simulated.confidence_pct,
        baseline_scs_cn_curve_number=baseline.scs_cn_curve_number,
        baseline_scs_cn_runoff_depth_mm=baseline.scs_cn_runoff_depth_mm,
        baseline_scs_cn_runoff_ratio=baseline.scs_cn_runoff_ratio,
        baseline_scs_cn_note=baseline.scs_cn_note,
        simulated_scs_cn_curve_number=simulated.scs_cn_curve_number,
        simulated_scs_cn_runoff_depth_mm=simulated.scs_cn_runoff_depth_mm,
        simulated_scs_cn_runoff_ratio=simulated.scs_cn_runoff_ratio,
        simulated_scs_cn_note=simulated.scs_cn_note,
        baseline_rainfall_threshold_hours_to_threshold=baseline.rainfall_threshold_hours_to_threshold,
        baseline_rainfall_threshold_status=baseline.rainfall_threshold_status,
        baseline_rainfall_threshold_note=baseline.rainfall_threshold_note,
        simulated_rainfall_threshold_hours_to_threshold=simulated.rainfall_threshold_hours_to_threshold,
        simulated_rainfall_threshold_status=simulated.rainfall_threshold_status,
        simulated_rainfall_threshold_note=simulated.rainfall_threshold_note,
        antecedent_rainfall_5day_mm=simulated.antecedent_rainfall_5day_mm,
        antecedent_rainfall_source=simulated.antecedent_rainfall_source,
        antecedent_rainfall_note=simulated.antecedent_rainfall_note,
        model_version=simulated.model_version_tag,
        drivers=simulated.drivers_json(),
        note=(
            "This is a hypothetical what-if scenario, not a live reading. Overridden "
            "input(s) are tagged SIMULATED here regardless of this village's real current "
            "data source. Nothing about this run is persisted to the database or fed "
            "into /alerts — it has zero side effects on the real system. The SCS-CN "
            "runoff and rainfall intensity-duration threshold fields both respond to "
            "rainfall/soil-moisture overrides (unlike the glacial-lake/glacier-melt "
            "fields, which don't depend on those inputs) — compare baseline_scs_cn_* / "
            "baseline_rainfall_threshold_* against simulated_scs_cn_* / "
            "simulated_rainfall_threshold_* to see the effect. antecedent_rainfall_* is "
            "real/simulated rainfall HISTORY, independent of any override, so it's shown "
            "once rather than as a baseline/simulated pair — a soil_moisture_pct override "
            "only changes SCS-CN's AMC classification when antecedent_rainfall_source is "
            "NOT 'real' (a real antecedent-rainfall result drives AMC instead once active)."
        ),
    )
