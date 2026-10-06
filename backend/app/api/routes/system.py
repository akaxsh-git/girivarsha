from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.config import get_settings
from app.services.risk_engine import MODEL_VERSION_TAG

router = APIRouter(tags=["system"])


@router.api_route("/health", methods=["GET", "HEAD"])
def health():
    """Liveness/readiness probe. Always cheap, never touches the DB or a provider."""
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "phase": settings.build_phase,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/version")
def version():
    """
    Minimal model/build governance stub (problem-statement item 38).
    Expands once a real risk model exists (Phase 5+): model_type, model_version,
    threshold_version, trained_at, etc. will be added then, not invented now.
    """
    settings = get_settings()
    return {
        "app": settings.app_name,
        "build_phase": settings.build_phase,
        "risk_thresholds": settings.risk_thresholds.model_dump(),
        "risk_weights": settings.risk_weights.model_dump(),
        "active_model": {
            "model_type": "weighted_baseline",
            "version_tag": MODEL_VERSION_TAG,
            "trained": False,
            "note": (
                "A transparent weighted-sum baseline (Phase 4), not a trained/fitted model — "
                "see app/services/risk_engine.py. This is the ONLY model behind GET /risk/*."
            ),
        },
        "ml_layer": {
            "status": "not_deployed",
            "reason": (
                "Insufficient real labelled historical events (1 recorded event in the pilot "
                "region — the 2013 Kedarnath flash flood) to train or validate a real model. "
                "A synthetic-data pipeline smoke test exists (ml/train.py) and passes — it proves "
                "the training/evaluation mechanics work, not real-world predictive skill."
            ),
            "note": "See docs/ML_Methodology.md and docs/Limitations.md. GET /risk/* does not use this layer.",
        },
        "iot_layer": {
            "status": "real_pipeline_simulated_hardware",
            "note": (
                "Real MQTT broker + real bridge (iot/mqtt_bridge.py) + this real ingestion API "
                "(GET/POST /sensors, /sensor-readings) — actually run and verified end-to-end. "
                "Only the publisher on the MQTT side is simulated (iot/simulate_sensor_publisher.py), "
                "standing in for physical ESP32 hardware that doesn't exist in this build "
                "environment; real firmware sketches exist (iot/firmware/) but are untested on "
                "actual boards. See docs/IoT_Architecture.md for the verification run."
            ),
            "sensor_thresholds": settings.sensor_thresholds.model_dump(),
        },
    }
