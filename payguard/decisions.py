"""Seller decision log — the action half of the risk queue.

Scoring alone is a report; a seller workflow needs the decision recorded:
HOLD a risky payment before shipping, REVIEW a borderline one, APPROVE a
safe one. Decisions live in memory (the demo has no database by design —
restarting the API resets the log, which the dashboard states plainly).
"""

from datetime import datetime, timezone

VALID_DECISIONS = ("HOLD", "REVIEW", "APPROVE")

_log: list = []


def record_decision(txn_id: str, decision: str, risk_band: str = "",
                    risk_score: float | None = None,
                    amount: float | None = None) -> dict:
    """Record one decision. Raises ValueError on an invalid decision."""
    decision = decision.upper()
    if decision not in VALID_DECISIONS:
        raise ValueError(
            f"decision must be one of {VALID_DECISIONS}, got {decision!r}")
    entry = {
        "txn_id": txn_id,
        "decision": decision,
        "risk_band": risk_band,
        "risk_score": risk_score,
        "amount": amount,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    _log.append(entry)
    return entry


def list_decisions() -> list:
    """Most recent decision first."""
    return list(reversed(_log))


def decision_summary() -> dict:
    counts = {d: 0 for d in VALID_DECISIONS}
    for entry in _log:
        counts[entry["decision"]] += 1
    return {"total": len(_log), "by_decision": counts}


def reset_log() -> None:
    """Test helper — clears the in-memory log."""
    _log.clear()
