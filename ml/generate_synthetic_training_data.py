"""
Phase 5 honesty note, up front: this generates a SYNTHETIC labelled dataset
— it does not, and cannot, produce real flash-flood training data. The
pilot region has exactly ONE real recorded historical event (2013
Kedarnath — see scripts/seed_pilot_region.py and docs/Data_Sources.md).
One labelled event is nowhere near enough to train or validate a real
predictive model; the problem statement (item 9) explicitly asks that this
be stated plainly rather than papered over with a model that looks
plausible but isn't backed by real outcomes.

What this file IS for: proving the ML pipeline itself — feature
engineering, temporal train/test splitting, the model-comparison ladder,
and honest metric reporting — actually works end-to-end (ml/train.py).
The "ground truth" labels here come from a known synthetic function of the
features (see `_true_hazard_probability` below), not from anything that
happened in the real world. A model trained on this data learns to
recover that known function; it says nothing about real flood risk.

Village elevations are the one real thing borrowed here — they match
scripts/seed_pilot_region.py exactly (checked by
tests/ml/test_pipeline.py::test_village_elevations_match_seed_script, so
the two can't silently drift apart). Everything else (rainfall, soil
moisture, upstream rainfall, day-to-day variation) is synthetic.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Must match scripts/seed_pilot_region.py's VILLAGES elevations exactly —
# see the module docstring above and tests/ml/test_pipeline.py.
VILLAGE_ELEVATIONS = {
    "Kedarnath": 3583,
    "Rambara": 2740,
    "Gaurikund": 1982,
    "Sonprayag": 1360,
    "Ukhimath": 1311,
    "Rudraprayag": 895,
}

# Upstream-order proxy matching risk_engine.py's own logic: a village's
# "upstream neighbours" are the other pilot villages at higher elevation.
_ORDERED = sorted(VILLAGE_ELEVATIONS.items(), key=lambda kv: -kv[1])
UPSTREAM_OF = {
    name: [n for n, e in VILLAGE_ELEVATIONS.items() if e > elev]
    for name, elev in VILLAGE_ELEVATIONS.items()
}

RAINFALL_CAP_MM_PER_HR = 50.0


def _true_hazard_probability(
    rainfall_intensity: np.ndarray,
    soil_moisture: np.ndarray,
    upstream_rainfall: np.ndarray,
    historical_susceptibility: np.ndarray,
) -> np.ndarray:
    """The synthetic ground-truth function. Deliberately mirrors the shape of
    risk_engine.py's weighted formula (same intuition: heavy local rain +
    saturated soil + heavy upstream rain + a hazard-prone history combine to
    push risk up) so that a model trained on this data is learning something
    structurally similar to what the baseline already encodes — a
    reasonable check that the ML pipeline and the baseline aren't
    contradicting each other in spirit, even though this data is synthetic."""
    z = (
        3.2 * (rainfall_intensity / RAINFALL_CAP_MM_PER_HR)
        + 1.6 * (soil_moisture / 100.0)
        + 2.4 * (upstream_rainfall / RAINFALL_CAP_MM_PER_HR)
        + 1.0 * historical_susceptibility
        - 3.6  # intercept, tuned so positive-class rate is realistically low (rare-event imbalance)
    )
    return 1.0 / (1.0 + np.exp(-z))


def generate_synthetic_dataset(n_days: int = 1200, seed: int = 42) -> pd.DataFrame:
    """One row per (village, day). Columns: village, elevation_m,
    rainfall_intensity, soil_moisture, upstream_rainfall,
    historical_susceptibility, day_index (for temporal splitting),
    event (0/1 synthetic label)."""
    rng = np.random.default_rng(seed)
    villages = list(VILLAGE_ELEVATIONS.keys())
    rows = []

    # Historical susceptibility mirrors risk_engine.py's real logic: only
    # Kedarnath has a direct recorded event (the 2013 disaster); every other
    # seeded village gets the catchment-wide discounted value, since they're
    # all in the same historically-hazardous valley. This part is real
    # (derived from the one real seeded event), everything else in this
    # function is synthetic.
    historical_susceptibility = {v: (1.0 if v == "Kedarnath" else 0.5) for v in villages}

    # Per-village correlated "weather state" (a simple AR(1) process) so
    # rainfall isn't pure IID noise day-to-day — closer to how real rainfall
    # persists over a few days, without claiming to be a real hydrological
    # simulator.
    state = {v: 0.0 for v in villages}

    for day in range(n_days):
        # A shared regional signal (some days are wetter across the whole
        # valley) plus village-level noise — crude, but gives the "upstream
        # rainfall" feature real information to correlate with, rather than
        # being independent noise that a model could never usefully learn from.
        # A small fraction of days are cloudburst-style storm days (a large
        # positive regional shock) — this is what actually triggers the
        # synthetic "event" label most of the time, which is deliberately
        # realistic in shape (flash floods are driven by rare extreme
        # rainfall, not average conditions) even though the specific numbers
        # are synthetic.
        is_storm_day = rng.random() < 0.05
        regional = rng.uniform(4.0, 8.0) if is_storm_day else rng.normal(0, 1)
        for v in villages:
            state[v] = 0.6 * state[v] + 0.4 * rng.normal(regional, 1.0)
            rainfall = max(0.0, 4.0 + state[v] * 6.0)
            soil = min(100.0, max(0.0, 45.0 + state[v] * 12.0 + rng.normal(0, 8)))
            upstream = [rainfall]
            for u in UPSTREAM_OF[v]:
                upstream.append(max(0.0, 4.0 + state[u] * 6.0) if u in state else 0.0)
            upstream_rainfall = max(upstream[1:]) if len(upstream) > 1 else 0.0

            rows.append(
                {
                    "village": v,
                    "elevation_m": VILLAGE_ELEVATIONS[v],
                    "rainfall_intensity": round(rainfall, 2),
                    "soil_moisture": round(soil, 2),
                    "upstream_rainfall": round(upstream_rainfall, 2),
                    "historical_susceptibility": historical_susceptibility[v],
                    "day_index": day,
                }
            )

    df = pd.DataFrame(rows)
    p = _true_hazard_probability(
        df["rainfall_intensity"].to_numpy(),
        df["soil_moisture"].to_numpy(),
        df["upstream_rainfall"].to_numpy(),
        df["historical_susceptibility"].to_numpy(),
    )
    df["event"] = (rng.random(len(df)) < p).astype(int)
    return df


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-days", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=str(Path(__file__).parent / "artifacts" / "synthetic_dataset.csv"))
    args = parser.parse_args()

    df = generate_synthetic_dataset(n_days=args.n_days, seed=args.seed)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} synthetic rows ({df['event'].sum()} positive, "
          f"{df['event'].mean():.1%} positive rate) to {out_path}")
