"""No DB required — a pure config sanity check. Runs even without Postgres
set up, unlike test_risk.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.core.config import get_settings  # noqa: E402


def test_risk_weights_sum_to_one():
    weights = get_settings().risk_weights
    total = (
        weights.rainfall_intensity
        + weights.soil_moisture
        + weights.upstream_rainfall
        + weights.historical_susceptibility
        + weights.glacial_melt_rate
    )
    assert abs(total - 1.0) < 1e-9, (
        f"risk_weights must sum to 1.0 (a weighted-average confidence/score formula assumes "
        f"this) — got {total}. Check backend/.env overrides if this fails outside CI defaults."
    )
