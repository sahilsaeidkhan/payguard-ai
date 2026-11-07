"""Tests for the seller decision log (v5)."""

import pytest
from fastapi.testclient import TestClient

import payguard.decisions as decisions_mod
from payguard.api import app
from payguard.decisions import (
    configure_storage,
    decision_summary,
    list_decisions,
    reset_log,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path):
    """Point decision persistence at a temp file per test, restore the
    default path afterwards — tests must never touch the real file."""
    configure_storage(tmp_path / "decisions.json")
    yield
    configure_storage(decisions_mod._DEFAULT_PATH)
    reset_log()


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


def test_redecision_supersedes_instead_of_double_counting():
    """v9: one payment, one current decision — changing your mind is not
    a second decision, and the queue/log must show the latest one only."""
    client.post("/decisions", json={"txn_id": "PAY-9", "decision": "HOLD",
                                    "risk_band": "HIGH"})
    r = client.post("/decisions", json={"txn_id": "PAY-9", "decision": "APPROVE",
                                        "risk_band": "HIGH"})
    assert r.status_code == 201
    log = client.get("/decisions").json()
    assert log["summary"]["total"] == 1
    assert log["summary"]["by_decision"] == {
        "HOLD": 0, "REVIEW": 0, "APPROVE": 1}
    assert len(log["decisions"]) == 1
    assert log["decisions"][0]["decision"] == "APPROVE"


def test_redecided_payment_moves_to_most_recent():
    client.post("/decisions", json={"txn_id": "A", "decision": "HOLD"})
    client.post("/decisions", json={"txn_id": "B", "decision": "REVIEW"})
    client.post("/decisions", json={"txn_id": "A", "decision": "APPROVE"})
    log = client.get("/decisions").json()
    assert [d["txn_id"] for d in log["decisions"]] == ["A", "B"]
    assert log["summary"]["total"] == 2


def test_module_helpers():
    from payguard.decisions import record_decision
    record_decision("X", "REVIEW", "MEDIUM", 0.5, 120.0)
    assert decision_summary()["by_decision"]["REVIEW"] == 1
    assert list_decisions()[0]["txn_id"] == "X"


def test_decisions_survive_a_restart(tmp_path):
    """v11: a HOLD recorded before an API restart is still there after it
    — persistence round-trips through the JSON file on disk."""
    path = tmp_path / "decisions.json"
    configure_storage(path)
    client.post("/decisions", json={"txn_id": "PAY-11", "decision": "HOLD",
                                    "risk_band": "HIGH", "risk_score": 0.9,
                                    "amount": 400.0})
    assert path.exists()
    # Simulate a restart: fresh in-memory state, same file.
    configure_storage(path)
    log = client.get("/decisions").json()
    assert log["summary"]["total"] == 1
    assert log["decisions"][0]["txn_id"] == "PAY-11"
    assert log["decisions"][0]["decision"] == "HOLD"


def test_corrupt_persisted_file_does_not_break_the_api(tmp_path):
    """v11: a damaged decisions.json starts the log empty instead of
    crashing the API — persistence is best-effort by design."""
    path = tmp_path / "decisions.json"
    path.write_text("{not valid json", encoding="utf-8")
    configure_storage(path)
    r = client.post("/decisions", json={"txn_id": "PAY-12",
                                        "decision": "APPROVE"})
    assert r.status_code == 201
    assert client.get("/decisions").json()["summary"]["total"] == 1


def test_export_csv(tmp_path):
    """v11: GET /decisions/export returns the log as CSV, most recent
    first, with a header row; empty log exports just the header."""
    empty = client.get("/decisions/export")
    assert empty.status_code == 200
    assert "text/csv" in empty.headers["content-type"]
    assert empty.text.strip() == (
        "txn_id,decision,risk_band,risk_score,amount,decided_at")
    client.post("/decisions", json={"txn_id": "A", "decision": "APPROVE",
                                    "risk_band": "LOW", "risk_score": 0.1,
                                    "amount": 20.0})
    client.post("/decisions", json={"txn_id": "B", "decision": "HOLD",
                                    "risk_band": "HIGH", "risk_score": 0.95,
                                    "amount": 300.0})
    r = client.get("/decisions/export")
    lines = r.text.strip().splitlines()
    assert len(lines) == 3  # header + 2 decisions
    assert lines[1].startswith("B,HOLD,HIGH,0.95,300.0,")
    assert lines[2].startswith("A,APPROVE,LOW,0.1,20.0,")
