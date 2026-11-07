"""FastAPI backend for PayGuard AI."""

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from payguard.data import sample_transactions
from payguard.decisions import (
    decision_summary,
    decisions_csv,
    list_decisions,
    record_decision,
)
from payguard.ingest import parse_transactions_csv, sample_csv
from payguard.model import load, score_transaction
from payguard.paypal_client import (
    PayPalClient,
    PayPalError,
    PayPalNotConfigured,
    base_url,
    is_configured,
    order_to_transaction,
)

app = FastAPI(
    title="PayGuard AI",
    description="AI payment-risk copilot for small sellers (PayPal AI Hackathon 2026).",
)


class TransactionIn(BaseModel):
    """One payment to score. Bounds are enforced so a bad payload gets a
    clear 422 instead of a nonsense score (e.g. a negative account age)."""

    id: str = "TXN-1"
    amount: float = Field(gt=0)
    seller_avg_order_value: float = Field(gt=0, default=55.0)
    buyer_account_age_days: int = Field(ge=0, default=365)
    buyer_orders_30d: int = Field(ge=0, default=1)
    seller_velocity_1h: int = Field(ge=0, default=1)
    country_mismatch: int = Field(ge=0, le=1, default=0)
    currency_mismatch: int = Field(ge=0, le=1, default=0)
    hour_of_day: int = Field(ge=0, le=23, default=12)
    is_digital_goods: int = Field(ge=0, le=1, default=0)
    buyer_disputes_90d: int = Field(ge=0, default=0)


@app.get("/health")
def health():
    _, meta = load()
    return {"status": "ok", "model_metrics": meta["metrics"]}


@app.post("/score")
def score(txn: TransactionIn):
    return score_transaction(txn.model_dump())


@app.get("/transactions")
def transactions(n: int = Query(12, ge=1, le=100)):
    return [score_transaction(t) for t in sample_transactions(n=n)]


@app.get("/model")
def model_info():
    _, meta = load()
    return meta


@app.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    """Score every row of an uploaded transaction CSV, riskiest first."""
    try:
        text = (await file.read()).decode("utf-8-sig")
        txns = parse_transactions_csv(text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="file is not UTF-8 text")
    scored = [score_transaction(t) for t in txns]
    scored.sort(key=lambda r: r["risk_score"], reverse=True)
    return {"count": len(scored), "transactions": scored}


class PayPalOrderIn(BaseModel):
    amount: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3, default="USD")
    seller_avg_order_value: float = Field(gt=0, default=55.0)
    seller_currency: str = Field(min_length=3, max_length=3, default="USD")


@app.get("/paypal/status")
def paypal_status():
    """Sandbox wiring status — never exposes credentials."""
    return {
        "configured": is_configured(),
        "base_url": base_url(),
        "mode": "sandbox",
        "hint": (
            None
            if is_configured()
            else "Set PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET from a PayPal "
            "Developer sandbox app to enable the live demo."
        ),
    }


@app.post("/paypal/order")
def paypal_order(order: PayPalOrderIn):
    """Create a live PayPal sandbox order and score it end-to-end.

    Returns the PayPal order (id, status, buyer-approval URL) plus the
    PayGuard risk score for that order — the demo loop: payment in,
    explanation out.
    """
    try:
        created = PayPalClient().create_order(order.amount, order.currency)
    except PayPalNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except PayPalError as e:
        raise HTTPException(status_code=502, detail=str(e))
    txn = order_to_transaction(
        {
            "id": created["id"],
            "purchase_units": [
                {"amount": {"currency_code": order.currency, "value": order.amount}}
            ],
        },
        seller_avg_order_value=order.seller_avg_order_value,
        seller_currency=order.seller_currency,
    )
    return {"order": created, "scored": score_transaction(txn)}


class DecisionIn(BaseModel):
    txn_id: str
    decision: str
    risk_band: str = ""
    risk_score: float | None = None
    amount: float | None = None


@app.post("/decisions", status_code=201)
def post_decision(d: DecisionIn):
    """Record a seller decision (HOLD / REVIEW / APPROVE) on a payment."""
    try:
        entry = record_decision(
            d.txn_id, d.decision, d.risk_band, d.risk_score, d.amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return entry


@app.get("/decisions")
def get_decisions():
    """Decision log, most recent first, plus counts by decision."""
    return {"summary": decision_summary(), "decisions": list_decisions()}


@app.get("/decisions/export")
def export_decisions():
    """Decision log as a CSV download — the seller's action list for
    held/reviewed payments outside the dashboard."""
    return Response(
        content=decisions_csv(),
        media_type="text/csv",
        headers={"Content-Disposition":
                 'attachment; filename="payguard_decisions.csv"'},
    )


@app.get("/sample-csv", response_class=PlainTextResponse)
def get_sample_csv():
    """Example CSV in the accepted format, for sellers to try the upload."""
    return sample_csv()
