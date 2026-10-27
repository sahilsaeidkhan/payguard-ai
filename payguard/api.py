"""FastAPI backend for PayGuard AI."""

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from payguard.data import sample_transactions
from payguard.ingest import parse_transactions_csv, sample_csv
from payguard.model import load, score_transaction

app = FastAPI(
    title="PayGuard AI",
    description="AI payment-risk copilot for small sellers (PayPal AI Hackathon 2026).",
)


class TransactionIn(BaseModel):
    id: str = "TXN-1"
    amount: float = Field(gt=0)
    seller_avg_order_value: float = 55.0
    buyer_account_age_days: int = 365
    buyer_orders_30d: int = 1
    seller_velocity_1h: int = 1
    country_mismatch: int = 0
    currency_mismatch: int = 0
    hour_of_day: int = 12
    is_digital_goods: int = 0
    buyer_disputes_90d: int = 0


@app.get("/health")
def health():
    _, meta = load()
    return {"status": "ok", "model_metrics": meta["metrics"]}


@app.post("/score")
def score(txn: TransactionIn):
    return score_transaction(txn.model_dump())


@app.get("/transactions")
def transactions(n: int = 12):
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


@app.get("/sample-csv", response_class=PlainTextResponse)
def get_sample_csv():
    """Example CSV in the accepted format, for sellers to try the upload."""
    return sample_csv()
