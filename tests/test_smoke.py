"""Smoke tests for PayGuard AI v1. Run: python -m pytest tests/ -q"""

from fastapi.testclient import TestClient

from payguard.api import app
from payguard.data import generate, sample_transactions
from payguard.model import score_transaction, train

client = TestClient(app)


def test_data_has_labels():
    df = generate(200)
    assert set(df["label"].unique()) <= {0, 1}
    assert len(df) == 200


def test_model_trains_and_scores():
    train()
    risky = {
        "id": "T-RISKY",
        "amount": 400.0,
        "seller_avg_order_value": 55.0,
        "buyer_account_age_days": 2,
        "buyer_orders_30d": 0,
        "country_mismatch": 1,
        "buyer_disputes_90d": 2,
    }
    safe = {
        "id": "T-SAFE",
        "amount": 45.0,
        "seller_avg_order_value": 55.0,
        "buyer_account_age_days": 900,
        "buyer_orders_30d": 5,
        "country_mismatch": 0,
        "buyer_disputes_90d": 0,
    }
    r_risky = score_transaction(risky)
    r_safe = score_transaction(safe)
    assert r_risky["risk_score"] > r_safe["risk_score"]
    assert r_risky["factors"], "risky transaction must carry explanations"
    assert "HOLD" in r_risky["action"] or "REVIEW" in r_risky["action"]
    assert r_safe["risk_band"] == "LOW"


def test_api_endpoints():
    assert client.get("/health").status_code == 200
    txns = client.get("/transactions").json()
    assert len(txns) == 12
    assert all("summary" in t and "risk_score" in t for t in txns)
    r = client.post("/score", json={"amount": 50.0}).json()
    assert r["risk_band"] in ("LOW", "MEDIUM", "HIGH")


def test_demo_queue_sorts_by_risk():
    scored = [score_transaction(t) for t in sample_transactions()]
    scores = sorted((s["risk_score"] for s in scored), reverse=True)
    assert scores[0] >= scores[-1]
