"""Seller decision log — the action half of the risk queue.

Scoring alone is a report; a seller workflow needs the decision recorded:
HOLD a risky payment before shipping, REVIEW a borderline one, APPROVE a
safe one. Decisions persist to ``decisions.json`` next to this package, so
a HOLD survives an API restart — a log that vanished on restart would make
the queue lie about what the seller already decided. Persistence is
best-effort: if the file can't be read or written, the in-memory log still
works and the API never crashes over it.
"""

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

VALID_DECISIONS = ("HOLD", "REVIEW", "APPROVE")

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "decisions.json"
_FILE = _DEFAULT_PATH
_log: list = []
_loaded = False


def _load() -> None:
    """Load persisted decisions once (lazily, so importing the module
    never touches disk before the log is actually used)."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    if _FILE.exists():
        try:
            data = json.loads(_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return  # corrupt/unreadable file: start empty, never crash
        if isinstance(data, list):
            _log.extend(
                e for e in data if isinstance(e, dict) and "txn_id" in e)


def _save() -> None:
    try:
        _FILE.write_text(json.dumps(_log, indent=2), encoding="utf-8")
    except OSError:
        pass  # best-effort: the in-memory log still works


def configure_storage(path) -> None:
    """Test helper — point persistence at a given file and reload from it."""
    global _FILE, _loaded
    _FILE = Path(path)
    _loaded = False
    _log.clear()
    _load()


def record_decision(txn_id: str, decision: str, risk_band: str = "",
                    risk_score: float | None = None,
                    amount: float | None = None) -> dict:
    """Record one decision. Raises ValueError on an invalid decision.

    One payment has exactly one current decision: re-deciding the same
    payment supersedes the earlier entry (it is removed and the new one
    becomes most recent) instead of double-counting it in the log and
    leaving the queue showing a stale state. A seller who HOLDs a payment
    and later APPROVEs it has changed their mind, not made two decisions.
    """
    decision = decision.upper()
    if decision not in VALID_DECISIONS:
        raise ValueError(
            f"decision must be one of {VALID_DECISIONS}, got {decision!r}")
    _load()
    _log[:] = [e for e in _log if e["txn_id"] != txn_id]
    entry = {
        "txn_id": txn_id,
        "decision": decision,
        "risk_band": risk_band,
        "risk_score": risk_score,
        "amount": amount,
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    _log.append(entry)
    _save()
    return entry


def list_decisions() -> list:
    """Most recent decision first."""
    _load()
    return list(reversed(_log))


def decision_summary() -> dict:
    _load()
    counts = {d: 0 for d in VALID_DECISIONS}
    for entry in _log:
        counts[entry["decision"]] += 1
    return {"total": len(_log), "by_decision": counts}


def decisions_csv() -> str:
    """The decision log as CSV (most recent first) — the seller's export
    for acting on held payments outside the dashboard."""
    _load()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["txn_id", "decision", "risk_band", "risk_score",
                     "amount", "decided_at"])
    for e in list_decisions():
        writer.writerow([
            e["txn_id"], e["decision"], e.get("risk_band", ""),
            "" if e.get("risk_score") is None else e["risk_score"],
            "" if e.get("amount") is None else e["amount"],
            e.get("decided_at", ""),
        ])
    return buf.getvalue()


def reset_log() -> None:
    """Test helper — clears the in-memory log and its persisted file."""
    _log.clear()
    try:
        _FILE.unlink(missing_ok=True)
    except OSError:
        pass
