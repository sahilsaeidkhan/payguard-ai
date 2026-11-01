"""Tests for the seller decision log (v5)."""

from fastapi.testclient import TestClient

from payguard.api import app
from payguard.decisions import decision_summary, list_decisions, reset_log

client = TestClient(app)


def setup_function():
    reset_log()


def test_decision_recorded_and_listed():
    r = client.post("/decisions", json={
        "txn_id": "PAY-1", "decision": "hold",
        "risk_band": "HIGH", "risk_score": 0.99, "amount": 400.0})
    assert r.status_code == 201
    assert r.json()["decision"] == "HOLD"
    log = client.get("/decisions").json()
    assert log["summary"]["total"] == 1
    assert log["summary"]["by_decision"]["HOLD"] == 1
    assert log["decisions"][0]["txn_id"] == "PAY-1"


def test_invalid_decision_rejected():
    r = client.post("/decisions", json={
        "txn_id": "PAY-2", "decision": "SHIP_IT"})
    assert r.status_code == 400
    assert client.get("/decisions").json()["summary"]["total"] == 0


def test_most_recent_first_and_counts():
    client.post("/decisions", json={"txn_id": "A", "decision": "APPROVE"})
    client.post("/decisions", json={"txn_id": "B", "decision": "HOLD"})
    client.post("/decisions", json={"txn_id": "C", "decision": "HOLD"})
    log = client.get("/decisions").json()
    assert [d["txn_id"] for d in log["decisions"]] == ["C", "B", "A"]
    assert log["summary"]["by_decision"] == {
        "HOLD": 2, "REVIEW": 0, "APPROVE": 1}


def test_module_helpers():
    from payguard.decisions import record_decision
    record_decision("X", "REVIEW", "MEDIUM", 0.5, 120.0)
    assert decision_summary()["by_decision"]["REVIEW"] == 1
    assert list_decisions()[0]["txn_id"] == "X"
