"""Train, persist, and explain the PayGuard risk model."""

import json
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, roc_auc_score
from xgboost import XGBClassifier

from .data import generate
from .features import (
    FACTOR_TEXT,
    FEATURES,
    recommended_action,
    risk_band,
    transaction_to_features,
)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "model.joblib")
META_PATH = os.path.join(os.path.dirname(__file__), "..", "model_meta.json")


def train(seed: int = 42) -> dict:
    df = generate(seed=seed)
    X, y = df[FEATURES], df["label"]
    split = int(len(df) * 0.8)
    model = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="logloss",
        random_state=seed,
    )
    model.fit(X.iloc[:split], y.iloc[:split])
    proba = model.predict_proba(X.iloc[split:])[:, 1]
    pred = (proba >= 0.5).astype(int)
    baseline = df.iloc[:split][df.iloc[:split]["label"] == 0][FEATURES].median()
    meta = {
        "features": FEATURES,
        "importance": dict(
            zip(FEATURES, [round(float(v), 4) for v in model.feature_importances_])
        ),
        "baseline_median": {f: float(baseline[f]) for f in FEATURES},
        "metrics": {
            "accuracy": round(float(accuracy_score(y.iloc[split:], pred)), 4),
            "roc_auc": round(float(roc_auc_score(y.iloc[split:], proba)), 4),
            "test_size": int(len(df) - split),
        },
    }
    joblib.dump(model, MODEL_PATH)
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)
    return meta


def load():
    if not os.path.exists(MODEL_PATH):
        train()
    model = joblib.load(MODEL_PATH)
    with open(META_PATH) as f:
        meta = json.load(f)
    return model, meta


def explain(txn: dict, meta: dict) -> list:
    """Top contributing factors: deviation from the safe baseline, weighted
    by the model's global feature importance. Returns readable factor dicts."""
    feats = transaction_to_features(txn)
    baseline = meta["baseline_median"]
    importance = meta["importance"]
    scored = []
    for name, value in zip(FEATURES, feats):
        # hour_of_day is circular (23:00 is adjacent to 00:00) and a weak
        # signal (importance ~0.01); surfacing it as a "risk factor" for
        # otherwise safe payments reads as a false alarm, so it is excluded
        # from explanations entirely.
        if name == "hour_of_day":
            continue
        base = baseline[name]
        # Relative deviation; binary flags count fully when set.
        if base == 0:
            deviation = 1.0 if value else 0.0
        else:
            deviation = max(0.0, (value - base) / abs(base)) if name not in (
                "buyer_account_age_days", "buyer_orders_30d") else max(
                0.0, (base - value) / abs(base))
        # Binary risk flags and dispute counts only push risk upward when set.
        if name in ("country_mismatch", "currency_mismatch", "is_digital_goods"):
            deviation = 1.0 if value else 0.0
        if name == "buyer_disputes_90d":
            deviation = min(1.0, value / 2.0)
        weight = importance.get(name, 0.0) * deviation
        if weight > 0:
            scored.append((weight, name))
    scored.sort(reverse=True)
    return [
        {"factor": FACTOR_TEXT[name][0], "detail": FACTOR_TEXT[name][1]}
        for _, name in scored[:3]
    ]


def plain_summary(score: float, factors: list, txn: dict) -> str:
    band = risk_band(score)
    if not factors:
        return (
            f"Low risk ({score:.0%}): this payment looks like your usual orders — "
            "no unusual signals. Safe to ship."
        )
    reasons = "; ".join(f["detail"] for f in factors)
    return (
        f"{band} risk ({score:.0%}): {reasons}. "
        f"Recommended action: {recommended_action(score).lower()}."
    )


def score_transaction(txn: dict) -> dict:
    model, meta = load()
    feats = np.array([transaction_to_features(txn)])
    score = float(model.predict_proba(feats)[0, 1])
    # Factors are only meaningful when the model actually sees risk. A
    # transaction the model scores near zero may deviate on a minor feature,
    # but listing "risk factors" next to a 0% score would be a false alarm —
    # so below MEDIUM the explanation is empty and the summary says so.
    factors = explain(txn, meta) if score >= 0.4 else []
    return {
        "id": txn.get("id", "TXN-?"),
        "amount": float(txn.get("amount", 0)),
        "risk_score": round(score, 4),
        "risk_band": risk_band(score),
        "action": recommended_action(score),
        "factors": factors,
        "summary": plain_summary(score, factors, txn),
    }
