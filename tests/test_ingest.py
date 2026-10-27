"""Tests for CSV ingestion (Oct 27 round) and generator balance."""

import pytest
from fastapi.testclient import TestClient

from payguard.api import app
from payguard.ingest import parse_transactions_csv, sample_csv
from payguard.model import score_transaction, train

client = TestClient(app)

PAYPAL_STYLE = """transaction_id,gross_amount,buyer_account_age_days,buyer_email
PAY-1,450.00,3,buyer_a@example.com
PAY-2,42.50,800,buyer_b@example.com
"""


def test_paypal_style_headers_parse_and_score():
    txns = parse_transactions_csv(PAYPAL_STYLE)
    assert len(txns) == 2
    assert txns[0]["id"] == "PAY-1"
    assert txns[0]["amount"] == 450.00
    assert txns[0]["buyer"] == "buyer_a@example.com"
    scored = [score_transaction(t) for t in txns]
    assert scored[0]["risk_score"] > scored[1]["risk_score"]


def test_partial_csv_scores_with_defaults():
    txns = parse_transactions_csv("amount\n120.00\n")
    assert len(txns) == 1
    r = score_transaction(txns[0])
    assert r["risk_band"] in ("LOW", "MEDIUM", "HIGH")


def test_missing_amount_column_rejected():
    with pytest.raises(ValueError, match="no amount column"):
        parse_transactions_csv("buyer_email\nsomeone@example.com\n")


def test_bad_amount_row_rejected_with_row_number():
    with pytest.raises(ValueError, match="Row 2"):
        parse_transactions_csv("amount\nnot-a-number\n")


def test_empty_csv_rejected():
    with pytest.raises(ValueError, match="no data rows"):
        parse_transactions_csv("amount\n")


def test_sample_csv_round_trips():
    txns = parse_transactions_csv(sample_csv())
    assert len(txns) == 6
    assert all(t["amount"] > 0 for t in txns)


def test_upload_csv_api():
    r = client.post(
        "/upload-csv",
        files={"file": ("txns.csv", PAYPAL_STYLE, "text/csv")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    scores = [t["risk_score"] for t in body["transactions"]]
    assert scores == sorted(scores, reverse=True), "riskiest first"


def test_upload_csv_api_rejects_bad_file():
    r = client.post(
        "/upload-csv",
        files={"file": ("bad.csv", "nope\n1\n", "text/csv")},
    )
    assert r.status_code == 400


def test_sample_csv_api():
    r = client.get("/sample-csv")
    assert r.status_code == 200
    assert len(parse_transactions_csv(r.text)) == 6


def test_generator_no_longer_single_feature_dominated():
    """Oct 27 fix: buyer_account_age_days carried 0.73 of importance in v1
    because risky/safe account-age ranges did not overlap. After the overlap
    fix, no single feature may dominate, and several must matter."""
    meta = train()
    importance = meta["importance"]
    assert max(importance.values()) < 0.60
    assert sum(1 for v in importance.values() if v > 0.05) >= 3
    assert meta["metrics"]["roc_auc"] > 0.85, "still a useful model"
