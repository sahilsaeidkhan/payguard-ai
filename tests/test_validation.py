"""Input-validation tests for PayGuard AI v7. Run: python -m pytest tests/ -q"""

import pytest
from fastapi.testclient import TestClient

from payguard.api import app

client = TestClient(app)


@pytest.mark.parametrize(
    "bad",
    [
        {"amount": 0},  # amount must be > 0
        {"amount": -10.0},
        {"amount": 50.0, "buyer_account_age_days": -5},
        {"amount": 50.0, "buyer_orders_30d": -1},
        {"amount": 50.0, "seller_velocity_1h": -1},
        {"amount": 50.0, "country_mismatch": 2},  # flags are 0/1 only
        {"amount": 50.0, "currency_mismatch": -1},
        {"amount": 50.0, "is_digital_goods": 2},
        {"amount": 50.0, "hour_of_day": 24},
        {"amount": 50.0, "hour_of_day": -1},
        {"amount": 50.0, "buyer_disputes_90d": -1},
        {"amount": 50.0, "seller_avg_order_value": 0},
    ],
)
def test_score_rejects_bad_input(bad):
    assert client.post("/score", json=bad).status_code == 422


@pytest.mark.parametrize(
    "good",
    [
        {"amount": 50.0},  # defaults only
        {"amount": 50.0, "buyer_account_age_days": 0, "hour_of_day": 0},
        {"amount": 50.0, "hour_of_day": 23, "country_mismatch": 1},
    ],
)
def test_score_accepts_edge_values(good):
    r = client.post("/score", json=good)
    assert r.status_code == 200
    assert r.json()["risk_band"] in ("LOW", "MEDIUM", "HIGH")


def test_transactions_n_bounds():
    assert client.get("/transactions?n=0").status_code == 422
    assert client.get("/transactions?n=101").status_code == 422
    assert len(client.get("/transactions?n=5").json()) == 5


def test_paypal_order_rejects_bad_currency_before_paypal_call():
    # Invalid currency must fail validation (422), not reach PayPal (503/502).
    r = client.post("/paypal/order", json={"amount": 10.0, "currency": "US"})
    assert r.status_code == 422
    r = client.post(
        "/paypal/order", json={"amount": 10.0, "seller_avg_order_value": 0}
    )
    assert r.status_code == 422
