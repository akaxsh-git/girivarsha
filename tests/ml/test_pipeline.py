"""
Phase 5 tests. These test the ML PIPELINE MECHANICS (feature assembly,
temporal splitting, the model-comparison ladder, honest metric reporting)
against synthetic data — not real flood prediction skill, which cannot be
validated with only one real historical event. See
ml/generate_synthetic_training_data.py and docs/ML_Methodology.md for the
full reasoning.

Needs ml/requirements.txt installed (`pip install -r ml/requirements.txt`)
— kept separate from the main backend test run since the running API never
imports this code.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from generate_synthetic_training_data import VILLAGE_ELEVATIONS, generate_synthetic_dataset  # noqa: E402
from train import FEATURE_LADDER, temporal_split, train_and_evaluate  # noqa: E402


def test_village_elevations_match_seed_script():
    """The one real thing borrowed into the synthetic generator (village
    elevations) must never silently drift from the actual seeded data."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from seed_pilot_region import VILLAGES  # noqa: E402  (import-only — module-level code has no DB side effects)

    real_elevations = {v["name"]: v["elevation_m"] for v in VILLAGES}
    assert VILLAGE_ELEVATIONS == real_elevations, (
        "ml/generate_synthetic_training_data.py's VILLAGE_ELEVATIONS has drifted from "
        "scripts/seed_pilot_region.py — update one to match the other."
    )


def test_synthetic_dataset_has_no_missing_values_and_expected_shape():
    df = generate_synthetic_dataset(n_days=300, seed=1)
    assert len(df) == 300 * len(VILLAGE_ELEVATIONS)
    assert not df.isna().any().any(), "synthetic dataset must never contain NaNs"
    assert set(df["village"].unique()) == set(VILLAGE_ELEVATIONS.keys())
    assert df["event"].isin([0, 1]).all()
    # Rare-event class imbalance is the whole point (problem-statement item 10) —
    # a dataset that's ~50/50 wouldn't exercise the imbalance-handling code path.
    positive_rate = df["event"].mean()
    assert 0.02 < positive_rate < 0.35, f"synthetic positive rate {positive_rate:.2%} isn't a realistic rare-event rate"


def test_temporal_split_never_leaks_future_into_training():
    df = generate_synthetic_dataset(n_days=300, seed=1)
    train, test = temporal_split(df, test_frac=0.2)
    assert len(train) > 0 and len(test) > 0
    assert train["day_index"].max() <= test["day_index"].min()


def test_feature_ladder_is_strictly_additive():
    """Each rung of the comparison ladder (item 10) must be a superset of the
    previous one — otherwise it's not actually testing 'does adding this
    source help', it's testing something else."""
    names = list(FEATURE_LADDER.keys())
    for prev, nxt in zip(names, names[1:]):
        assert set(FEATURE_LADDER[prev]).issubset(set(FEATURE_LADDER[nxt])), (
            f"{nxt} must be a superset of {prev} for the comparison to be meaningful"
        )


def test_pipeline_beats_random_on_synthetic_ground_truth():
    """The real point of this test: with a KNOWN synthetic ground-truth
    function, a correctly-implemented pipeline must learn to do meaningfully
    better than random guessing (AUC 0.5). If this ever drops to ~0.5, the
    pipeline itself is broken (e.g. a label leak, a broken split, or a
    feature/label mismatch) — this is a smoke test of pipeline CORRECTNESS,
    not of real-world predictive skill (see module + file docstrings)."""
    df = generate_synthetic_dataset(n_days=1200, seed=42)
    results = train_and_evaluate(df, seed=42)

    assert set(results.keys()) == set(FEATURE_LADDER.keys())
    for name, metrics in results.items():
        assert metrics["roc_auc"] is not None
        assert metrics["roc_auc"] > 0.55, f"{name} scored no better than random (AUC={metrics['roc_auc']}) — pipeline likely broken"
        for key in ("precision", "recall", "f1", "false_alarm_rate", "false_negative_rate", "n_test", "n_positive_test"):
            assert key in metrics, f"{name} is missing required honest-reporting field {key!r}"
