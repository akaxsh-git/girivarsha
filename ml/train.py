"""
Phase 5 ML pipeline: trains the model-comparison ladder the problem
statement asks for (item 10) — rainfall-only vs. +soil vs. +terrain vs. all
sources — and reports honest metrics (precision/recall/F1/ROC-AUC/false-
alarm rate/false-negative rate), never accuracy alone (misleading under the
rare-event class imbalance this domain has).

**Read this before trusting any number this script prints**: it trains on
SYNTHETIC data (ml/generate_synthetic_training_data.py) because the real
pilot region has exactly one recorded historical event — not enough to
train or validate anything real. This script's job is to prove the
pipeline mechanics are correct (splitting, feature ladders, metrics), not
to produce a deployable flood model. See docs/ML_Methodology.md and
docs/Limitations.md. `GET /api/v1/version`'s `ml_layer` field reports this
same status — the ML layer is NOT used by the live risk API
(GET /risk/* still runs entirely on the Phase 4 baseline).

Temporal split: the last `test_frac` of `day_index` values become the test
set — never a random shuffle, per the problem statement's explicit
instruction for event-prediction tasks (item 10's "temporal train/test
splitting" note in docs/ML_Methodology.md).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from xgboost import XGBClassifier

from generate_synthetic_training_data import generate_synthetic_dataset

FEATURE_LADDER = {
    "A_rainfall_only": ["rainfall_intensity"],
    "B_plus_soil": ["rainfall_intensity", "soil_moisture"],
    "C_plus_terrain": ["rainfall_intensity", "soil_moisture", "elevation_m"],
    "D_all_sources": [
        "rainfall_intensity",
        "soil_moisture",
        "elevation_m",
        "upstream_rainfall",
        "historical_susceptibility",
    ],
}


def temporal_split(df: pd.DataFrame, test_frac: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    cutoff = df["day_index"].quantile(1 - test_frac)
    train = df[df["day_index"] <= cutoff]
    test = df[df["day_index"] > cutoff]
    assert train["day_index"].max() <= test["day_index"].min(), "temporal split leaked future into training"
    return train, test


def _metrics(y_true: np.ndarray, y_pred: np.ndarray, y_prob: np.ndarray) -> dict:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 4) if len(set(y_true)) > 1 else None,
        # False-alarm rate = false positives / all actual negatives — how often
        # we'd cry wolf. False-negative rate = missed events / all actual
        # positives — the one that matters most for a hazard system.
        "false_alarm_rate": round(float(fp / (fp + tn)), 4) if (fp + tn) > 0 else None,
        "false_negative_rate": round(float(fn / (fn + tp)), 4) if (fn + tp) > 0 else None,
        "n_test": int(len(y_true)),
        "n_positive_test": int(y_true.sum()),
    }


def train_and_evaluate(df: pd.DataFrame, test_frac: float = 0.2, seed: int = 42) -> dict:
    train, test = temporal_split(df, test_frac=test_frac)
    results = {}
    for model_name, features in FEATURE_LADDER.items():
        X_train, y_train = train[features], train["event"]
        X_test, y_test = test[features], test["event"]

        # scale_pos_weight compensates for the deliberate rare-event class
        # imbalance (per problem-statement item 10's "class imbalance
        # handling" requirement) rather than letting the model learn to
        # just always predict "no event" and look falsely accurate.
        pos = max(1, int(y_train.sum()))
        neg = max(1, int(len(y_train) - pos))
        model = XGBClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.1,
            scale_pos_weight=neg / pos,
            random_state=seed,
            eval_metric="logloss",
        )
        model.fit(X_train, y_train)
        y_prob = model.predict_proba(X_test)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)
        results[model_name] = {
            "features": features,
            **_metrics(y_test.to_numpy(), y_pred, y_prob),
        }
    return results


def main() -> None:
    df = generate_synthetic_dataset()
    results = train_and_evaluate(df)

    print("Phase 5 ML pipeline — SYNTHETIC data smoke test (see module docstring). "
          "Not a real flood model.\n")
    for name, metrics in results.items():
        print(f"{name}: {metrics}")

    out_path = Path(__file__).parent / "artifacts" / "metrics.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        {
            "warning": (
                "SYNTHETIC-DATA PIPELINE SMOKE TEST — not a validated flood model. "
                "See docs/ML_Methodology.md. Real training is blocked on insufficient "
                "labelled historical events (1 recorded event in the pilot region)."
            ),
            "results": results,
        },
        indent=2,
    ))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
