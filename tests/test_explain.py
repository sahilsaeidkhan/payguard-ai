"""Tests for PayGuard AI v4 perturbation explanations. Run: python -m pytest tests/ -q"""

from payguard.features import FACTOR_TEXT
from payguard.model import explain, load, score_transaction, train

RISKY = {
    "id": "T-RISKY",
    "amount": 400.0,
    "seller_avg_order_value": 55.0,
    "buyer_account_age_days": 2,
    "buyer_orders_30d": 0,
    "country_mismatch": 1,
    "buyer_disputes_90d": 2,
}

SAFE = {
    "id": "T-SAFE",
    "amount": 45.0,
    "seller_avg_order_value": 55.0,
    "buyer_account_age_days": 900,
    "buyer_orders_30d": 5,
    "country_mismatch": 0,
    "buyer_disputes_90d": 0,
}

KNOWN_FACTORS = {v[0] for v in FACTOR_TEXT.values()}


def test_perturbation_explains_risky_transaction():
    train()
    model, meta = load()
    factors = explain(RISKY, meta, model)
    assert factors, "risky transaction must carry model-grounded explanations"
    assert len(factors) <= 3
    assert all(f["factor"] in KNOWN_FACTORS for f in factors)
    assert all("detail" in f for f in factors)


def test_contributions_descending_when_present():
    train()
    model, meta = load()
    factors = explain(RISKY, meta, model)
    contribs = [f["contribution"] for f in factors if "contribution" in f]
    assert contribs == sorted(contribs, reverse=True)
    assert all(c > 0 for c in contribs)


def test_safe_transaction_has_no_factors():
    result = score_transaction(SAFE)
    assert result["factors"] == []
    assert "Safe to ship" in result["summary"]


def test_risky_summary_names_action():
    result = score_transaction(RISKY)
    assert result["factors"]
    assert result["action"].split(" ")[0] in ("HOLD", "REVIEW")
    assert "risk" in result["summary"].lower()
