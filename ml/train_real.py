"""
ML pipeline trained/evaluated on the REAL, combined dataset — the real
counterpart to ml/train.py (which trains on synthetic data only).

**Read this before trusting any number this script prints.**

Two real, cited sources are merged by ml/merge_real_training_data.py into
ml/data/real_flood_training_features_combined.csv (see that script's own
docstring):
  - 144 POINT-precision rows (36 real GLOF events + the app's own 2 seeded
    events) — each positive's coordinates are the actual glacial lake or
    seeded village.
  - 927 DISTRICT-CENTROID-precision rows (309 real India Flood Inventory
    events, geocoded via ml/geocode_ifi_candidates.py) — each positive's
    coordinates are a real OpenStreetMap Nominatim geocode of its
    district, genuinely real but coarser than point precision; the actual
    flood/landslide site could be tens of km from the district centroid
    used to pull rainfall.

**1,071 total rows (345 positive)** is a real, substantial jump from the
previous 144-row/36-positive real dataset (itself already a jump from
Phase 5's 1 real event) — but read what it still ISN'T:

- Still not deployment-grade. More real rows narrows the noise on these
  metrics; it does not, by itself, cross the bar for a life-safety warning
  system — see the honest recall/false-negative numbers this script prints
  before assuming otherwise.
- The two source types are NOT equally precise (see above) — this script
  reports a precision-stratified breakdown on the test set specifically so
  the district-centroid rows' real, coarser-location noise can't hide
  inside one blended number.
- Only rainfall (NASA POWER, real) + elevation are real features here — no
  real soil moisture or upstream-catchment-rainfall, same limitation as
  before (those need ground sensors or a shared catchment topology this
  scattered event list doesn't have).
- "Negative" means "no event recorded in the source inventory at this
  location on this date," not "confirmed no event occurred" — same caveat
  as before, now covering two source inventories.
- Events span 4 countries (GLOF subset) and India's Himalayan hill states
  (IFI subset) at very different elevations than either pilot valley
  (900-3,600m) — still NOT specific to the Mandakini or Chamoli catchments.

`GET /api/v1/version`'s `ml_layer` field is NOT changed by this script —
deploying any model behind the live risk API is a separate, deliberately
cautious decision documented in docs/ML_Methodology.md, not something a
training run makes on its own.

Two real analyses, not one, for a fairer picture at this larger N — and
this turned out to matter, not just be due diligence:
  1. A single temporal train/test split (last 25% by date) — the same
     methodology as the prior 144-row run.
  2. A 4-fold expanding-window temporal cross-validation (never trains on
     future data relative to its own test fold) — reports mean +/- std,
     which a single split can't.

**These two disagree, and the disagreement is itself a real, disclosed
finding, not noise to average away.** The India Flood Inventory source
data documents recent years far more thoroughly than older ones (2022-2023
alone contribute ~19% of all rows in this combined dataset, almost all of
them positive), so a single "last 25% by date" split lands mostly in that
recent, positive-heavy tail — its test set ends up ~77% positive, nothing
like the full dataset's ~32% positive rate, which flatters recall/precision
in a way that isn't representative. The 4-fold CV's earlier folds don't
have this problem and show meaningfully worse (more honest) numbers. THE
CV AGGREGATE, NOT THE SINGLE SPLIT, IS TREATED AS THE HEADLINE RESULT below
for exactly this reason — the single split is still reported (so this run
is comparable to the prior 144-row one), but is flagged, not led with.

Two real models compared honestly, not one assumed better:
  - LogisticRegression (same choice as the 144-row run) — still the more
    interpretable, lower-variance choice.
  - XGBoost — defensible now that N=1,071 (was not, at N=144; see the
    144-row run's own docstring for why it was skipped then), but kept
    deliberately shallow/regularized (few, shallow trees) rather than
    tuned, since no held-out validation set exists to tune against without
    further shrinking an already-small test fold.
Whichever genuinely has the lower false-negative rate on the primary split
is reported as the honest pick — never assumed by model sophistication.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

DATA_DIR = Path(__file__).parent / "data"
COMBINED_PATH = DATA_DIR / "real_flood_training_features_combined.csv"
LEGACY_PATH = DATA_DIR / "real_flood_training_features.csv"  # pre-merge fallback
ARTIFACT_PATH = Path(__file__).parent / "artifacts" / "real_data_metrics.json"

FEATURES = [
    "max_daily_rainfall_mm",
    "rainfall_intensity_mm_hr_proxy",
    "rainfall_cumulative_3day_mm",
    "rainfall_cumulative_7day_mm",
    "elevation_m",
]

N_CV_FOLDS = 4


def temporal_split(df: pd.DataFrame, test_frac: float = 0.25) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("date").reset_index(drop=True)
    cutoff_idx = int(len(df) * (1 - test_frac))
    train, test = df.iloc[:cutoff_idx], df.iloc[cutoff_idx:]
    assert train["date"].max() <= test["date"].min(), "temporal split leaked future into training"
    return train, test


def honest_metrics(y_true, y_pred, y_prob) -> dict:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        "n_test": int(len(y_true)),
        "n_test_positive": int(sum(y_true)),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 3),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 3),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 3),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 3) if len(set(y_true)) > 1 else None,
        "false_alarm_rate": round(float(fp / (fp + tn)), 3) if (fp + tn) > 0 else None,
        "false_negative_rate": round(float(fn / (fn + tp)), 3) if (fn + tp) > 0 else None,
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def _fit_logreg(X_train, y_train):
    model = LogisticRegression(class_weight="balanced", max_iter=1000)
    model.fit(X_train, y_train)
    return model


def _fit_xgb(X_train, y_train, seed: int = 42):
    pos = max(1, int(y_train.sum()))
    neg = max(1, int(len(y_train) - pos))
    # Deliberately shallow/regularized (few, shallow trees) — no held-out
    # validation fold exists to tune hyperparameters against without
    # further shrinking an already-small test set, so this is a
    # conservative, documented default, not a tuned result.
    model = XGBClassifier(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.1,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=neg / pos,
        random_state=seed,
        eval_metric="logloss",
    )
    model.fit(X_train, y_train)
    return model


def _stratified_breakdown(test: pd.DataFrame, y_pred: np.ndarray, y_prob: np.ndarray) -> dict:
    """Honest check: does the district-centroid rows' coarser location
    precision measurably change how the model does on them, vs. the
    point-precision rows? Reported separately so it can't hide inside one
    blended number."""
    out = {}
    test = test.reset_index(drop=True)
    for precision_tag in ("point_source", "district_centroid"):
        mask = (test["coordinate_precision"] == precision_tag).to_numpy()
        n = int(mask.sum())
        if n == 0:
            out[precision_tag] = {"n_test": 0}
            continue
        y_true_sub = test.loc[mask, "label"].to_numpy()
        out[precision_tag] = honest_metrics(y_true_sub, y_pred[mask], y_prob[mask])
    return out


def _expanding_window_cv(df: pd.DataFrame, fit_fn, n_folds: int = N_CV_FOLDS) -> dict:
    """Never trains on a fold's own future — each fold's test window is a
    later, non-overlapping date slice than everything used to train it.
    Reports mean +/- std across folds, which a single split can't."""
    df = df.sort_values("date").reset_index(drop=True)
    n = len(df)
    # First fold needs a real training set; folds after that each add one
    # more slice of real data to train on before testing on the next.
    fold_bounds = np.linspace(int(n * 0.4), n, n_folds + 1).astype(int)

    fold_metrics = []
    for i in range(n_folds):
        train_end, test_end = fold_bounds[i], fold_bounds[i + 1]
        train, test = df.iloc[:train_end], df.iloc[train_end:test_end]
        if test["label"].nunique() < 2 or train["label"].nunique() < 2:
            continue  # a fold with only one class can't report roc_auc honestly

        scaler = StandardScaler()
        X_train = scaler.fit_transform(train[FEATURES])
        X_test = scaler.transform(test[FEATURES])
        y_train, y_test = train["label"].to_numpy(), test["label"].to_numpy()

        model = fit_fn(X_train, y_train)
        y_prob = model.predict_proba(X_test)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)
        fold_metrics.append(honest_metrics(y_test, y_pred, y_prob))

    if not fold_metrics:
        return {"folds_run": 0, "note": "No fold had both classes present — CV skipped."}

    agg = {}
    for key in ("precision", "recall", "f1", "roc_auc", "false_alarm_rate", "false_negative_rate"):
        vals = [m[key] for m in fold_metrics if m[key] is not None]
        agg[key] = {
            "mean": round(float(np.mean(vals)), 3) if vals else None,
            "std": round(float(np.std(vals)), 3) if len(vals) > 1 else None,
        }
    return {"folds_run": len(fold_metrics), "per_fold": fold_metrics, "aggregate": agg}


def main() -> None:
    if COMBINED_PATH.exists():
        data_path = COMBINED_PATH
    elif LEGACY_PATH.exists():
        print(f"[warning] {COMBINED_PATH} not found — falling back to the smaller, pre-merge "
              f"{LEGACY_PATH}. Run ml/geocode_ifi_candidates.py, ml/backfill_ifi_weather.py, "
              "then ml/merge_real_training_data.py to get the full combined dataset.")
        data_path = LEGACY_PATH
    else:
        raise SystemExit(
            f"Neither {COMBINED_PATH} nor {LEGACY_PATH} found. Run ml/assemble_real_events.py, "
            "ml/backfill_real_weather.py, ml/geocode_ifi_candidates.py, ml/backfill_ifi_weather.py, "
            "then ml/merge_real_training_data.py first (several of these make live network calls, "
            "so none run automatically here)."
        )

    df = pd.read_csv(data_path).dropna(subset=FEATURES + ["label"])
    if "coordinate_precision" not in df.columns:
        df["coordinate_precision"] = "point_source"  # legacy-file fallback
    print(f"Loaded {len(df)} real rows ({(df['label']==1).sum()} positive) from {data_path.name} after dropping incomplete rows.")

    train, test = temporal_split(df)
    print(f"Primary temporal split: {len(train)} train rows (through {train['date'].max()}), "
          f"{len(test)} test rows (from {test['date'].min()}).")

    scaler = StandardScaler()
    X_train = scaler.fit_transform(train[FEATURES])
    X_test = scaler.transform(test[FEATURES])
    y_train, y_test = train["label"].to_numpy(), test["label"].to_numpy()

    models = {
        "LogisticRegression": _fit_logreg(X_train, y_train),
        "XGBoost": _fit_xgb(X_train, y_train),
    }

    model_reports = {}
    for name, model in models.items():
        y_prob = model.predict_proba(X_test)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)
        metrics = honest_metrics(y_test, y_pred, y_prob)
        stratified = _stratified_breakdown(test, y_pred, y_prob)
        cv = _expanding_window_cv(df, _fit_logreg if name == "LogisticRegression" else _fit_xgb)

        if name == "LogisticRegression":
            importances = dict(zip(FEATURES, [round(float(c), 3) for c in model.coef_[0]]))
        else:
            importances = dict(zip(FEATURES, [round(float(c), 3) for c in model.feature_importances_]))

        model_reports[name] = {
            "headline_expanding_window_cv": cv,
            "single_split_metrics_not_headline": metrics,
            "single_split_by_coordinate_precision": stratified,
            "feature_importance_or_coefficients": importances,
        }
        print(f"\n=== {name} — 4-fold expanding-window CV (headline; see module docstring for why) ===")
        print(json.dumps(cv.get("aggregate", cv), indent=2))
        print(f"\n=== {name} — single temporal split (flagged, not headline — see module docstring) ===")
        print(json.dumps(metrics, indent=2))

    # Honest pick: lower MEAN false-negative rate across the 4 CV folds
    # wins — the headline metric (see module docstring for why CV, not the
    # single split, is treated as headline), never assumed by model
    # sophistication. Ties keep LogisticRegression (the simpler, lower-
    # variance, more interpretable choice) as the honest default.
    def _cv_fnr(report: dict) -> float:
        agg = report["headline_expanding_window_cv"].get("aggregate")
        if not agg or agg["false_negative_rate"]["mean"] is None:
            return 1.0
        return agg["false_negative_rate"]["mean"]

    fnr = {name: _cv_fnr(report) for name, report in model_reports.items()}
    better_model = min(fnr, key=lambda k: (fnr[k], k != "LogisticRegression"))

    report = {
        "dataset": str(data_path.relative_to(Path(__file__).parent)),
        "n_total_rows": int(len(df)),
        "n_positive": int((df["label"] == 1).sum()),
        "n_negative": int((df["label"] == 0).sum()),
        "n_point_source": int((df["coordinate_precision"] == "point_source").sum()),
        "n_district_centroid": int((df["coordinate_precision"] == "district_centroid").sum()),
        "date_range": [str(df["date"].min()), str(df["date"].max())],
        "features_used": FEATURES,
        "models": model_reports,
        "honest_pick_by_lowest_false_negative_rate": better_model,
        "caveats": [
            f"{len(df)} rows ({int((df['label']==1).sum())} positive) is a real jump from the prior 144-row/36-positive "
            "real dataset, but still small for a rare-event classifier at deployment stakes — treat all metrics as "
            "informative point estimates, not validated performance.",
            "The single temporal split's test set is ~77% positive (vs. ~32% for the full dataset) because the IFI "
            "source documents recent years far more thoroughly than older ones — that split's rosier numbers are "
            "flagged, NOT the headline; the 4-fold CV aggregate is the honest headline result. See module docstring.",
            "927 of these rows carry DISTRICT-CENTROID coordinates (real Nominatim geocodes, genuinely real but "
            "coarser than point precision) — see single_split_by_coordinate_precision on each model, though note "
            "the point_source stratum has only 12 test rows in the single split (too few to read confidently on "
            "its own — reported for transparency, not as a validated point-vs-district comparison).",
            "Events span 4 countries (GLOF subset) and India's Himalayan hill states (IFI subset) at elevations "
            "900-5,000m — NOT specific to either pilot valley's catchment.",
            "No real soil-moisture or upstream-catchment-rainfall features exist for this dataset (unlike the "
            "Phase 4 baseline).",
            "Negative examples mean 'no event recorded in the source inventory', not 'confirmed no event occurred'.",
            "XGBoost's hyperparameters here are a conservative, documented default, not tuned against a held-out "
            "validation fold — there isn't enough real data to spare a third split without shrinking the test set "
            "past the point of a trustworthy read.",
            "This model is NOT deployed behind GET /risk/* — see docs/ML_Methodology.md for the deployment decision.",
        ],
    }

    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(json.dumps(report, indent=2))

    print(f"\nHonest pick by lowest MEAN false-negative rate across the 4 CV folds (headline metric): {better_model}")
    print(f"Full report written to {ARTIFACT_PATH}")


if __name__ == "__main__":
    main()
